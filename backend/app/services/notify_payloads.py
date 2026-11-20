"""Builders for outbound notification payloads (pure, unit-testable)."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Literal

from app.schemas import Alert

Event = Literal["opened", "resolved"]

_SEVERITY_EMOJI = {"critical": ":red_circle:", "warning": ":large_orange_circle:", "info": ":large_blue_circle:"}
_PAGERDUTY_SEVERITY = {"critical": "critical", "warning": "warning", "info": "info"}


def slack_payload(alert: Alert, event: Event, dashboard_url: str) -> dict[str, Any]:
    if event == "resolved":
        headline = f":white_check_mark: *Resolved* - {alert.rule_name}"
    else:
        headline = f"{_SEVERITY_EMOJI.get(alert.severity, '')} *{alert.severity.upper()}* - {alert.summary}"
    fields = [
        {"type": "mrkdwn", "text": f"*Service*\n{alert.service or 'all services'}"},
        {"type": "mrkdwn", "text": f"*Occurrences*\n{alert.count}"},
        {"type": "mrkdwn", "text": f"*First seen*\n{alert.first_seen.isoformat(timespec='seconds')}"},
        {"type": "mrkdwn", "text": f"*Last seen*\n{alert.last_seen.isoformat(timespec='seconds')}"},
    ]
    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": headline}},
        {"type": "section", "fields": fields},
    ]
    if alert.sample_message and event == "opened":
        sample = alert.sample_message[:500].replace("```", "'''")
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"```{sample}```"}})
    blocks.append(
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open dashboard"},
                    "url": f"{dashboard_url.rstrip('/')}/#/alerts",
                }
            ],
        }
    )
    # `text` is the fallback shown in notifications and by clients that cannot render blocks.
    return {"text": headline.replace("*", ""), "blocks": blocks}


def pagerduty_payload(alert: Alert, event: Event, routing_key: str, dashboard_url: str) -> dict[str, Any]:
    if event == "resolved":
        return {"routing_key": routing_key, "event_action": "resolve", "dedup_key": alert.fingerprint}
    return {
        "routing_key": routing_key,
        "event_action": "trigger",
        "dedup_key": alert.fingerprint,
        "payload": {
            "summary": alert.summary[:1024],
            "source": alert.service or "insightforge",
            "severity": _PAGERDUTY_SEVERITY.get(alert.severity, "error"),
            "timestamp": alert.first_seen.isoformat(),
            "component": alert.service,
            "class": alert.rule_name,
            "custom_details": {
                "rule_id": alert.rule_id,
                "count": alert.count,
                "sample_message": alert.sample_message,
            },
        },
        "links": [{"href": f"{dashboard_url.rstrip('/')}/#/alerts", "text": "InsightForge"}],
    }


def webhook_payload(alert: Alert, event: Event) -> dict[str, Any]:
    return {"event": f"alert.{event}", "alert": alert.model_dump(mode="json")}


def sign_body(body: bytes, secret: str) -> str:
    """HMAC-SHA256 signature sent as ``X-InsightForge-Signature: sha256=<hex>``."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def encode_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), default=str).encode()
