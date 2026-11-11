"""Rule 8 course change persistence: the new heading of a course change has to be held for
HEADING_PERSISTENCE_TIME; the course a vessel starts on was never changed to, so it may end at any time."""

import math
from typing import List, Sequence, Tuple

from concrete_level.colregs_monitoring.colregs_monitor_runtime import ColregsMonitorRuntime, MonitoringTask
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.subsystems.monitoring.rule_outcomes import RuleOutcomes
from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, SPEED, TARGET, constants

PERSISTENCE = "Rule 8(b): Course Change Persistence"
EARLY_ACTION = "Rule 16: Give-Way Vessel Takes Early and Substantial Action"
TURN_S = 16  # at 2 degrees per second: 32 degrees, readily apparent
RATE = math.radians(2.0)


def failed_rules(own_turns: Sequence[Tuple[int, float]], target_start: ActorState, target_turns: Sequence[Tuple[int, float]] = (), steps: int = 300) -> List[Tuple[str, int]]:
    """The rules that failed and when, for the own ship from the origin heading east; a turn is (start second, signed rate)."""
    own = ActorState(0.0, 0.0, SPEED, 0.0)
    target = target_start
    runtime = ColregsMonitorRuntime(constants())
    outcomes = RuleOutcomes()
    for t in range(steps):
        runtime.add_task(MonitoringTask(scene=ConcreteScene({OWN_SHIP: own, TARGET: target}), scene_timestamp=t, time_step=1))
        for result in runtime.monitor_current_tasks():
            outcomes.add(result)
        own_heading = own.heading + sum(rate for start, rate in own_turns if start <= t < start + TURN_S)
        target_heading = target.heading + sum(rate for start, rate in target_turns if start <= t < start + TURN_S)
        own = ActorState(own.x + SPEED * math.cos(own_heading), own.y + SPEED * math.sin(own_heading), SPEED, own_heading)
        target = ActorState(target.x + SPEED * math.cos(target_heading), target.y + SPEED * math.sin(target_heading), SPEED, target_heading)
    return sorted({(item["rule"].split(" (")[0], item["first_failed_at"]) for item in outcomes.failed_rules()})


FAR_AWAY = ActorState(0.0, 20000.0, SPEED, 0.0)  # in no encounter with the own ship
HEAD_ON = ActorState(4000.0, 0.0, SPEED, math.pi)


def test_a_first_course_change_is_not_failed_for_ending_the_course_the_vessel_started_on():
    assert failed_rules([(20, -RATE)], FAR_AWAY) == []


def test_turning_again_before_the_new_heading_was_held_long_enough_fails():
    held = constants().HEADING_PERSISTENCE_TIME // 2
    second = 20 + TURN_S + held
    assert failed_rules([(20, -RATE), (second, RATE)], FAR_AWAY) == [(PERSISTENCE, second + 1)]


def test_turning_again_after_the_new_heading_was_held_long_enough_passes():
    second = 20 + TURN_S + constants().HEADING_PERSISTENCE_TIME + 10
    assert failed_rules([(20, -RATE), (second, RATE)], FAR_AWAY, steps=second + 120) == []


def test_give_way_vessels_may_turn_early_in_a_head_on_encounter():
    """Rule 16 wants the turn before IMMEDIATE_HEADING_CHANGE_TIME; the course the vessels started on does not hold it back."""
    turn = constants().IMMEDIATE_HEADING_CHANGE_TIME // 2
    assert failed_rules([(turn, -RATE)], HEAD_ON, [(turn, -RATE)]) == []
