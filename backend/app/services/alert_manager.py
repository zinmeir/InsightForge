"""Turns rule matches into persisted, de-duplicated alerts and notifications.

Lifecycle of an alert (one per fingerprint = rule + service while open):

    firing --ack--> acknowledged --resolve / auto-resolve--> resolved
    firing --------------resolve / auto-resolve------------> resolved

* New matches for an open alert bump ``count``/``last_seen`` (persisted in debounced batches).
* A new alert is opened only once the rule's cooldown has elapsed since the previous one.
* Alerts with no matches for ``auto_resolve_seconds`` are resolved by the sweeper.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from app.core import metrics
from app.schemas import Alert, AlertRule, utcnow
from app.services.alert_engine import AlertEngine, RuleMatch

logger = logging.getLogger(__name__)


class AlertStoreLike(Protocol):
    async def save(self, alert: Alert, *, refresh: bool = False) -> None: ...
    async def get(self, alert_id: str) -> Alert | None: ...
    async def list_open(self) -> list[Alert]: ...


class NotifierLike(Protocol):
    def dispatch(self, alert: Alert, event: Any, channels: list[Any]) -> None: ...


class AlertConflictError(Exception):
    pass


class AlertManager:
    def __init__(
        self,
        engine: AlertEngine,
        store: AlertStoreLike,
        notifier: NotifierLike,
        *,
        sweep_interval: float = 15.0,
        queue_size: int = 10_000,
    ) -> None:
        self.engine = engine
        self._store = store
        self._notifier = notifier
        self._sweep_interval = sweep_interval
        self._matches: asyncio.Queue[RuleMatch] = asyncio.Queue(maxsize=queue_size)
        self._open: dict[str, Alert] = {}  # fingerprint -> alert
        self._dirty: set[str] = set()
        self._lock = asyncio.Lock()
        self._tasks: list[asyncio.Task[None]] = []

    # -- lifecycle ------------------------------------------------------------------

    async def start(self, rules: list[AlertRule]) -> None:
        self.engine.set_rules(rules)
        for alert in await self._store.list_open():
            self._open[alert.fingerprint] = alert
        self._tasks = [
            asyncio.create_task(self._consume(), name="alert-consumer"),
            asyncio.create_task(self._sweep_loop(), name="alert-sweeper"),
        ]
        logger.info("alert manager started", extra={"rules": len(rules), "open_alerts": len(self._open)})

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        await self._persist_dirty()

    # -- ingest path (synchronous, cheap) -------------------------------------------

    def process(self, doc: dict[str, Any]) -> None:
        for match in self.engine.evaluate(doc):
            try:
                self._matches.put_nowait(match)
            except asyncio.QueueFull:
                logger.error("alert queue full; dropping match", extra={"rule_id": match.rule.id})

    # -- queries -------------------------------------------------------------------

    @property
    def open_alerts(self) -> list[Alert]:
        return sorted(self._open.values(), key=lambda a: a.last_seen, reverse=True)

    async def get(self, alert_id: str) -> Alert | None:
        for alert in self._open.values():
            if alert.id == alert_id:
                return alert
        return await self._store.get(alert_id)

    # -- operator actions ------------------------------------------------------------

    async def acknowledge(self, alert_id: str, user: str) -> Alert:
        async with self._lock:
            alert = self._find_open(alert_id)
            if alert.status == "firing":
                alert.status = "acknowledged"
                alert.acknowledged_by = user
                alert.acknowledged_at = utcnow()
                await self._store.save(alert, refresh=True)
                self._dirty.discard(alert.fingerprint)
            return alert

    async def resolve(self, alert_id: str, user: str | None, reason: str = "manual") -> Alert:
        async with self._lock:
            alert = self._find_open(alert_id)
            await self._resolve(alert, reason if user is None else f"{reason}:{user}")
            return alert

    async def resolve_for_rule(self, rule_id: str, reason: str) -> int:
        async with self._lock:
            targets = [a for a in self._open.values() if a.rule_id == rule_id]
            for alert in targets:
                await self._resolve(alert, reason)
            return len(targets)

    def _find_open(self, alert_id: str) -> Alert:
        for alert in self._open.values():
            if alert.id == alert_id:
                return alert
        raise AlertConflictError("alert is not open (already resolved or unknown)")

    async def _resolve(self, alert: Alert, reason: str) -> None:
        alert.status = "resolved"
        alert.resolved_at = utcnow()
        alert.resolved_reason = reason
        self._open.pop(alert.fingerprint, None)
        self._dirty.discard(alert.fingerprint)
        await self._store.save(alert, refresh=True)
        rule = self.engine.get_rule(alert.rule_id)
        if rule:
            self._notifier.dispatch(alert, "resolved", rule.notify)

    # -- background workers ------------------------------------------------------------

    async def _consume(self) -> None:
        while True:
            match = await self._matches.get()
            try:
                async with self._lock:
                    await self._handle(match)
            except Exception:
                logger.exception("failed to handle rule match", extra={"rule_id": match.rule.id})

    async def _handle(self, match: RuleMatch) -> None:
        now = utcnow()
        existing = self._open.get(match.fingerprint)
        if existing:
            existing.count += 1
            existing.last_seen = now
            existing.sample_message = match.sample_message
            self._dirty.add(match.fingerprint)
            return
        if not match.may_open:
            return  # in cooldown after a recent alert for this fingerprint

        alert = Alert(
            fingerprint=match.fingerprint,
            rule_id=match.rule.id,
            rule_name=match.rule.name,
            severity=match.rule.severity,
            service=match.service,
            summary=match.summary,
            sample_message=match.sample_message,
            count=match.window_count,
            first_seen=now,
            last_seen=now,
        )
        self._open[match.fingerprint] = alert
        self.engine.mark_opened(match.fingerprint)
        await self._store.save(alert, refresh=True)
        metrics.ALERTS_OPENED.labels(severity=alert.severity).inc()
        logger.info("alert opened", extra={"alert_id": alert.id, "fingerprint": alert.fingerprint})
        self._notifier.dispatch(alert, "opened", match.rule.notify)

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(self._sweep_interval)
            try:
                await self.sweep()
            except Exception:
                logger.exception("alert sweep failed")

    async def sweep(self, now: datetime | None = None) -> None:
        """Persist debounced updates and auto-resolve stale alerts."""
        now = now or datetime.now(timezone.utc)
        async with self._lock:
            for alert in list(self._open.values()):
                rule = self.engine.get_rule(alert.rule_id)
                if rule is None:
                    await self._resolve(alert, "rule_deleted")
                    continue
                if rule.auto_resolve_seconds and now - alert.last_seen >= timedelta(
                    seconds=rule.auto_resolve_seconds
                ):
                    await self._resolve(alert, "auto")
            await self._persist_dirty()

    async def _persist_dirty(self) -> None:
        for fingerprint in list(self._dirty):
            alert = self._open.get(fingerprint)
            if alert:
                await self._store.save(alert)
            self._dirty.discard(fingerprint)
