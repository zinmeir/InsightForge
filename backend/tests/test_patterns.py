from datetime import datetime, timedelta, timezone

import pytest

from app.services.patterns import extract_patterns, search_query_for, to_template

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("message", "template"),
    [
        ("timeout after 12043ms calling stripe", "timeout after <num>ms calling stripe"),
        ("GET /v1/orders 200 in 42ms", "GET /v1/orders <num> in <num>ms"),
        ("user user_4821 logged in", "user user_<num> logged in"),
        ("cache lookup key=9f2ab1c0", "cache lookup key=<hex>"),
        ("query 'red shoes' returned 12 hits", "query '<str>' returned <num> hits"),
        ("connect to 10.0.3.17:5432 refused", "connect to <ip> refused"),
        ("job 3f2b6c1e-9d4a-4b8e-a1c2-7e5f0a9b3c4d failed", "job <uuid> failed"),
        ("webhook https://hooks.example.com/x?id=9 returned 503", "webhook <url> returned <num>"),
        ("mail to ops@example.com bounced", "mail to <email> bounced"),
        ("disk at 98.5% on /var/lib", "disk at <num>% on /var/lib"),
        ("can't connect, don't retry", "can't connect, don't retry"),
        ("deadlock   detected\n retrying", "deadlock detected retrying"),
    ],
)
def test_to_template(message, template):
    assert to_template(message) == template


def test_search_query_drops_words_glued_to_placeholders():
    assert search_query_for("timeout after <num>ms calling stripe") == '"timeout after" "calling stripe"'
    assert search_query_for("query '<str>' returned <num> hits") == '"query" "returned" "hits"'
    assert search_query_for("<num>") == "<num>"


def doc(message, minutes, level="ERROR", service="api"):
    ts = (T0 + timedelta(minutes=minutes)).isoformat()
    return {"message": message, "@timestamp": ts, "level": level, "service": service}


def test_extract_patterns_groups_counts_and_trends():
    stripe_minutes = [1, 2, 50, 55, 56, 57, 58]
    docs = (
        [doc(f"timeout after {i}ms calling stripe", m, service="payments") for i, m in enumerate(stripe_minutes)]
        + [doc(f"upstream returned {code}", m) for code, m in [(503, 0), (502, 3), (503, 4), (503, 59)]]
        + [
            doc("disk full on node 7", 58, level="CRITICAL", service="db"),
            doc("disk full on node 9", 60, level="CRITICAL", service="db"),
        ]
    )
    patterns = extract_patterns(docs)
    by_template = {p.pattern: p for p in patterns}

    stripe = by_template["timeout after <num>ms calling stripe"]
    assert stripe.count == 7 and stripe.services == ["payments"] and stripe.trend == "rising"
    assert stripe.share == round(7 / 13, 4)
    assert stripe.example == "timeout after 6ms calling stripe"  # newest occurrence
    assert stripe.first_seen == T0 + timedelta(minutes=1)

    assert by_template["upstream returned <num>"].trend == "falling"
    disk = by_template["disk full on node <num>"]
    assert disk.trend == "new" and disk.by_level.CRITICAL == 2
    assert [p.pattern for p in patterns][0] == "timeout after <num>ms calling stripe"


def test_extract_patterns_limit_and_empty():
    assert extract_patterns([]) == []
    docs = [doc(f"distinct message {chr(97 + i)}{chr(97 + i)}{chr(97 + i)}", i) for i in range(10)]
    assert len(extract_patterns(docs, limit=3)) == 3
