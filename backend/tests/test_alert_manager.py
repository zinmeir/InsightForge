import asyncio
from datetime import timedelta

import pytest

from app.schemas import Alert, AlertRule, RuleCondition, utcnow
from app.services.alert_engine import AlertEngine
from app.services.alert_manager import AlertConflictError, AlertManager


class MemoryStore:
    def __init__(self):
        self.saved: dict[str, Alert] = {}
        self.writes = 0

    async def save(self, alert, *, refresh=False):
        self.writes += 1
        self.saved[alert.id] = alert.model_copy()

    async def get(self, alert_id):
        return self.saved.get(alert_id)

    async def list_open(self):
        return [a for a in self.saved.values() if a.status != "resolved"]


class RecordingNotifier:
    def __init__(self):
        self.events = []

    def dispatch(self, alert, event, channels):
        self.events.append((event, alert.fingerprint, tuple(channels)))


def run(coro):
    return asyncio.run(coro)


async def _drain(manager: AlertManager):
    # Let the consumer task process queued matches.
    for _ in range(20):
        await asyncio.sleep(0)
        if manager._matches.empty():
            await asyncio.sleep(0)
            return


def build(**rule_kwargs):
    rule = AlertRule(name="crit", notify=["slack"], **rule_kwargs)
    store, notifier = MemoryStore(), RecordingNotifier()
    manager = AlertManager(AlertEngine(), store, notifier, sweep_interval=3_600)
    return rule, store, notifier, manager


def test_opens_once_then_deduplicates():
    async def scenario():
        rule, store, notifier, manager = build()
        await manager.start([rule])
        for _ in range(5):
            manager.process({"level": "CRITICAL", "service": "pay", "message": "down"})
        await _drain(manager)
        [alert] = manager.open_alerts
        assert alert.count == 5 and alert.status == "firing"
        assert notifier.events == [("opened", alert.fingerprint, ("slack",))]
        await manager.stop()  # flushes debounced counters
        assert store.saved[alert.id].count == 5

    run(scenario())


def test_acknowledge_then_resolve_notifies():
    async def scenario():
        rule, store, notifier, manager = build()
        await manager.start([rule])
        manager.process({"level": "ERROR", "service": "api", "message": "x"})
        await _drain(manager)
        [alert] = manager.open_alerts
        acked = await manager.acknowledge(alert.id, "alice")
        assert acked.status == "acknowledged" and acked.acknowledged_by == "alice"
        resolved = await manager.resolve(alert.id, "alice")
        assert resolved.status == "resolved" and manager.open_alerts == []
        assert notifier.events[-1][0] == "resolved"
        with pytest.raises(AlertConflictError):
            await manager.resolve(alert.id, "alice")
        await manager.stop()

    run(scenario())


def test_auto_resolve_and_cooldown_after_resolution():
    async def scenario():
        rule, store, notifier, manager = build(cooldown_seconds=3_600, auto_resolve_seconds=60)
        await manager.start([rule])
        manager.process({"level": "ERROR", "service": "api", "message": "x"})
        await _drain(manager)
        [alert] = manager.open_alerts
        await manager.sweep(now=alert.last_seen + timedelta(seconds=61))
        assert manager.open_alerts == []
        assert store.saved[alert.id].resolved_reason == "auto"
        # Still inside the cooldown: a new match must not reopen an alert.
        manager.process({"level": "ERROR", "service": "api", "message": "x"})
        await _drain(manager)
        assert manager.open_alerts == []
        await manager.stop()

    run(scenario())


def test_resolves_alerts_of_deleted_rules_and_restores_open_alerts():
    async def scenario():
        rule, store, notifier, manager = build()
        existing = Alert(
            fingerprint=f"{rule.id}:api", rule_id=rule.id, rule_name=rule.name,
            severity="warning", service="api", summary="s", first_seen=utcnow(),
        )  # fmt: skip
        await store.save(existing)
        await manager.start([rule])
        assert [a.id for a in manager.open_alerts] == [existing.id]
        assert await manager.resolve_for_rule(rule.id, "rule_deleted") == 1
        assert manager.open_alerts == []
        await manager.stop()

    run(scenario())


def test_threshold_rule_count_starts_at_window_count():
    async def scenario():
        rule, store, notifier, manager = build(condition=RuleCondition(threshold=3, window_seconds=60))
        await manager.start([rule])
        for _ in range(3):
            manager.process({"level": "ERROR", "service": "api", "message": "x"})
        await _drain(manager)
        [alert] = manager.open_alerts
        assert alert.count == 3
        assert "3 matching logs" in alert.summary
        await manager.stop()

    run(scenario())
