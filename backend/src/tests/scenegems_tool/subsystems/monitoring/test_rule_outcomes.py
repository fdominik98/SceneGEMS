"""RuleOutcomes: first outcome times, the verdict, and when every rule counts as decided."""

from types import SimpleNamespace

from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.situation_context import COLREGSType
from scenegems_tool.subsystems.monitoring.rule_outcomes import RuleOutcomes

PASSED, FAILED, UNKNOWN = COLREGSRuleResult.PASSED, COLREGSRuleResult.FAILED, COLREGSRuleResult.UNKNOWN


def _context(name, give_way=(), stand_on=()):
    """A situation context of the type, whose vessels are the ones named by role."""
    actors = [SimpleNamespace(name=vessel) for vessel in (*give_way, *stand_on)]
    return SimpleNamespace(
        situation_type=COLREGSType[name],
        actors=actors,
        is_give_way_actor=lambda actor: actor.name in give_way,
        is_stand_on_actor=lambda actor: actor.name in stand_on,
    )


def _scene(timestamp, results, contexts=None):
    """A monitored scene; contexts maps a relation to its situation type name or a whole context."""
    situation_contexts = {relation: _context(context) if isinstance(context, str) else context for relation, context in (contexts or {}).items()}
    return SimpleNamespace(timestamp=timestamp, monitor_result_map_set=results, situation_context_set=situation_contexts)


def _outcomes(*scenes):
    outcomes = RuleOutcomes()
    for scene in scenes:
        outcomes.add(scene)
    return outcomes


def test_the_first_time_of_each_outcome_is_kept():
    outcomes = _outcomes(
        _scene(0, {}),
        _scene(1, {"a - b": {"r8": UNKNOWN, "r16": PASSED}, "a - a": {}}),
        _scene(2, {"a - b": {"r8": FAILED, "r16": PASSED}}),
        _scene(3, {"a - b": {"r8": FAILED, "r16": FAILED}}),
    )
    assert outcomes.monitored_scenes == 4
    assert outcomes.summary() == {
        "rules": {"a - b": {"r16": {"passed": 1, "failed": 3}, "r8": {"failed": 2}}, "a - a": {}},
        "failed_rules": [{"relation": "a - b", "rule": "r8", "first_failed_at": 2}, {"relation": "a - b", "rule": "r16", "first_failed_at": 3}],
        "encounters": {},
        "encounter_roles": {},
        "passed": False,
    }


def test_a_run_without_failures_passed():
    assert _outcomes(_scene(0, {}), _scene(1, {"a - b": {"r8": PASSED}})).summary()["passed"]


def test_failures_are_sorted_by_time_then_relation_and_rule():
    outcomes = _outcomes(_scene(5, {"b - c": {"r1": FAILED}, "a - b": {"r2": FAILED, "r1": FAILED}}))
    assert [(item["relation"], item["rule"]) for item in outcomes.failed_rules()] == [("a - b", "r1"), ("a - b", "r2"), ("b - c", "r1")]


def test_only_a_failure_is_final():
    assert not RuleOutcomes().every_rule_decided()
    assert not _outcomes(_scene(0, {})).every_rule_decided()  # no rule at all yet
    assert not _outcomes(_scene(1, {"a - b": {"r8": PASSED}})).every_rule_decided()  # a pass can still turn into a failure
    assert not _outcomes(_scene(1, {"a - b": {"r8": FAILED, "r16": UNKNOWN}})).every_rule_decided()
    assert _outcomes(_scene(1, {"a - b": {"r8": FAILED}}), _scene(2, {"a - b": {"r8": FAILED, "r16": FAILED}, "a - a": {}})).every_rule_decided()


def test_a_failure_stays_decided_when_the_rule_restarts():
    # A rule that turns active again restarts as unknown; its earlier failure is in the summary for good.
    outcomes = _outcomes(_scene(1, {"a - b": {"r8": FAILED}}), _scene(2, {"a - b": {"r8": UNKNOWN}}))
    assert outcomes.every_rule_decided() and not outcomes.summary()["passed"]


def test_encounter_types_are_listed_per_relation_in_order_of_first_appearance():
    outcomes = _outcomes(
        _scene(0, {}, {"a - b": "HEAD_ON", "a - c": "OTHER"}),
        _scene(1, {"a - b": {"r8": PASSED}}, {"a - b": "HEAD_ON", "a - c": "CROSSING_FROM_PORT"}),
        _scene(2, {}, {"a - b": "OTHER", "a - c": "OTHER"}),
        _scene(3, {}, {"a - b": "HEAD_ON"}),
    )
    assert outcomes.summary()["encounters"] == {"a - b": ["HEAD_ON", "OTHER"], "a - c": ["OTHER", "CROSSING_FROM_PORT"]}


def test_a_scene_judged_alone_has_its_type_per_pair():
    assert _outcomes(_scene(0, {}, {"OS_0 - TS_1": "OVERTAKING_TO_PORT"})).summary()["encounters"] == {"OS_0 - TS_1": ["OVERTAKING_TO_PORT"]}


def test_the_roles_say_who_gives_way_where_the_relation_key_cannot():
    # The key orders the vessels by id, the context by role: here the second vessel of the key gives way.
    summary = _outcomes(_scene(0, {}, {"OS_0 - TS_1": _context("CROSSING_FROM_PORT", give_way=["TS_1"], stand_on=["OS_0"])})).summary()
    assert summary["encounter_roles"] == {"OS_0 - TS_1": {"CROSSING_FROM_PORT": {"give_way": ["TS_1"], "stand_on": ["OS_0"]}}}


def test_both_vessels_give_way_in_a_head_on():
    summary = _outcomes(_scene(0, {}, {"OS_0 - TS_1": _context("HEAD_ON", give_way=["OS_0", "TS_1"])})).summary()
    assert summary["encounter_roles"] == {"OS_0 - TS_1": {"HEAD_ON": {"give_way": ["OS_0", "TS_1"], "stand_on": []}}}


def test_a_type_keeps_the_roles_of_its_first_appearance_and_other_has_none():
    outcomes = _outcomes(
        _scene(0, {}, {"a - b": "OTHER", "a - c": "OTHER"}),
        _scene(1, {}, {"a - b": _context("CROSSING_FROM_PORT", give_way=["a"], stand_on=["b"]), "a - c": "OTHER"}),
        _scene(2, {}, {"a - b": "OTHER", "a - c": "OTHER"}),
        _scene(3, {}, {"a - b": _context("CROSSING_FROM_PORT", give_way=["b"], stand_on=["a"]), "a - c": "OTHER"}),
    )
    assert outcomes.summary()["encounter_roles"] == {"a - b": {"CROSSING_FROM_PORT": {"give_way": ["a"], "stand_on": ["b"]}}}
