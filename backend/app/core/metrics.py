"""Prometheus metrics.

Falls back to no-op stand-ins if ``prometheus_client`` is not installed, so pure modules that
record metrics stay importable in minimal environments (e.g. isolated unit tests).
"""

from __future__ import annotations

from typing import Any

try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

    PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the dependency
    PROMETHEUS_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    class _NoOp:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def labels(self, *args: Any, **kwargs: Any) -> _NoOp:
            return self

        def inc(self, *args: Any, **kwargs: Any) -> None:
            pass

        def dec(self, *args: Any, **kwargs: Any) -> None:
            pass

        def set(self, *args: Any, **kwargs: Any) -> None:
            pass

        def observe(self, *args: Any, **kwargs: Any) -> None:
            pass

    Counter = Gauge = Histogram = _NoOp  # type: ignore[misc,assignment]

    def generate_latest(*args: Any, **kwargs: Any) -> bytes:  # type: ignore[misc]
        return b""


HTTP_REQUESTS = Counter(
    "insightforge_http_requests_total", "HTTP requests", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "insightforge_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
LOGS_RECEIVED = Counter("insightforge_logs_received_total", "Logs accepted by the API", ["level"])
LOGS_REJECTED = Counter(
    "insightforge_logs_rejected_total", "Logs rejected before buffering", ["reason"]
)
LOGS_INDEXED = Counter("insightforge_logs_indexed_total", "Logs written to Elasticsearch")
LOGS_DROPPED = Counter(
    "insightforge_logs_dropped_total", "Logs that could not be written", ["reason"]
)
BULK_LATENCY = Histogram(
    "insightforge_bulk_flush_duration_seconds",
    "Elasticsearch bulk flush latency",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
INGEST_QUEUE_DEPTH = Gauge("insightforge_ingest_queue_depth", "Logs waiting to be flushed")
ALERTS_OPENED = Counter("insightforge_alerts_opened_total", "Alerts opened", ["severity"])
NOTIFICATIONS = Counter(
    "insightforge_notifications_total", "Notification attempts", ["channel", "outcome"]
)
STREAM_SUBSCRIBERS = Gauge("insightforge_stream_subscribers", "Connected live-tail clients")

__all__ = [
    "ALERTS_OPENED",
    "BULK_LATENCY",
    "CONTENT_TYPE_LATEST",
    "HTTP_LATENCY",
    "HTTP_REQUESTS",
    "INGEST_QUEUE_DEPTH",
    "LOGS_DROPPED",
    "LOGS_INDEXED",
    "LOGS_RECEIVED",
    "LOGS_REJECTED",
    "NOTIFICATIONS",
    "PROMETHEUS_AVAILABLE",
    "STREAM_SUBSCRIBERS",
    "generate_latest",
]
