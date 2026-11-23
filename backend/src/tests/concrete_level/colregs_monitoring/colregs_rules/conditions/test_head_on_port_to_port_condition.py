"""HeadOnPortToPortCondition (Rule 14(a)): two vessels meeting head-on pass port to port."""

import math
from functools import lru_cache
from typing import List

from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.head_on_port_to_port_condition import line_of_sight_rotation
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredSceneWithResults
from concrete_level.colregs_monitoring.situation_context import COLREGSType
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, SPEED, TARGET, rule_result, scripted_run

# Reciprocal courses on the x axis, 3 km apart: a head-on encounter from the first scene.
OWN_START = ActorState(0.0, 0.0, SPEED, 0.0)
TARGET_START = ActorState(3000.0, 0.0, SPEED, math.pi)
TURN_RATE = math.radians(1.0)


def turning(sign: float):
    """1 degree per second for 30 s from 5 s: positive to port, negative to starboard."""
    return lambda t: sign * TURN_RATE if 5 <= t < 35 else 0.0


@lru_cache(maxsize=4)
def both_turn(sign: float, time_step: int = 1) -> List[MonitoredSceneWithResults]:
    return scripted_run(OWN_START, TARGET_START, 400 // time_step, own_turn=turning(sign), target_turn=turning(sign), time_step=time_step)


def results(run: List[MonitoredSceneWithResults]):
    return [rule_result(monitored, "14(a)") for monitored in run]


def test_the_test_geometry_is_head_on():
    (context,) = both_turn(-1.0)[0].situation_context_set.values()
    assert context.situation_type is COLREGSType.HEAD_ON


def test_both_turning_to_starboard_pass_port_to_port():
    outcomes = results(both_turn(-1.0))
    assert COLREGSRuleResult.FAILED not in outcomes
    assert outcomes[-1] is COLREGSRuleResult.PASSED


def test_both_turning_to_port_pass_starboard_to_starboard_and_fail():
    run = both_turn(1.0)
    outcomes = results(run)
    failed_at = outcomes.index(COLREGSRuleResult.FAILED)
    # judged at the closest point of approach, not when the turn begins
    assert failed_at > 100
    assert outcomes[-1] is COLREGSRuleResult.FAILED


def test_the_pass_is_judged_when_closest_approach_and_passing_fall_in_one_planner_step():
    """At a 15 s step the pair reaches its closest approach and is past and clear within one step, after which the rule is no longer active."""
    assert results(both_turn(1.0, 15))[-1] is COLREGSRuleResult.FAILED
    assert results(both_turn(-1.0, 15))[-1] is COLREGSRuleResult.PASSED


def test_the_line_of_sight_turns_counter_clockwise_for_a_port_to_port_pass():
    relation = Relation(OWN_SHIP, TARGET)
    target_to_port = ConcreteScene({OWN_SHIP: OWN_START, TARGET: ActorState(3000.0, 200.0, SPEED, math.pi)})
    target_to_starboard = ConcreteScene({OWN_SHIP: OWN_START, TARGET: ActorState(3000.0, -200.0, SPEED, math.pi)})
    assert line_of_sight_rotation(target_to_port, relation) > 0.0
    assert line_of_sight_rotation(target_to_starboard, relation) < 0.0
    # the order of the pair does not matter
    assert line_of_sight_rotation(target_to_port, Relation(TARGET, OWN_SHIP)) > 0.0
