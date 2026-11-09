"""SafeDistanceCondition, GiveWayEarlyActionCondition and ReadilyApparentCourseChangeCondition on hand-built monitor states."""

from types import SimpleNamespace

import pytest

from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.give_way_early_action_condition import GiveWayEarlyActionCondition
from concrete_level.colregs_monitoring.colregs_rules.conditions.readily_apparent_course_change_condition import ReadilyApparentCourseChangeCondition
from concrete_level.colregs_monitoring.colregs_rules.conditions.safe_distance_condition import SafeDistanceCondition
from concrete_level.colregs_monitoring.maneuver import ManeuverType
from concrete_level.models.relation import Relation
from scenegems_tool.vessel_stack.calibration.reference_scenarios import make_vessel
from tests.concrete_level.colregs_monitoring.monitor_runs import constants
from utils.math_utils import Direction

A, B = make_vessel(0, True), make_vessel(1, False)
AB = Relation(A, B)
UNKNOWN, FAILED, PASSED = COLREGSRuleResult.UNKNOWN, COLREGSRuleResult.FAILED, COLREGSRuleResult.PASSED
LEFT, RIGHT, PERSIST = ManeuverType.COURSE_CHANGE_TO_THE_LEFT, ManeuverType.COURSE_CHANGE_TO_THE_RIGHT, ManeuverType.PERSISTING_COURSE


def colregs_state(**changes):
    state = {
        "actors_violate_safety_domain": False,
        "actors_clearance": {A: 100.0, B: 100.0},
        "min_step_clearance": 100.0,
        "actors_passed_each_other": False,
        "time_spent_in_current_context": 0,
        "actors_left_of_start_state": {A: False},
        "actors_right_of_start_state": {A: False},
        "actors_have_been_in_left_maneuver": {A: False},
        "actors_have_been_in_right_maneuver": {A: False},
        "actors_avoidance_direction": {A: Direction.LEFT},
    }
    state.update(changes)
    return SimpleNamespace(**state)


def scene(state=None, maneuver=None):
    return SimpleNamespace(colregs_state_set={AB: state or colregs_state()}, maneuver_state_set={AB: maneuver})


def maneuver(**changes):
    fields = {"is_course_change": True, "readily_apparent_time_passed": False, "type": LEFT, "heading_change": SimpleNamespace(is_readily_apparent_since_readily_apparent_time=False)}
    fields.update(changes)
    return SimpleNamespace(**fields)


class TestSafeDistance:
    condition = SafeDistanceCondition(AB, constants())

    def test_it_judges_the_first_actor_of_the_relation(self):
        assert self.condition.actor is A

    def test_clear_water_is_undecided(self):
        assert self.condition.condition(scene(), scene()) is UNKNOWN

    def test_entering_the_domain_fails(self):
        assert self.condition.condition(scene(), scene(colregs_state(actors_violate_safety_domain=True))) is FAILED

    def test_tunnelling_through_the_domain_inside_one_step_fails(self):
        assert self.condition.condition(scene(), scene(colregs_state(min_step_clearance=-1.0))) is FAILED

    @pytest.mark.parametrize("next_clearance, expected", [(-20.0, UNKNOWN), (-30.0, FAILED), (-40.0, FAILED)])
    def test_when_already_inside_the_clearance_has_to_improve(self, next_clearance, expected):
        inside = colregs_state(actors_violate_safety_domain=True, actors_clearance={A: -30.0, B: -30.0})
        later = colregs_state(actors_violate_safety_domain=True, actors_clearance={A: next_clearance, B: next_clearance}, min_step_clearance=-5.0)
        assert self.condition.condition(scene(inside), scene(later)) is expected

    def test_it_suggests_turning_either_way_for_both_actors_only_when_inside(self):
        assert self.condition.maneuver_suggestions(scene(), 1) == {}
        suggestions = self.condition.maneuver_suggestions(scene(colregs_state(actors_violate_safety_domain=True)), 1)
        assert dict(suggestions) == {A: {LEFT, RIGHT}, B: {LEFT, RIGHT}}
        assert "SafeDistanceCondition" in suggestions.get_info(A)


class TestGiveWayEarlyAction:
    condition = GiveWayEarlyActionCondition(AB, A, constants())
    immediate = constants().IMMEDIATE_HEADING_CHANGE_TIME

    def _in_left_maneuver(self, **changes):
        return colregs_state(actors_left_of_start_state={A: True}, actors_have_been_in_left_maneuver={A: True}, **changes)

    def test_passing_each_other_passes_the_rule(self):
        assert self.condition.condition(scene(), scene(colregs_state(actors_passed_each_other=True))) is PASSED

    def test_there_is_no_obligation_in_the_first_seconds_of_the_encounter(self):
        at_the_limit = colregs_state(time_spent_in_current_context=self.immediate)
        assert self.condition.condition(scene(), scene(at_the_limit)) is UNKNOWN

    def test_after_that_the_actor_has_to_be_in_its_avoidance_maneuver_or_fails(self):
        waiting = colregs_state(time_spent_in_current_context=self.immediate + 1)
        assert self.condition.condition(scene(), scene(waiting)) is FAILED
        turned = self._in_left_maneuver(time_spent_in_current_context=self.immediate + 1)
        assert self.condition.condition(scene(), scene(turned)) is UNKNOWN

    def test_the_maneuver_has_to_be_on_the_demanded_side(self):
        wrong_side = colregs_state(actors_right_of_start_state={A: True}, actors_have_been_in_right_maneuver={A: True}, time_spent_in_current_context=self.immediate + 1)
        assert self.condition.condition(scene(), scene(wrong_side)) is FAILED
        right_demanded = colregs_state(
            actors_avoidance_direction={A: Direction.RIGHT}, actors_right_of_start_state={A: True}, actors_have_been_in_right_maneuver={A: True}, time_spent_in_current_context=self.immediate + 1
        )
        assert self.condition.condition(scene(), scene(right_demanded)) is UNKNOWN

    def test_a_forward_demand_needs_no_maneuver(self):
        forward = colregs_state(actors_avoidance_direction={A: Direction.FORWARD}, time_spent_in_current_context=self.immediate + 1)
        assert self.condition.condition(scene(), scene(forward)) is UNKNOWN
        assert self.condition.maneuver_suggestions(scene(forward), 1) == {}

    def test_the_action_has_to_start_before_the_deadline(self):
        deadline = self.condition.action_start_deadline
        assert deadline == max(0, self.immediate - constants().READILY_APPARENT_COURSE_CHANGE_TIME)

    def test_at_the_start_of_the_encounter_turning_is_the_only_suggestion(self):
        """The shipped presets give IMMEDIATE_HEADING_CHANGE_TIME 60 s and READILY_APPARENT_COURSE_CHANGE_TIME 70 s:
        the turn has to be under way at once (deadline 0), so holding the course is not offered any more."""
        assert self.condition.action_start_deadline == 0
        state = colregs_state(time_spent_in_current_context=0)
        suggestions = self.condition.maneuver_suggestions(scene(state), 1)
        assert dict(suggestions) == {A: {LEFT}}

    def test_at_the_deadline_only_the_turn_is_suggested(self):
        state = colregs_state(time_spent_in_current_context=self.condition.action_start_deadline)
        assert self.condition.is_time_to_give_way_early(scene(state), 1)
        assert dict(self.condition.maneuver_suggestions(scene(state), 1)) == {A: {LEFT}}

    def test_nothing_is_suggested_once_the_actor_is_already_turning_or_the_time_has_run_out(self):
        assert self.condition.maneuver_suggestions(scene(self._in_left_maneuver()), 1) == {}
        too_late = colregs_state(time_spent_in_current_context=self.immediate + 1)
        assert not self.condition.is_time_to_give_way_early(scene(too_late), 1)
        assert self.condition.maneuver_suggestions(scene(too_late), 1) == {}


class TestReadilyApparentCourseChange:
    condition = ReadilyApparentCourseChangeCondition(AB, A, constants())

    def test_without_a_course_change_nothing_is_decided(self):
        assert self.condition.condition(scene(), scene(maneuver=maneuver(is_course_change=False))) is UNKNOWN

    def test_a_change_still_inside_the_window_is_undecided(self):
        assert self.condition.condition(scene(), scene(maneuver=maneuver())) is UNKNOWN

    def test_a_change_that_stayed_small_for_the_whole_window_fails(self):
        assert self.condition.condition(scene(), scene(maneuver=maneuver(readily_apparent_time_passed=True))) is FAILED

    def test_a_change_that_became_apparent_does_not_fail(self):
        apparent = maneuver(readily_apparent_time_passed=True, heading_change=SimpleNamespace(is_readily_apparent_since_readily_apparent_time=True))
        assert self.condition.condition(scene(), scene(maneuver=apparent)) is UNKNOWN

    def test_no_suggestion_without_a_course_change(self):
        assert self.condition.maneuver_suggestions(scene(maneuver=maneuver(is_course_change=False)), 1) == {}

    def test_a_change_that_is_not_apparent_yet_has_to_be_kept_up(self):
        suggestions = self.condition.maneuver_suggestions(scene(maneuver=maneuver(type=RIGHT)), 1)
        assert dict(suggestions) == {A: {RIGHT}}

    def test_a_change_that_is_apparent_may_be_followed_by_holding_the_course(self):
        apparent = maneuver(type=RIGHT, heading_change=SimpleNamespace(is_readily_apparent_since_readily_apparent_time=True))
        suggestions = self.condition.maneuver_suggestions(scene(maneuver=apparent), 1)
        assert dict(suggestions) == {A: {RIGHT, PERSIST}}
        assert "ReadilyApparentCourseChangeCondition" in suggestions.get_info(A)
