"""GiveWayPassesAsternCondition (Rule 15): the give-way vessel of a crossing does not cross ahead of the stand-on vessel."""

import math
from functools import lru_cache
from typing import List

from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.give_way_passes_astern_condition import GiveWayPassesAsternCondition, position_in_frame_of
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredSceneWithResults
from concrete_level.colregs_monitoring.situation_context import COLREGSType
from concrete_level.models.actor_state import ActorState
from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, SPEED, rule_result, scripted_run

# The target crosses the own ship's bow from starboard: the own ship gives way, the target stands on.
OWN_START = ActorState(0.0, 0.0, SPEED, 0.0)
TARGET_START = ActorState(3600.0, -3600.0, SPEED, math.pi / 2)


@lru_cache(maxsize=4)
def own_ship_turns(degrees: float) -> List[MonitoredSceneWithResults]:
    """The own ship turns by `degrees` (positive to port) at 1 degree per second from 5 s, the target holds her course."""
    rate = math.copysign(math.radians(1.0), degrees)
    return scripted_run(OWN_START, TARGET_START, 700, own_turn=lambda t: rate if 5 <= t < 5 + abs(degrees) else 0.0)


def results(run: List[MonitoredSceneWithResults]):
    return [rule_result(monitored, "15") for monitored in run]


def test_the_test_geometry_is_a_crossing_with_the_own_ship_giving_way():
    (context,) = own_ship_turns(-45.0)[0].situation_context_set.values()
    assert context.situation_type is COLREGSType.CROSSING_FROM_PORT and context.is_give_way_actor(OWN_SHIP)


def test_turning_to_port_and_crossing_ahead_fails():
    outcomes = results(own_ship_turns(30.0))
    assert COLREGSRuleResult.FAILED in outcomes
    assert outcomes[-1] is COLREGSRuleResult.FAILED


def test_turning_to_starboard_and_passing_astern_passes():
    outcomes = results(own_ship_turns(-45.0))
    assert COLREGSRuleResult.FAILED not in outcomes
    assert outcomes[-1] is COLREGSRuleResult.PASSED


def test_the_crossing_point_is_interpolated_over_the_step():
    crossing = GiveWayPassesAsternCondition.heading_line_crossing
    assert crossing((100.0, 50.0), (120.0, -50.0)) == 110.0
    assert crossing((-100.0, 50.0), (-80.0, -50.0)) == -90.0
    # reaching the line is the crossing; leaving it is not counted again
    assert crossing((100.0, 50.0), (110.0, 0.0)) == 110.0
    assert crossing((110.0, 0.0), (120.0, -50.0)) is None
    assert crossing((100.0, 50.0), (110.0, 20.0)) is None


def test_the_frame_is_ahead_and_to_port_of_the_reference_heading():
    north = ActorState(0.0, 0.0, 0.0, math.pi / 2)  # lying stopped still has a frame
    forward, port = position_in_frame_of(north, ActorState(-10.0, 30.0, SPEED, 0.0))
    assert math.isclose(forward, 30.0) and math.isclose(port, 10.0)


def test_the_rule_judges_the_give_way_vessel():
    (rule,) = [rule for results in own_ship_turns(-45.0)[1].monitor_result_map_set.values() for rule in results if rule.rule_number == "15"]
    assert rule.subject_actor_id == OWN_SHIP.id
