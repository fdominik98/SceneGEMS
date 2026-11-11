"""NoNewSituationCondition (Rule 8(c)): a vessel that altered course in a running encounter must not get into a new situation.

The rule is kept per vessel. It fails when a new COLREGS situation begins for a vessel that
has made a course change in an encounter still running, passes when every such encounter has
ended without that, and judges nothing while the vessel has not altered course.
"""

import math
from functools import lru_cache
from types import SimpleNamespace
from typing import List, Optional, Tuple

from concrete_level.colregs_monitoring.colregs_monitor_runtime import ColregsMonitorRuntime, MonitoringTask
from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.colregs_rules import NoNewSituationRule
from concrete_level.colregs_monitoring.colregs_rules.conditions.no_new_situation_condition import NoNewSituationCondition
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredSceneWithResults
from concrete_level.colregs_monitoring.situation_context import COLREGSType
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from scenegems_tool.vessel_stack.calibration.reference_scenarios import make_vessel
from tests.concrete_level.colregs_monitoring.monitor_runs import OWN_SHIP, SPEED, TARGET, constants

THIRD = make_vessel(2, False)
OWN, OWN_TARGET, OWN_THIRD, TARGET_THIRD = Relation(OWN_SHIP, OWN_SHIP), Relation(OWN_SHIP, TARGET), Relation(OWN_SHIP, THIRD), Relation(TARGET, THIRD)
UNKNOWN, FAILED, PASSED = COLREGSRuleResult.UNKNOWN, COLREGSRuleResult.FAILED, COLREGSRuleResult.PASSED
CROSSING, HEAD_ON, OVERTAKING, OTHER = COLREGSType.CROSSING_FROM_PORT, COLREGSType.HEAD_ON, COLREGSType.OVERTAKING_TO_PORT, COLREGSType.OTHER

CONDITION = NoNewSituationCondition(OWN, OWN_SHIP, constants())
RULE = NoNewSituationRule(OWN_SHIP, constants())


def scene(own_target=CROSSING, own_third=OTHER, turned=False, passed=False, turning=False):
    """A hand-built monitored scene: the own ship's pairs with the target and the third vessel.

    ``turned`` and ``passed`` are the state of the pair with the target, ``turning`` is the
    own ship's manoeuvre at the scene.
    """
    return SimpleNamespace(
        situation_context_set={
            OWN_TARGET: SimpleNamespace(situation_type=own_target),
            OWN_THIRD: SimpleNamespace(situation_type=own_third),
            TARGET_THIRD: SimpleNamespace(situation_type=HEAD_ON),
        },
        colregs_state_set={
            OWN_TARGET: SimpleNamespace(actors_passed_each_other=passed, actors_have_been_in_right_maneuver={OWN_SHIP: turned}, actors_have_been_in_left_maneuver={OWN_SHIP: False}),
            OWN_THIRD: SimpleNamespace(actors_passed_each_other=False, actors_have_been_in_right_maneuver={OWN_SHIP: False}, actors_have_been_in_left_maneuver={OWN_SHIP: False}),
        },
        maneuver_state_set={OWN: SimpleNamespace(is_course_change=turning)},
    )


class TestOneStep:
    def test_a_new_situation_after_a_turn_in_a_running_encounter_fails(self):
        assert CONDITION.condition(scene(turned=True), scene(turned=True, own_third=HEAD_ON)) is FAILED

    def test_the_turn_made_in_the_same_step_counts(self):
        assert CONDITION.condition(scene(), scene(turned=True, turning=True, own_third=HEAD_ON)) is FAILED

    def test_a_new_situation_without_a_turn_judges_nothing(self):
        assert CONDITION.condition(scene(), scene(own_third=HEAD_ON)) is UNKNOWN

    def test_a_turn_outside_a_running_encounter_judges_nothing(self):
        assert CONDITION.condition(scene(own_target=OTHER), scene(own_target=OTHER, turning=True, own_third=HEAD_ON)) is UNKNOWN
        assert CONDITION.condition(scene(turned=True, passed=True), scene(turned=True, passed=True, own_third=HEAD_ON)) is UNKNOWN

    def test_a_relabelled_encounter_is_not_a_new_situation(self):
        assert CONDITION.condition(scene(turned=True), scene(own_target=OVERTAKING, turned=True)) is UNKNOWN

    def test_a_situation_between_two_other_vessels_does_not_count(self):
        """The target and the third vessel are head-on in every scene here; that pair is not the own ship's."""
        assert CONDITION.new_situation_relations(scene(), scene()) == []
        assert CONDITION.new_situation_relations(scene(), scene(own_third=HEAD_ON)) == [OWN_THIRD]

    def test_while_the_encounter_runs_and_nothing_new_begins_the_rule_is_undecided(self):
        assert CONDITION.condition(scene(turned=True), scene(turned=True)) is UNKNOWN

    def test_the_rule_passes_when_the_encounter_ends_without_a_new_situation(self):
        assert CONDITION.condition(scene(turned=True), scene(own_target=OTHER)) is PASSED
        assert CONDITION.condition(scene(turned=True), scene(turned=True, passed=True)) is PASSED

    def test_a_new_situation_in_the_step_the_encounter_ends_still_fails(self):
        assert CONDITION.condition(scene(turned=True), scene(own_target=OTHER, own_third=HEAD_ON)) is FAILED

    def test_the_rule_suggests_no_maneuver(self):
        assert CONDITION.maneuver_suggestions(scene(turned=True), 1) == {}


class TestResultOverSteps:
    def test_a_pass_holds_while_the_vessel_resolves_nothing(self):
        assert CONDITION.next_result(PASSED, scene(own_target=OTHER), scene(own_target=OTHER)) is PASSED
        assert CONDITION.next_result(PASSED, scene(own_target=OTHER), scene(own_target=OTHER, own_third=HEAD_ON)) is PASSED

    def test_a_pass_falls_back_to_unknown_when_the_vessel_turns_in_a_running_encounter_again(self):
        assert CONDITION.next_result(PASSED, scene(turned=True), scene(turned=True)) is UNKNOWN

    def test_a_failure_sticks(self):
        assert CONDITION.next_result(FAILED, scene(own_target=OTHER), scene(own_target=OTHER)) is FAILED


Turn = Optional[Tuple[int, int, float]]  # from this second, for this many seconds, at this many degrees per second (negative: to starboard)


@lru_cache(maxsize=4)
def three_vessel_run(steps: int, own_turn: Turn, third_start: Tuple[float, float, float], third_turn: Turn = None) -> List[MonitoredSceneWithResults]:
    """The own ship heads east from the origin and gives way to the target crossing from its starboard side.

    The third vessel starts at ``third_start`` (x, y, heading). All at SPEED, one result per second.
    """
    states = {OWN_SHIP: ActorState(0.0, 0.0, SPEED, 0.0), TARGET: ActorState(3600.0, -3600.0, SPEED, math.pi / 2), THIRD: ActorState(third_start[0], third_start[1], SPEED, third_start[2])}
    turns = {OWN_SHIP: own_turn, TARGET: None, THIRD: third_turn}
    runtime = ColregsMonitorRuntime(constants())
    results: List[MonitoredSceneWithResults] = []
    for t in range(steps):
        runtime.add_task(MonitoringTask(scene=ConcreteScene(dict(states)), scene_timestamp=t, time_step=1))
        results.extend(runtime.monitor_current_tasks())
        for actor, state in states.items():
            turn = turns[actor]
            heading = state.heading + (math.radians(turn[2]) if turn is not None and turn[0] <= t < turn[0] + turn[1] else 0.0)
            states[actor] = ActorState(state.x + SPEED * math.cos(heading), state.y + SPEED * math.sin(heading), SPEED, heading)
    return results


# The own ship turns 90 degrees to starboard from 5 s and then heads south.
STARBOARD_TURN = (5, 90, -1.0)
# Heading north on the line the own ship comes down after its turn: head-on with it from then on.
ON_THE_NEW_COURSE = (458.0, -6000.0, math.pi / 2)
# Heading north far to the north-west: never on a collision course with anybody.
OUT_OF_THE_WAY = (-3000.0, 6000.0, math.pi / 2)
# Heading west 1500 m north of the own ship's track; a turn to port from 20 s brings it across that track.
PASSING_CLEAR = (8000.0, 1500.0, math.pi)
PORT_TURN = (20, 30, 1.0)


def rule_8c(result: MonitoredSceneWithResults, actor: ConcreteActor) -> COLREGSRuleResult:
    results = result.monitor_result_map_set.get_result(Relation(actor, actor))
    (value,) = [value for rule, value in results.items() if rule.rule_number == "8(c)"]
    return value


def situation(result: MonitoredSceneWithResults, relation: Relation) -> COLREGSType:
    return result.situation_context_set[relation].situation_type


def first_index(run: List[MonitoredSceneWithResults], relation: Relation) -> int:
    """The first scene at which the pair is in a situation."""
    return next(index for index, result in enumerate(run) if situation(result, relation) is not OTHER)


def test_a_give_way_vessel_that_turns_into_a_third_vessel_fails():
    run = three_vessel_run(130, STARBOARD_TURN, ON_THE_NEW_COURSE)
    assert situation(run[0], OWN_TARGET) is CROSSING and situation(run[0], OWN_THIRD) is OTHER
    began = first_index(run, OWN_THIRD)
    assert 5 < began < 95, "the new situation begins during the turn"
    assert situation(run[began], OWN_TARGET) is CROSSING, "the encounter being resolved is still running"
    assert {rule_8c(result, OWN_SHIP) for result in run[:began]} == {UNKNOWN}
    # the failure sticks
    assert {rule_8c(result, OWN_SHIP) for result in run[began:]} == {FAILED}
    assert run[-1].first_failed_at[(OWN, RULE)] == began


def test_only_the_vessel_that_turned_fails():
    run = three_vessel_run(130, STARBOARD_TURN, ON_THE_NEW_COURSE)
    assert {rule_8c(result, actor) for result in run for actor in (TARGET, THIRD)} == {UNKNOWN}


def test_a_vessel_that_holds_its_course_is_not_failed_by_a_situation_another_vessel_creates():
    run = three_vessel_run(60, None, PASSING_CLEAR, PORT_TURN)
    began = first_index(run, OWN_THIRD)
    assert situation(run[began], OWN_TARGET) is CROSSING
    assert {rule_8c(result, OWN_SHIP) for result in run} == {UNKNOWN}


def test_any_vessel_turning_in_a_running_encounter_is_judged_whatever_its_role():
    """The third vessel's turn first meets the target, then the own ship: the second situation fails it."""
    run = three_vessel_run(60, None, PASSING_CLEAR, PORT_TURN)
    first, second = first_index(run, TARGET_THIRD), first_index(run, OWN_THIRD)
    assert PORT_TURN[0] < first < second < PORT_TURN[0] + PORT_TURN[1]
    assert {rule_8c(result, THIRD) for result in run[:second]} == {UNKNOWN}
    assert {rule_8c(result, THIRD) for result in run[second:]} == {FAILED}


def test_the_rule_passes_when_the_encounter_ends_without_a_new_situation():
    run = three_vessel_run(260, STARBOARD_TURN, OUT_OF_THE_WAY)
    ended = next(index for index, result in enumerate(run) if situation(result, OWN_TARGET) is OTHER)
    assert {situation(result, OWN_THIRD) for result in run} == {OTHER}
    assert {rule_8c(result, OWN_SHIP) for result in run[:ended]} == {UNKNOWN}
    # the pass holds once the vessel resolves nothing any more
    assert {rule_8c(result, OWN_SHIP) for result in run[ended:]} == {PASSED}
    assert all(rule.rule_number != "8(c)" for _, rule in run[-1].first_failed_at)
