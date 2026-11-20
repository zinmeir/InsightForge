"""Asynchronous ingest buffer that batches documents into bulk writes.

Requests enqueue documents and return immediately (HTTP 202). A single background worker drains
the queue, flushing whenever ``batch_size`` documents are waiting or ``flush_interval`` elapses.
When the queue is full, :meth:`IngestBuffer.submit` raises :class:`BufferFullError`, which the
API turns into ``503 Retry-After`` - explicit backpressure instead of unbounded memory growth.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from app.core import metrics

logger = logging.getLogger(__name__)


@dataclass
class SinkResult:
    """Outcome of one bulk write."""

    written: int = 0
    retryable: list[dict[str, Any]] = field(default_factory=list)
    rejected: int = 0  # permanent failures (e.g. mapping errors) - retrying will not help


Sink = Callable[[list[dict[str, Any]]], Awaitable[SinkResult]]


class BufferFullError(Exception):
    pass


_WAKE: dict[str, Any] = {}  # sentinel used to wake the worker on shutdown


class IngestBuffer:
    def __init__(
        self,
        sink: Sink,
        *,
        batch_size: int = 500,
        flush_interval: float = 1.0,
        max_queue_size: int = 50_000,
        max_retries: int = 3,
        retry_base_delay: float = 0.5,
    ) -> None:
        self._sink = sink
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_queue_size)
        self._worker: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()
        self.last_flush_error: str | None = None
        self.last_flush_at: float | None = None

    # -- lifecycle ------------------------------------------------------------------

    async def start(self) -> None:
        if self._worker is None:
            self._stopping.clear()
            self._worker = asyncio.create_task(self._run(), name="ingest-buffer")

    async def stop(self, timeout: float = 15.0) -> None:
        """Stop accepting work and flush whatever is still queued."""
        if self._worker is None:
            return
        self._stopping.set()
        with contextlib.suppress(asyncio.QueueFull):  # if full, the worker isn't blocked anyway
            self._queue.put_nowait(_WAKE)
        try:
            await asyncio.wait_for(self._worker, timeout=timeout)
        except TimeoutError:
            logger.error("ingest buffer did not drain in time; %d logs lost", self._queue.qsize())
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
        self._worker = None

    @property
    def running(self) -> bool:
        return self._worker is not None and not self._worker.done()

    @property
    def depth(self) -> int:
        return self._queue.qsize()  # may include the shutdown sentinel; close enough for a gauge

    @property
    def capacity(self) -> int:
        return self._queue.maxsize

    # -- producer side ----------------------------------------------------------------

    def submit(self, docs: list[dict[str, Any]]) -> None:
        """Enqueue documents atomically: either all are accepted or none are."""
        if self._stopping.is_set():
            raise BufferFullError("ingest buffer is shutting down")
        if self._queue.qsize() + len(docs) > self._queue.maxsize:
            metrics.LOGS_REJECTED.labels(reason="buffer_full").inc(len(docs))
            raise BufferFullError("ingest buffer is full")
        for doc in docs:
            self._queue.put_nowait(doc)
        metrics.INGEST_QUEUE_DEPTH.set(self._queue.qsize())

    # -- consumer side ----------------------------------------------------------------

    async def _run(self) -> None:
        while True:
            batch = await self._collect_batch()
            if batch:
                await self._flush(batch)
            elif self._stopping.is_set() and self._queue.empty():
                return

    async def _collect_batch(self) -> list[dict[str, Any]]:
        batch: list[dict[str, Any]] = []
        deadline = time.monotonic() + self._flush_interval
        while len(batch) < self._batch_size:
            # Fast path: drain whatever is already queued without awaiting.
            try:
                item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            else:
                if item is not _WAKE:
                    batch.append(item)
                continue
            if self._stopping.is_set():
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=remaining)
            except TimeoutError:
                break
            if item is not _WAKE:
                batch.append(item)
        metrics.INGEST_QUEUE_DEPTH.set(self._queue.qsize())
        return batch

    async def _flush(self, batch: list[dict[str, Any]]) -> None:
        pending = batch
        for attempt in range(self._max_retries + 1):
            started = time.perf_counter()
            try:
                result = await self._sink(pending)
            except Exception as exc:  # network error, ES down, ...
                logger.warning("bulk flush failed (attempt %d): %s", attempt + 1, exc)
                self.last_flush_error = str(exc)
                result = SinkResult(retryable=pending)
            finally:
                metrics.BULK_LATENCY.observe(time.perf_counter() - started)

            if result.written:
                metrics.LOGS_INDEXED.inc(result.written)
            if result.rejected:
                metrics.LOGS_DROPPED.labels(reason="rejected").inc(result.rejected)
                logger.error("%d logs permanently rejected by Elasticsearch", result.rejected)
            if not result.retryable:
                self.last_flush_at = time.time()
                if not result.rejected:
                    self.last_flush_error = None
                return
            pending = result.retryable
            if attempt < self._max_retries:
                await asyncio.sleep(self._retry_base_delay * (2**attempt))

        metrics.LOGS_DROPPED.labels(reason="retries_exhausted").inc(len(pending))
        logger.error("dropping %d logs after %d retries", len(pending), self._max_retries)
