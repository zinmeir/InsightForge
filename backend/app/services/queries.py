"""Elasticsearch query/aggregation builders and response parsers (pure functions)."""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.schemas import HistogramBucket, LevelCounts, LogLevel, ServiceStat

LOG_SORT: list[dict[str, Any]] = [
    {"@timestamp": {"order": "desc"}},
    {"event_id": {"order": "desc"}},
]

_RELATIVE = re.compile(r"^now(?:-(?P<amount>\d+)(?P<unit>[smhdw]))?$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3_600, "d": 86_400, "w": 604_800}

# Candidate histogram intervals, smallest first, as (ES fixed_interval, seconds).
INTERVALS: list[tuple[str, int]] = [
    ("1s", 1), ("5s", 5), ("10s", 10), ("30s", 30),
    ("1m", 60), ("5m", 300), ("10m", 600), ("30m", 1_800),
    ("1h", 3_600), ("3h", 10_800), ("6h", 21_600), ("12h", 43_200),
    ("1d", 86_400), ("7d", 604_800),
]  # fmt: skip

MAX_RANGE = timedelta(days=90)


class QueryError(ValueError):
    """Raised for invalid user-supplied query parameters (mapped to HTTP 400)."""


# ---------------------------------------------------------------------------
# Time handling
# ---------------------------------------------------------------------------


def parse_time(value: str, now: datetime | None = None) -> datetime:
    """Parse ``now``, ``now-15m`` style relative times or ISO-8601 timestamps to aware UTC."""
    now = now or datetime.now(timezone.utc)
    value = value.strip()
    match = _RELATIVE.match(value)
    if match:
        if not match.group("amount"):
            return now
        return now - timedelta(seconds=int(match.group("amount")) * _UNIT_SECONDS[match.group("unit")])
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QueryError(f"invalid time {value!r}: use ISO-8601 or now-<n><s|m|h|d|w>") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class TimeRange:
    start: datetime
    end: datetime

    @classmethod
    def parse(cls, start: str | None, end: str | None, default_start: str = "now-1h") -> TimeRange:
        now = datetime.now(timezone.utc)
        rng = cls(parse_time(start or default_start, now), parse_time(end or "now", now))
        if rng.start >= rng.end:
            raise QueryError("'from' must be before 'to'")
        if rng.end - rng.start > MAX_RANGE:
            raise QueryError(f"time range may not exceed {MAX_RANGE.days} days")
        return rng

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    def as_filter(self) -> dict[str, Any]:
        return {
            "range": {
                "@timestamp": {"gte": self.start.isoformat(), "lte": self.end.isoformat()}
            }
        }


def pick_interval(seconds: float, target_buckets: int = 60) -> tuple[str, int]:
    for name, size in INTERVALS:
        if seconds / size <= target_buckets:
            return name, size
    return INTERVALS[-1]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def build_log_query(
    *,
    time_range: TimeRange | None = None,
    text: str | None = None,
    levels: list[LogLevel] | None = None,
    services: list[str] | None = None,
    trace_id: str | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    filters: list[dict[str, Any]] = []
    must: list[dict[str, Any]] = []

    if time_range:
        filters.append(time_range.as_filter())
    if levels:
        filters.append({"terms": {"level": [lvl.value for lvl in levels]}})
    if services:
        exact = [s for s in services if "*" not in s and "?" not in s]
        patterns = [s for s in services if s not in exact]
        should: list[dict[str, Any]] = []
        if exact:
            should.append({"terms": {"service": exact}})
        should.extend({"wildcard": {"service": {"value": p}}} for p in patterns)
        filters.append({"bool": {"should": should, "minimum_should_match": 1}})
    if trace_id:
        filters.append({"term": {"trace_id": trace_id}})
    if host:
        filters.append({"term": {"host": host}})
    if text and text.strip():
        # simple_query_string never throws on bad syntax and supports "phrases", -exclusion, OR (|).
        must.append(
            {
                "simple_query_string": {
                    "query": text.strip(),
                    "fields": ["message"],
                    "default_operator": "AND",
                    "flags": "AND|OR|NOT|PHRASE|PREFIX|PRECEDENCE|WHITESPACE|ESCAPE",
                }
            }
        )
    if not filters and not must:
        return {"match_all": {}}
    query: dict[str, Any] = {"bool": {}}
    if filters:
        query["bool"]["filter"] = filters
    if must:
        query["bool"]["must"] = must
    return query


def encode_cursor(sort_values: list[Any]) -> str:
    raw = json.dumps(sort_values, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> list[Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        values = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise QueryError("invalid cursor") from exc
    if (
        not isinstance(values, list)
        or len(values) != len(LOG_SORT)
        or not all(isinstance(v, (int, float, str)) for v in values)
    ):
        raise QueryError("invalid cursor")
    return values


# ---------------------------------------------------------------------------
# Aggregations
# ---------------------------------------------------------------------------


def _level_counts(level_buckets: list[dict[str, Any]]) -> LevelCounts:
    counts = LevelCounts()
    for bucket in level_buckets:
        key = bucket.get("key")
        if key in LevelCounts.model_fields:
            setattr(counts, key, bucket.get("doc_count", 0))
    return counts


def _error_rate(counts: LevelCounts, total: int) -> float:
    return round((counts.ERROR + counts.CRITICAL) / total, 4) if total else 0.0


def overview_aggs() -> dict[str, Any]:
    return {
        "levels": {"terms": {"field": "level", "size": 10}},
        "services": {"cardinality": {"field": "service"}},
    }


def parse_overview(resp: dict[str, Any]) -> tuple[int, LevelCounts, float, int]:
    total = resp["hits"]["total"]["value"]
    aggs = resp.get("aggregations", {})
    counts = _level_counts(aggs.get("levels", {}).get("buckets", []))
    services = aggs.get("services", {}).get("value", 0)
    return total, counts, _error_rate(counts, total), services


def histogram_aggs(time_range: TimeRange, interval: str) -> dict[str, Any]:
    return {
        "over_time": {
            "date_histogram": {
                "field": "@timestamp",
                "fixed_interval": interval,
                "min_doc_count": 0,
                "extended_bounds": {
                    "min": int(time_range.start.timestamp() * 1000),
                    "max": int(time_range.end.timestamp() * 1000),
                },
            },
            "aggs": {"levels": {"terms": {"field": "level", "size": 10}}},
        }
    }


def parse_histogram(resp: dict[str, Any]) -> list[HistogramBucket]:
    buckets = resp.get("aggregations", {}).get("over_time", {}).get("buckets", [])
    out = []
    for b in buckets:
        counts = _level_counts(b.get("levels", {}).get("buckets", []))
        out.append(
            HistogramBucket(
                time=datetime.fromtimestamp(b["key"] / 1000, tz=timezone.utc), **counts.model_dump()
            )
        )
    return out


def services_aggs(size: int = 20) -> dict[str, Any]:
    return {
        "by_service": {
            "terms": {"field": "service", "size": size, "order": {"_count": "desc"}},
            "aggs": {"levels": {"terms": {"field": "level", "size": 10}}},
        }
    }


def parse_services(resp: dict[str, Any]) -> list[ServiceStat]:
    out = []
    for b in resp.get("aggregations", {}).get("by_service", {}).get("buckets", []):
        counts = _level_counts(b.get("levels", {}).get("buckets", []))
        total = b.get("doc_count", 0)
        out.append(
            ServiceStat(
                service=b["key"], total=total, by_level=counts, error_rate=_error_rate(counts, total)
            )
        )
    return out
