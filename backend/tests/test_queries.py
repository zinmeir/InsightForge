from datetime import datetime, timedelta, timezone

import pytest

from app.schemas import LogLevel
from app.services import queries
from app.services.queries import QueryError, TimeRange

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def test_parse_relative_and_absolute_times():
    assert queries.parse_time("now", NOW) == NOW
    assert queries.parse_time("now-15m", NOW) == NOW - timedelta(minutes=15)
    assert queries.parse_time("now-2d", NOW) == NOW - timedelta(days=2)
    assert queries.parse_time("2026-01-01T10:00:00Z", NOW) == datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
    # Naive timestamps are treated as UTC.
    assert queries.parse_time("2026-01-01T10:00:00", NOW).tzinfo is not None


@pytest.mark.parametrize("bad", ["yesterday", "now-5x", "now+1h", "2026-13-01"])
def test_parse_time_rejects_garbage(bad):
    with pytest.raises(QueryError):
        queries.parse_time(bad, NOW)


def test_time_range_validation():
    with pytest.raises(QueryError):
        TimeRange.parse("now", "now-1h")
    with pytest.raises(QueryError):
        TimeRange.parse("now-200d", "now")
    rng = TimeRange.parse("now-1h", None)
    assert 3_599 <= rng.seconds <= 3_601


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(60, "1s"), (900, "30s"), (3_600, "1m"), (86_400, "30m"), (7 * 86_400, "3h"), (90 * 86_400, "7d")],
)
def test_pick_interval_targets_about_60_buckets(seconds, expected):
    assert queries.pick_interval(seconds)[0] == expected


def test_build_log_query_combines_filters():
    rng = TimeRange(NOW - timedelta(hours=1), NOW)
    q = queries.build_log_query(
        time_range=rng,
        text='"connection reset" -retry',
        levels=[LogLevel.ERROR, LogLevel.CRITICAL],
        services=["auth", "payment-*"],
        trace_id="abc",
    )
    filters = q["bool"]["filter"]
    assert filters[0]["range"]["@timestamp"]["gte"] == rng.start.isoformat()
    assert filters[1] == {"terms": {"level": ["ERROR", "CRITICAL"]}}
    service_should = filters[2]["bool"]["should"]
    assert {"terms": {"service": ["auth"]}} in service_should
    assert {"wildcard": {"service": {"value": "payment-*"}}} in service_should
    assert filters[3] == {"term": {"trace_id": "abc"}}
    assert q["bool"]["must"][0]["simple_query_string"]["query"] == '"connection reset" -retry'


def test_build_log_query_without_filters_is_match_all():
    assert queries.build_log_query() == {"match_all": {}}
    assert queries.build_log_query(text="   ") == {"match_all": {}}


def test_cursor_round_trip_and_validation():
    values = [1767268800000, "a1b2c3"]
    assert queries.decode_cursor(queries.encode_cursor(values)) == values
    for bad in ["!!!", queries.encode_cursor([1]), queries.encode_cursor([{"x": 1}, "a"])]:
        with pytest.raises(QueryError):
            queries.decode_cursor(bad)


def test_parse_aggregations():
    resp = {
        "hits": {"total": {"value": 10}},
        "aggregations": {
            "levels": {"buckets": [{"key": "INFO", "doc_count": 7}, {"key": "ERROR", "doc_count": 3}]},
            "services": {"value": 4},
            "over_time": {
                "buckets": [
                    {"key": 1767268800000, "doc_count": 2, "levels": {"buckets": [{"key": "WARN", "doc_count": 2}]}}
                ]
            },
            "by_service": {
                "buckets": [
                    {
                        "key": "api",
                        "doc_count": 4,
                        "levels": {"buckets": [{"key": "CRITICAL", "doc_count": 1}, {"key": "INFO", "doc_count": 3}]},
                    }
                ]
            },
        },
    }
    total, counts, error_rate, services = queries.parse_overview(resp)
    assert (total, counts.INFO, counts.ERROR, error_rate, services) == (10, 7, 3, 0.3, 4)

    [bucket] = queries.parse_histogram(resp)
    assert bucket.WARN == 2 and bucket.time == datetime(2026, 1, 1, 12, tzinfo=timezone.utc)

    [svc] = queries.parse_services(resp)
    assert svc.service == "api" and svc.error_rate == 0.25


def test_histogram_bounds_are_epoch_millis():
    rng = TimeRange(NOW - timedelta(hours=1), NOW)
    bounds = queries.histogram_aggs(rng, "1m")["over_time"]["date_histogram"]["extended_bounds"]
    assert bounds == {"min": int((NOW - timedelta(hours=1)).timestamp() * 1000), "max": int(NOW.timestamp() * 1000)}
