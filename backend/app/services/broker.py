"""In-process pub/sub used to fan out freshly ingested logs to live-tail (SSE) clients.

Each subscriber has its own bounded queue; slow consumers drop events rather than slowing down
ingestion. For multi-replica deployments, replace this with Redis pub/sub or similar.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.core import metrics

Filter = Callable[[dict[str, Any]], bool]


@dataclass(eq=False)
class Subscription:
    queue: asyncio.Queue[dict[str, Any]]
    accepts: Filter
    dropped: int = field(default=0)


class LogBroker:
    def __init__(self, queue_size: int = 1_000) -> None:
        self._queue_size = queue_size
        self._subs: set[Subscription] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def subscribe(self, accepts: Filter | None = None) -> Subscription:
        sub = Subscription(asyncio.Queue(maxsize=self._queue_size), accepts or (lambda _doc: True))
        self._subs.add(sub)
        metrics.STREAM_SUBSCRIBERS.set(len(self._subs))
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.discard(sub)
        metrics.STREAM_SUBSCRIBERS.set(len(self._subs))

    def publish(self, doc: dict[str, Any]) -> None:
        for sub in self._subs:
            if not sub.accepts(doc):
                continue
            try:
                sub.queue.put_nowait(doc)
            except asyncio.QueueFull:
                sub.dropped += 1
