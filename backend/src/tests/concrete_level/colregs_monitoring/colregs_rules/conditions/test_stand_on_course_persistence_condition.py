"""StandOnCoursePersistenceCondition (Rule 17): it binds the stand-on vessel of a live encounter, and nothing else.

Rule 17(a)(i) passes when the obligation ends with course and speed kept: the encounter is
over, or the vessel is released (17(a)(ii), 17(b)); 17(b) to 17(d) themselves are not judged.
"""

import math
from functools import lru_cache
from typing import List

from concrete_level.colregs_monitoring.colregs_monitor_runtime import ColregsMonitorRuntime, MonitoringTask
from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredSceneWithResults
from concrete_level.colregs_monitoring.situation_context import COLREGSType
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, SPEED, TARGET, constants, monitored_run

# The target crosses the own ship's bow from starboard: the own ship gives way, the target stands on.
CROSSING = (3600.0, -3600.0)
# The target crosses 600 m ahead of the own ship: never a collision course, so nobody stands on.
CLEAR_AHEAD = (3600.0, -3000.0)


def rule_17(result) -> COLREGSRuleResult:
    results = result.monitor_result_map_set.get_result(Relation(TARGET, TARGET))
    (value,) = [value for rule, value in results.items() if rule.rule_number == "17(a)(i)"]
    return value


def test_the_stand_on_vessel_fails_when_it_turns_in_a_live_encounter():
    run = monitored_run(CROSSING, 120, turn_at=30, turn_s=30)
    assert any(context.is_stand_on_actor(TARGET) for context in run[10].situation_context_set.values())
    assert rule_17(run[20]) == COLREGSRuleResult.UNKNOWN
    assert rule_17(run[40]) == COLREGSRuleResult.FAILED


def test_a_vessel_that_never_stands_on_may_turn():
    """Regression: the per-vessel rule judged every turn, so this target failed Rule 17 when it turned 450 s later."""
    run = monitored_run(CLEAR_AHEAD, 800, turn_at=700, turn_s=45)
    assert all(not context.is_stand_on_actor(TARGET) for result in run for context in result.situation_context_set.values())
    assert {rule_17(result) for result in run[1:]} == {COLREGSRuleResult.UNKNOWN}


@lru_cache(maxsize=1)
def give_way_turns_away(steps: int = 300) -> List[MonitoredSceneWithResults]:
    """CROSSING, but the own ship turns 90 degrees to starboard at 1 degree per second from 5 s and passes behind the target."""
    own = ActorState(0.0, 0.0, SPEED, 0.0)
    target = ActorState(CROSSING[0], CROSSING[1], SPEED, math.pi / 2)
    runtime = ColregsMonitorRuntime(constants())
    results: List[MonitoredSceneWithResults] = []
    for t in range(steps):
        runtime.add_task(MonitoringTask(scene=ConcreteScene({OWN_SHIP: own, TARGET: target}), scene_timestamp=t, time_step=1))
        results.extend(runtime.monitor_current_tasks())
        heading = own.heading - (math.radians(1.0) if 5 <= t < 95 else 0.0)
        own = ActorState(own.x + SPEED * math.cos(heading), own.y + SPEED * math.sin(heading), SPEED, heading)
        target = ActorState(target.x, target.y + SPEED, SPEED, target.heading)
    return results


def first_index(run: List[MonitoredSceneWithResults], result: COLREGSRuleResult) -> int:
    return next(index for index, monitored in enumerate(run) if rule_17(monitored) == result)


def test_the_stand_on_vessel_holding_its_course_passes_once_released():
    """The give-way vessel never acts, so after its 60 s window the stand-on vessel is released (17(a)(ii)): 17(a)(i) was kept."""
    run = monitored_run(CROSSING, 120)
    released = first_index(run, COLREGSRuleResult.PASSED)
    assert released == constants().IMMEDIATE_HEADING_CHANGE_TIME + 1
    assert {rule_17(result) for result in run[1:released]} == {COLREGSRuleResult.UNKNOWN}
    # the pass holds while the vessel stays released
    assert {rule_17(result) for result in run[released:]} == {COLREGSRuleResult.PASSED}
    assert all(not rule.rule_number == "17(a)(i)" for _, rule in run[-1].first_failed_at)


def test_the_stand_on_vessel_holding_its_course_passes_when_the_encounter_ends():
    run = give_way_turns_away()
    passed = first_index(run, COLREGSRuleResult.PASSED)
    assert {rule_17(result) for result in run[:passed]} == {COLREGSRuleResult.UNKNOWN}
    (context,) = run[passed].situation_context_set.values()
    (before,) = run[passed - 1].situation_context_set.values()
    assert before.situation_type is COLREGSType.CROSSING_FROM_PORT and context.situation_type is COLREGSType.OTHER
    assert {rule_17(result) for result in run[passed:]} == {COLREGSRuleResult.PASSED}


def test_a_failure_of_the_stand_on_vessel_is_not_turned_into_a_pass():
    run = monitored_run(CROSSING, 120, turn_at=30, turn_s=30)
    assert {rule_17(result) for result in run[31:]} == {COLREGSRuleResult.FAILED}
