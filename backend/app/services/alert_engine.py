"""In-memory, sliding-window alert rule evaluator.

The engine is pure and synchronous: it is called inline on the ingest path, so it must be cheap.
Persistence and notifications are handled by :mod:`app.services.alert_manager`.

Memory is bounded: each (rule, service) window keeps at most ``threshold`` timestamps, and the
number of tracked windows is capped with LRU eviction.
"""

from __future__ import annotations

import fnmatch
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from app.schemas import AlertRule

MAX_TRACKED_WINDOWS = 50_000


@dataclass(frozen=True, slots=True)
class RuleMatch:
    """Emitted when a rule's threshold is met by an incoming log."""

    rule: AlertRule
    fingerprint: str
    service: str | None
    window_count: int
    sample_message: str
    may_open: bool  # False while the (rule, service) pair is in cooldown

    @property
    def summary(self) -> str:
        cond = self.rule.condition
        scope = f" in {self.service}" if self.service else ""
        if cond.threshold == 1:
            return f"{self.rule.name}: matching log{scope}"
        return f"{self.rule.name}: {self.window_count} matching logs{scope} within {cond.window_seconds}s"


def fingerprint_for(rule: AlertRule, service: str | None) -> str:
    return f"{rule.id}:{service if (rule.group_by_service and service) else '*'}"


def rule_matches(rule: AlertRule, doc: dict[str, Any]) -> bool:
    cond = rule.condition
    if cond.levels and doc.get("level") not in {lvl.value for lvl in cond.levels}:
        return False
    if cond.services:
        service = doc.get("service", "")
        if not any(fnmatch.fnmatchcase(service, pattern) for pattern in cond.services):
            return False
    if cond.message_contains and cond.message_contains.lower() not in doc.get("message", "").lower():
        return False
    return True


class AlertEngine:
    def __init__(self, clock: Callable[[], float] = time.monotonic, max_windows: int = MAX_TRACKED_WINDOWS):
        self._clock = clock
        self._max_windows = max_windows
        self._rules: dict[str, AlertRule] = {}
        self._windows: OrderedDict[str, deque[float]] = OrderedDict()
        self._last_opened: dict[str, float] = {}

    # -- rule management --------------------------------------------------------

    @property
    def rules(self) -> list[AlertRule]:
        return list(self._rules.values())

    def get_rule(self, rule_id: str) -> AlertRule | None:
        return self._rules.get(rule_id)

    def set_rules(self, rules: Iterable[AlertRule]) -> None:
        self._rules = {r.id: r for r in rules}
        self._forget(lambda key: key.split(":", 1)[0] not in self._rules)

    def upsert_rule(self, rule: AlertRule) -> None:
        self._rules[rule.id] = rule
        # The condition may have changed: start the window fresh, keep cooldown history.
        self._forget(lambda key: key.startswith(f"{rule.id}:"), keep_cooldowns=True)

    def remove_rule(self, rule_id: str) -> None:
        self._rules.pop(rule_id, None)
        self._forget(lambda key: key.startswith(f"{rule_id}:"))

    def _forget(self, predicate: Callable[[str], bool], keep_cooldowns: bool = False) -> None:
        for key in [k for k in self._windows if predicate(k)]:
            del self._windows[key]
        if not keep_cooldowns:
            for key in [k for k in self._last_opened if predicate(k)]:
                del self._last_opened[key]

    # -- evaluation ---------------------------------------------------------------

    def evaluate(self, doc: dict[str, Any]) -> list[RuleMatch]:
        matches: list[RuleMatch] = []
        if not self._rules:
            return matches
        now = self._clock()
        for rule in self._rules.values():
            if not rule.enabled or not rule_matches(rule, doc):
                continue
            service = doc.get("service")
            key = fingerprint_for(rule, service)
            window = self._touch_window(key, rule.condition.threshold)
            window.append(now)
            horizon = now - rule.condition.window_seconds
            while window and window[0] < horizon:
                window.popleft()
            if len(window) < rule.condition.threshold:
                continue

            last = self._last_opened.get(key)
            may_open = last is None or (now - last) >= rule.cooldown_seconds
            matches.append(
                RuleMatch(
                    rule=rule,
                    fingerprint=key,
                    service=service if rule.group_by_service else None,
                    window_count=len(window),
                    sample_message=doc.get("message", "")[:1_000],
                    may_open=may_open,
                )
            )
        return matches

    def mark_opened(self, fingerprint: str) -> None:
        """Record that an alert was opened for ``fingerprint`` (starts its cooldown)."""
        self._last_opened[fingerprint] = self._clock()

    def _touch_window(self, key: str, threshold: int) -> deque[float]:
        window = self._windows.get(key)
        if window is None or window.maxlen != threshold:
            window = deque(window or (), maxlen=threshold)
            self._windows[key] = window
        self._windows.move_to_end(key)
        while len(self._windows) > self._max_windows:
            self._windows.popitem(last=False)
        return window
