"""COLREGSMonitor at the first timestamp, the first failure time it keeps per rule, and the in sight state it keeps per pair."""

import math

from concrete_level.colregs_monitoring.colregs_monitor import COLREGSMonitor
from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult, COLREGSRuleResultMap, COLREGSRuleResultMapSet
from concrete_level.colregs_monitoring.colregs_rules.colregs_rules import GiveWayEarlyActionRule, SafeDistanceRule
from concrete_level.colregs_monitoring.monitored_trajectory import record_first_failures
from concrete_level.colregs_monitoring.situation_context import COLREGSType
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from tests.concrete_level.colregs_monitoring.colregs_rules.conditions.test_stand_on_course_persistence_condition import CROSSING
from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, SPEED, TARGET, constants, monitored_run

PAIR = Relation.canonical(OWN_SHIP, TARGET)
# Head-on along the x axis. The safety radius is 120 m: 80 m is inside the default circle,
# 200 m only inside the own ship's head-on ellipse.
INSIDE_CIRCLE, INSIDE_HEAD_ON_DOMAIN = 80.0, 200.0
# Two 30 m vessels meeting are in sight from 5 nm (9260 m).
WITHIN_VISIBILITY, BEYOND_VISIBILITY = 3000.0, 12000.0


def head_on(distance: float) -> ConcreteScene:
    return ConcreteScene({OWN_SHIP: ActorState(0.0, 0.0, SPEED, 0.0), TARGET: ActorState(distance, 0.0, SPEED, math.pi)})


def abeam(distance: float, advance: float = 0.0) -> ConcreteScene:
    """Parallel courses east, ``distance`` apart: never on a collision course."""
    return ConcreteScene({OWN_SHIP: ActorState(advance, 0.0, SPEED, 0.0), TARGET: ActorState(advance, distance, SPEED, 0.0)})


def safe_distance(results: COLREGSRuleResultMapSet) -> COLREGSRuleResult:
    return results.get_result(PAIR).get_result(SafeDistanceRule(PAIR, constants()))


def test_the_initial_result_lists_every_active_rule():
    monitor = COLREGSMonitor(head_on(2000.0), constants())
    results = monitor.initial_monitored_scene_with_results.monitor_result_map_set
    assert {relation: set(result_map) for relation, result_map in results.items()} == {relation: set(rule_map) for relation, rule_map in monitor.initial_rules.items()}
    assert monitor.initial_situation_context_set[PAIR].situation_type is COLREGSType.HEAD_ON


def test_rules_on_motion_start_unknown_and_a_clear_pair_fails_nothing():
    initial = COLREGSMonitor(head_on(2000.0), constants()).initial_monitored_scene_with_results
    assert {result for result_map in initial.monitor_result_map_set.values() for result in result_map.values()} == {COLREGSRuleResult.UNKNOWN}
    assert initial.first_failed_at == {}


def test_a_pair_starting_inside_its_safety_circle_fails_safe_distance_at_0():
    monitor = COLREGSMonitor(head_on(INSIDE_CIRCLE), constants())
    initial = monitor.initial_monitored_scene_with_results
    assert monitor.initial_situation_context_set[PAIR].situation_type is COLREGSType.OTHER
    assert safe_distance(initial.monitor_result_map_set) is COLREGSRuleResult.FAILED
    assert initial.first_failed_at == {(PAIR, SafeDistanceRule(PAIR, constants())): 0}
    # the failure sticks, and keeps its first time
    after = monitor.step(initial, head_on(INSIDE_CIRCLE + 2 * SPEED), 1)
    assert safe_distance(after.monitor_result_map_set) is COLREGSRuleResult.FAILED
    assert after.first_failed_at == {(PAIR, SafeDistanceRule(PAIR, constants())): 0}


def test_a_pair_inside_the_encounter_domain_only_is_judged_on_the_default_circle():
    """The safety domain guard makes the pair OTHER, so SafeDistance judges the default circle, which it is outside of."""
    monitor = COLREGSMonitor(head_on(INSIDE_HEAD_ON_DOMAIN), constants())
    assert monitor.initial_situation_context_set[PAIR].situation_type is COLREGSType.OTHER
    assert safe_distance(monitor.initial_monitored_scene_with_results.monitor_result_map_set) is COLREGSRuleResult.UNKNOWN


def test_the_planner_monitor_leaves_the_initial_scene_unjudged():
    monitor = COLREGSMonitor(head_on(INSIDE_CIRCLE), constants(), judge_initial_scene=False)
    initial = monitor.initial_monitored_scene_with_results
    assert safe_distance(initial.monitor_result_map_set) is COLREGSRuleResult.UNKNOWN
    assert not initial.monitor_result_map_set.is_failed() and initial.first_failed_at == {}


def test_the_first_failure_time_is_kept_on_later_scenes():
    run = monitored_run(CROSSING, 120, turn_at=30, turn_s=30)
    rule_17 = next(key for key in run[-1].first_failed_at if key[1].rule_number == "17(a)(i)")
    assert rule_17[0] == Relation(TARGET, TARGET)
    assert all(rule_17 not in monitored.first_failed_at for monitored in run[:31])
    assert {monitored.first_failed_at[rule_17] for monitored in run[31:]} == {31}


def test_first_failures_are_kept_per_relation_and_never_moved():
    giving_way = GiveWayEarlyActionRule(OWN_SHIP, constants())
    first = Relation(OWN_SHIP, TARGET)

    def results(*failed_relations):
        return COLREGSRuleResultMapSet({relation: COLREGSRuleResultMap({giving_way: COLREGSRuleResult.FAILED}) for relation in failed_relations})

    recorded = record_first_failures({}, results(first), 5)
    assert recorded == {(first, giving_way): 5}
    # nothing new: the same dict comes back, nothing is copied
    assert record_first_failures(recorded, results(first), 9) is recorded
    # a later failure under another relation gets its own time, the earlier one stays
    other = Relation(OWN_SHIP, OWN_SHIP)
    later = record_first_failures(recorded, results(first, other), 9)
    assert later == {(first, giving_way): 5, (other, giving_way): 9} and recorded == {(first, giving_way): 5}


def test_a_pair_within_visibility_is_in_sight_and_one_beyond_it_is_not():
    assert COLREGSMonitor(abeam(WITHIN_VISIBILITY), constants()).initial_monitor_state_set[PAIR].actors_see_each_other
    assert not COLREGSMonitor(abeam(BEYOND_VISIBILITY), constants()).initial_monitor_state_set[PAIR].actors_see_each_other


def test_a_pair_stays_in_sight_after_both_vessels_leave_visibility_range():
    monitor = COLREGSMonitor(abeam(WITHIN_VISIBILITY), constants())
    apart = abeam(BEYOND_VISIBILITY, SPEED)
    after = monitor.step(monitor.initial_monitored_scene_with_results, apart, 1)
    assert apart.visibility_distance_kind(OWN_SHIP, TARGET) == "out"
    assert after.monitored_scene.colregs_state_set[PAIR].actors_see_each_other
    later = monitor.step(after, abeam(BEYOND_VISIBILITY, 2 * SPEED), 1)
    assert later.monitored_scene.colregs_state_set[PAIR].actors_see_each_other


def test_a_pair_that_was_in_sight_meets_again_beyond_visibility_as_an_encounter():
    monitor = COLREGSMonitor(abeam(WITHIN_VISIBILITY), constants())
    assert monitor.initial_situation_context_set[PAIR].situation_type is COLREGSType.OTHER
    after = monitor.step(monitor.initial_monitored_scene_with_results, head_on(BEYOND_VISIBILITY), 1)
    assert after.monitored_scene.situation_context_set[PAIR].situation_type is COLREGSType.HEAD_ON
    assert after.monitored_scene.colregs_state_set[PAIR].actors_see_each_other


def test_a_pair_never_in_sight_meets_beyond_visibility_without_an_encounter():
    monitor = COLREGSMonitor(abeam(BEYOND_VISIBILITY), constants())
    after = monitor.step(monitor.initial_monitored_scene_with_results, head_on(BEYOND_VISIBILITY), 1)
    assert after.monitored_scene.situation_context_set[PAIR].situation_type is COLREGSType.OTHER
    assert not after.monitored_scene.colregs_state_set[PAIR].actors_see_each_other
