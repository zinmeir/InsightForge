import asyncio

import pytest

from app.services.broker import LogBroker
from app.services.ingest_buffer import BufferFullError, IngestBuffer, SinkResult


class RecordingSink:
    def __init__(self, script=None):
        self.batches: list[list[dict]] = []
        self.script = list(script or [])  # per-call behaviour: "ok" | "fail" | "partial" | Exception

    async def __call__(self, docs):
        self.batches.append(list(docs))
        action = self.script.pop(0) if self.script else "ok"
        if isinstance(action, Exception):
            raise action
        if action == "partial":
            return SinkResult(written=len(docs) - 1, retryable=docs[-1:])
        if action == "reject":
            return SinkResult(written=len(docs) - 1, rejected=1)
        return SinkResult(written=len(docs))


def docs(n):
    return [{"i": i} for i in range(n)]


def test_flushes_by_batch_size_and_drains_on_stop():
    async def scenario():
        sink = RecordingSink()
        buf = IngestBuffer(sink, batch_size=10, flush_interval=10, max_queue_size=1_000)
        await buf.start()
        buf.submit(docs(25))
        await asyncio.sleep(0.05)
        assert [len(b) for b in sink.batches] == [10, 10]  # third batch waits for interval/stop
        await buf.stop()
        assert sum(len(b) for b in sink.batches) == 25

    asyncio.run(scenario())


def test_flushes_by_interval():
    async def scenario():
        sink = RecordingSink()
        buf = IngestBuffer(sink, batch_size=1_000, flush_interval=0.05)
        await buf.start()
        buf.submit(docs(3))
        await asyncio.sleep(0.2)
        assert [len(b) for b in sink.batches] == [3]
        await buf.stop()

    asyncio.run(scenario())


def test_backpressure_is_atomic():
    async def scenario():
        buf = IngestBuffer(RecordingSink(), max_queue_size=100)
        buf.submit(docs(90))
        with pytest.raises(BufferFullError):
            buf.submit(docs(11))
        assert buf.depth == 90

    asyncio.run(scenario())


def test_retries_failures_then_succeeds():
    async def scenario():
        sink = RecordingSink([ConnectionError("es down"), "partial", "ok"])
        buf = IngestBuffer(sink, batch_size=5, flush_interval=0.01, max_retries=3, retry_base_delay=0.001)
        await buf.start()
        buf.submit(docs(5))
        await asyncio.sleep(0.1)
        await buf.stop()
        # full batch, full batch again after exception, then only the retryable doc
        assert [len(b) for b in sink.batches] == [5, 5, 1]
        assert buf.last_flush_error is None

    asyncio.run(scenario())


def test_gives_up_after_max_retries():
    async def scenario():
        sink = RecordingSink([RuntimeError("x")] * 10)
        buf = IngestBuffer(sink, batch_size=2, flush_interval=0.01, max_retries=2, retry_base_delay=0.001)
        await buf.start()
        buf.submit(docs(2))
        await asyncio.sleep(0.1)
        await buf.stop()
        assert len(sink.batches) == 3
        assert buf.last_flush_error == "x"

    asyncio.run(scenario())


def test_rejects_submissions_while_stopping():
    async def scenario():
        buf = IngestBuffer(RecordingSink(), flush_interval=0.01)
        await buf.start()
        await buf.stop()
        buf._stopping.set()
        with pytest.raises(BufferFullError):
            buf.submit(docs(1))

    asyncio.run(scenario())


def test_broker_filters_and_drops_for_slow_consumers():
    async def scenario():
        broker = LogBroker(queue_size=2)
        errors = broker.subscribe(lambda d: d["level"] == "ERROR")
        everything = broker.subscribe()
        for level in ["INFO", "ERROR", "ERROR", "ERROR"]:
            broker.publish({"level": level})
        assert errors.queue.qsize() == 2 and errors.dropped == 1
        assert everything.queue.qsize() == 2 and everything.dropped == 2
        broker.unsubscribe(errors)
        assert broker.subscriber_count == 1

    asyncio.run(scenario())
