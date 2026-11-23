"""StandOnNoPortTurnCondition (Rule 17(c)): the stand-on vessel of a crossing does not turn to port for the vessel on her port side."""

import math

from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.situation_context import COLREGSType
from concrete_level.models.actor_state import ActorState
from concrete_level.models.relation import Relation
from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, SPEED, TARGET, monitored_run, rule_result, scripted_run

# The target crosses the own ship's bow from starboard: the own ship gives way, the target stands on.
CROSSING = (3600.0, -3600.0)


def outcomes(run, rule_number: str):
    return [rule_result(monitored, rule_number, TARGET) for monitored in run]


def test_the_stand_on_vessel_turning_to_port_fails():
    run = monitored_run(CROSSING, 120, turn_at=30, turn_s=30)
    results = outcomes(run, "17(c)")
    assert set(results[1:30]) == {COLREGSRuleResult.UNKNOWN}
    assert results[-1] is COLREGSRuleResult.FAILED


def test_the_stand_on_vessel_turning_to_starboard_breaks_17_a_i_but_not_17_c():
    run = scripted_run(
        ActorState(0.0, 0.0, SPEED, 0.0),
        ActorState(CROSSING[0], CROSSING[1], SPEED, math.pi / 2),
        120,
        target_turn=lambda t: -math.radians(1.0) if 30 <= t < 60 else 0.0,
    )
    assert COLREGSRuleResult.FAILED not in outcomes(run, "17(c)")
    assert outcomes(run, "17(a)(i)")[-1] is COLREGSRuleResult.FAILED


def test_a_released_stand_on_vessel_still_may_not_turn_to_port():
    """The give-way vessel never acts, so the target is released after 60 s (17(a)(ii)) and keeps 17(a)(i); its later turn to port fails 17(c)."""
    run = monitored_run(CROSSING, 150, turn_at=80, turn_s=30)
    assert outcomes(run, "17(a)(i)")[-1] is COLREGSRuleResult.PASSED
    results = outcomes(run, "17(c)")
    assert set(results[1:80]) == {COLREGSRuleResult.UNKNOWN}
    assert results[-1] is COLREGSRuleResult.FAILED


def test_the_rule_is_kept_per_vessel_so_a_failure_names_the_stand_on_vessel():
    """The planner repairs the vessel of a per-vessel rule, so a 17(c) failure steers the target, not the give-way own ship."""
    run = monitored_run(CROSSING, 120, turn_at=30, turn_s=30)
    failed = run[-1].monitor_result_map_set.get_failed_rules()
    (relation,) = [relation for relation, rules in failed.items() if any(rule.rule_number == "17(c)" for rule in rules)]
    assert relation == Relation(TARGET, TARGET)
    assert outcomes(run, "17(c)")[-1] is COLREGSRuleResult.FAILED
    assert {rule_result(monitored, "17(c)", OWN_SHIP) for monitored in run[1:]} == {COLREGSRuleResult.UNKNOWN}


def test_the_stand_on_vessel_holding_on_passes_when_the_crossing_ends():
    """The own ship gives way with 90 degrees to starboard and passes astern; the target holds on, and the pass holds after the crossing."""
    run = scripted_run(
        ActorState(0.0, 0.0, SPEED, 0.0),
        ActorState(CROSSING[0], CROSSING[1], SPEED, math.pi / 2),
        300,
        own_turn=lambda t: -math.radians(1.0) if 5 <= t < 95 else 0.0,
    )
    results = outcomes(run, "17(c)")
    passed = results.index(COLREGSRuleResult.PASSED)
    assert set(results[1:passed]) == {COLREGSRuleResult.UNKNOWN}
    assert set(results[passed:]) == {COLREGSRuleResult.PASSED}
    (before,) = run[passed - 1].situation_context_set.values()
    (after,) = run[passed].situation_context_set.values()
    assert before.situation_type is COLREGSType.CROSSING_FROM_PORT and after.situation_type is COLREGSType.OTHER


def test_a_vessel_that_never_stands_on_in_a_crossing_is_not_judged():
    run = monitored_run((3600.0, -3000.0), 800, turn_at=700, turn_s=45)
    assert set(outcomes(run, "17(c)")[1:]) == {COLREGSRuleResult.UNKNOWN}
