from app.schemas import AlertRule, LogLevel, RuleCondition
from app.services.alert_engine import AlertEngine, rule_matches


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def log(level="ERROR", service="api", message="boom"):
    return {"level": level, "service": service, "message": message}


def make_rule(**overrides):
    cond = overrides.pop("condition", {})
    return AlertRule(name="r", condition=RuleCondition(**cond), **overrides)


def test_rule_matching_levels_services_and_message():
    rule = make_rule(condition={"levels": ["ERROR"], "services": ["pay*"], "message_contains": "TimeOut"})
    assert rule_matches(rule, log(service="payments", message="gateway timeout after 30s"))
    assert not rule_matches(rule, log(level="INFO", service="payments", message="timeout"))
    assert not rule_matches(rule, log(service="auth", message="timeout"))
    assert not rule_matches(rule, log(service="payments", message="ok"))


def test_empty_condition_matches_everything():
    assert rule_matches(make_rule(), log(level="DEBUG", service="x", message="y"))


def test_level_aliases_are_normalized():
    rule = make_rule(condition={"levels": ["warning", "fatal"]})
    assert rule.condition.levels == [LogLevel.WARN, LogLevel.CRITICAL]


def test_threshold_within_window():
    clock = FakeClock()
    engine = AlertEngine(clock=clock)
    engine.set_rules([make_rule(condition={"threshold": 3, "window_seconds": 10})])

    assert engine.evaluate(log()) == []
    clock.now += 1
    assert engine.evaluate(log()) == []
    clock.now += 1
    matches = engine.evaluate(log())
    assert len(matches) == 1 and matches[0].window_count == 3 and matches[0].may_open


def test_window_expires_old_events():
    clock = FakeClock()
    engine = AlertEngine(clock=clock)
    engine.set_rules([make_rule(condition={"threshold": 2, "window_seconds": 5})])
    engine.evaluate(log())
    clock.now += 6
    assert engine.evaluate(log()) == []


def test_group_by_service_tracks_windows_separately():
    engine = AlertEngine(clock=FakeClock())
    engine.set_rules([make_rule(condition={"threshold": 2})])
    engine.evaluate(log(service="a"))
    assert engine.evaluate(log(service="b")) == []
    [match] = engine.evaluate(log(service="a"))
    assert match.service == "a" and match.fingerprint.endswith(":a")


def test_global_rule_aggregates_services():
    engine = AlertEngine(clock=FakeClock())
    engine.set_rules([make_rule(group_by_service=False, condition={"threshold": 2})])
    engine.evaluate(log(service="a"))
    [match] = engine.evaluate(log(service="b"))
    assert match.service is None and match.fingerprint.endswith(":*")


def test_cooldown_blocks_reopening():
    clock = FakeClock()
    engine = AlertEngine(clock=clock)
    rule = make_rule(cooldown_seconds=60)
    engine.set_rules([rule])

    [first] = engine.evaluate(log())
    assert first.may_open
    engine.mark_opened(first.fingerprint)
    clock.now += 30
    [second] = engine.evaluate(log())
    assert not second.may_open
    clock.now += 31
    [third] = engine.evaluate(log())
    assert third.may_open


def test_disabled_rules_are_ignored_and_removal_clears_state():
    engine = AlertEngine(clock=FakeClock())
    rule = make_rule(enabled=False)
    engine.set_rules([rule])
    assert engine.evaluate(log()) == []
    engine.remove_rule(rule.id)
    assert engine.rules == []


def test_window_memory_is_bounded():
    engine = AlertEngine(clock=FakeClock(), max_windows=10)
    engine.set_rules([make_rule(condition={"threshold": 5})])
    for i in range(100):
        engine.evaluate(log(service=f"svc-{i}"))
    assert len(engine._windows) == 10
    assert all(len(w) <= 5 for w in engine._windows.values())
