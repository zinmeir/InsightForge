import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.core import security
from app.schemas import Alert, AlertRule, AlertRuleUpdate, LogEntryIn, LogLevel, LogRecord
from app.services import notify_payloads as payloads


def test_log_entry_normalizes_and_builds_document():
    entry = LogEntryIn(
        level="warning",
        service="payment-gateway",
        message="slow",
        timestamp="2026-01-01T10:00:00+05:00",
        attributes={"latency_ms": 812, "retry": True, "region": None},
    )
    assert entry.level is LogLevel.WARN
    doc = entry.to_document()
    assert doc["@timestamp"] == "2026-01-01T05:00:00+00:00"
    assert doc["attributes"] == {"latency_ms": "812", "retry": "True", "region": ""}
    assert len(doc["event_id"]) == 32
    assert "host" not in doc

    record = LogRecord.from_document(doc)
    assert record.id == doc["event_id"] and record.level is LogLevel.WARN


def test_log_entry_defaults_timestamp_to_receive_time():
    received = datetime(2026, 1, 1, tzinfo=timezone.utc)
    doc = LogEntryIn(level="INFO", service="a", message="b").to_document(received)
    assert doc["@timestamp"] == doc["ingested_at"] == received.isoformat()


@pytest.mark.parametrize(
    "payload",
    [
        {"level": "LOUD", "service": "a", "message": "b"},
        {"level": "INFO", "service": "has spaces", "message": "b"},
        {"level": "INFO", "service": "a", "message": ""},
        {"level": "INFO", "service": "a", "message": "b", "unexpected": 1},
        {"level": "INFO", "service": "a", "message": "b", "attributes": {"_private": "x"}},
        {"level": "INFO", "service": "a", "message": "b", "attributes": {f"k{i}": i for i in range(65)}},
    ],
)
def test_log_entry_rejects_invalid_payloads(payload):
    with pytest.raises(ValidationError):
        LogEntryIn(**payload)


def test_rule_partial_update():
    rule = AlertRule(name="r", severity="warning")
    updated = rule.apply_update(AlertRuleUpdate(severity="critical", enabled=False))
    assert (updated.id, updated.name, updated.severity, updated.enabled) == (rule.id, "r", "critical", False)
    assert updated.updated_at >= rule.updated_at


def test_jwt_round_trip_and_tampering():
    token, expires_in = security.create_access_token("alice", "admin", secret="s" * 32, expires_minutes=5)
    assert expires_in == 300
    claims = security.decode_access_token(token, secret="s" * 32)
    assert claims["sub"] == "alice" and claims["role"] == "admin"
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token, secret="t" * 32)
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token + "x", secret="s" * 32)


def test_expired_and_bad_role_tokens_are_rejected():
    expired, _ = security.create_access_token("a", "admin", secret="k" * 32, expires_minutes=-1)
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(expired, secret="k" * 32)
    weird, _ = security.create_access_token("a", "root", secret="k" * 32)
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(weird, secret="k" * 32)


def test_api_key_verification():
    assert security.verify_api_key("abc", ["zzz", "abc"])
    assert not security.verify_api_key("abd", ["abc"])
    assert not security.verify_api_key(None, ["abc"])
    assert not security.verify_api_key("abc", [])


def _alert():
    return Alert(
        fingerprint="r1:payments", rule_id="r1", rule_name="Critical log", severity="critical",
        service="payments", summary="Critical log: matching log in payments", sample_message="Stripe ```timeout```",
    )  # fmt: skip


def test_slack_and_pagerduty_payloads():
    alert = _alert()
    slack = payloads.slack_payload(alert, "opened", "https://if.example.com/")
    assert "CRITICAL" in slack["text"]
    assert slack["blocks"][-1]["elements"][0]["url"] == "https://if.example.com/#/alerts"
    assert "```Stripe '''timeout'''```" in json.dumps(slack)

    trigger = payloads.pagerduty_payload(alert, "opened", "rk", "https://x")
    assert trigger["event_action"] == "trigger" and trigger["dedup_key"] == "r1:payments"
    assert trigger["payload"]["severity"] == "critical"
    resolve = payloads.pagerduty_payload(alert, "resolved", "rk", "https://x")
    assert resolve == {"routing_key": "rk", "event_action": "resolve", "dedup_key": "r1:payments"}


def test_webhook_signature_is_stable_hmac():
    body = payloads.encode_json(payloads.webhook_payload(_alert(), "opened"))
    sig = payloads.sign_body(body, "secret")
    assert sig.startswith("sha256=") and sig == payloads.sign_body(body, "secret")
    assert sig != payloads.sign_body(body, "other")
