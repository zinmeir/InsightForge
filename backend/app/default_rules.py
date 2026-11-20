"""Rules seeded the first time InsightForge starts against an empty cluster."""

from __future__ import annotations

from app.schemas import AlertRule, LogLevel, RuleCondition


def default_rules() -> list[AlertRule]:
    return [
        AlertRule(
            name="Critical log",
            description="Any CRITICAL log opens an alert for its service.",
            severity="critical",
            condition=RuleCondition(levels=[LogLevel.CRITICAL], threshold=1, window_seconds=60),
            cooldown_seconds=300,
            auto_resolve_seconds=900,
            notify=["slack", "pagerduty", "webhook"],
        ),
        AlertRule(
            name="Error spike",
            description="20+ ERROR/CRITICAL logs from one service within a minute.",
            severity="warning",
            condition=RuleCondition(
                levels=[LogLevel.ERROR, LogLevel.CRITICAL], threshold=20, window_seconds=60
            ),
            cooldown_seconds=600,
            auto_resolve_seconds=600,
            notify=["slack", "webhook"],
        ),
        AlertRule(
            name="Payment timeouts",
            description="Example of a message-matching rule scoped to services by wildcard.",
            severity="critical",
            condition=RuleCondition(
                services=["payment*"], message_contains="timeout", threshold=3, window_seconds=120
            ),
            cooldown_seconds=600,
            auto_resolve_seconds=900,
            notify=["slack", "pagerduty"],
        ),
    ]
