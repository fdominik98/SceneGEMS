from typing import Dict

from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import AVOIDANCE_DIRECTION_TO_MANEUVER_TYPE, RuleCondition
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.maneuver import ManeuverType
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints

OPPOSITE_MANEUVER_TYPE: Dict[ManeuverType, ManeuverType] = {
    ManeuverType.COURSE_CHANGE_TO_THE_RIGHT: ManeuverType.COURSE_CHANGE_TO_THE_LEFT,
    ManeuverType.COURSE_CHANGE_TO_THE_LEFT: ManeuverType.COURSE_CHANGE_TO_THE_RIGHT,
}


class HoldAvoidanceCourseCondition(RuleCondition):
    """The avoidance course is held until the encounter is over.

    A course change that is taken back while the other vessel still has to be kept clear
    of is not readily apparent: the other vessel sees the alteration and then sees it
    undone, and the pair of them reads as course keeping. Only movement BACK toward the
    original course is withheld. Holding, and turning further out, both stay available,
    so a give-way vessel can still escalate when its clearance degrades, and it may
    resume its original course once the vessels have passed each other.
    """

    def __init__(self, relation: Relation, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(relation, actor, colregs_constants)

    def avoidance_maneuver(self, monitored_scene: MonitoredScene) -> ManeuverType:
        avoidance_direction = self.effective_avoidance_direction(monitored_scene)
        return AVOIDANCE_DIRECTION_TO_MANEUVER_TYPE[avoidance_direction]

    def has_taken_avoidance_action(self, monitored_scene: MonitoredScene) -> bool:
        colregs_state = monitored_scene.colregs_state_set[self.relation]
        avoidance_maneuver = self.avoidance_maneuver(monitored_scene)
        if avoidance_maneuver is ManeuverType.COURSE_CHANGE_TO_THE_RIGHT:
            return colregs_state.actors_have_been_in_right_maneuver.get(self.actor, False)
        if avoidance_maneuver is ManeuverType.COURSE_CHANGE_TO_THE_LEFT:
            return colregs_state.actors_have_been_in_left_maneuver.get(self.actor, False)
        return False

    def has_to_hold(self, monitored_scene: MonitoredScene) -> bool:
        if monitored_scene.colregs_state_set[self.relation].actors_passed_each_other:
            return False
        # Rule 2(b): the hold gives way to immediate danger. A vessel already inside a
        # safety domain, which may well be a third vessel's, has to be free to take
        # whatever action clears it, and without this a vessel that had given way to
        # starboard for one ship could never turn to port for another: the suggestion
        # sets would intersect to nothing and the branch would be pruned in silence.
        if monitored_scene.colregs_state_set.actor_violates_safety_domain(self.actor):
            return False
        return self.has_taken_avoidance_action(monitored_scene)

    def has_drifted_back(self, monitored_scene: MonitoredScene) -> bool:
        """A hold that is quietly walking back toward the original course.

        The manoeuvre type alone cannot see this. A return made slower than the
        undetectable rate is classified PERSISTING_COURSE at every single step, and the
        persisting state only gives way to a course change once the angle accumulated
        since the hold began becomes READILY APPARENT, so nearly 30 deg of drift passes
        as keeping course. Measured on this scene: a 61 deg starboard alteration walked
        back to 34 deg over 200 s without ever leaving the persisting state, and a 33 deg
        one walked back to 2 deg over 270 s. The manoeuvre's own accumulator is what sees
        it, and it is an angle since the hold began rather than a per-step difference, so
        it reads the same at the planner's step and at the console's.
        """
        maneuver_state = monitored_scene.maneuver_state_set[Relation(self.actor, self.actor)]
        if not maneuver_state.is_persisting_course:
            return False
        given_back = maneuver_state.heading_change.heading_diff_since_start
        avoidance_maneuver = self.avoidance_maneuver(monitored_scene)
        if avoidance_maneuver is ManeuverType.COURSE_CHANGE_TO_THE_RIGHT:
            return given_back > self.give_back_tolerance
        if avoidance_maneuver is ManeuverType.COURSE_CHANGE_TO_THE_LEFT:
            return -given_back > self.give_back_tolerance
        return False

    @property
    def give_back_tolerance(self) -> float:
        """How much of the alteration a hold may give back before it counts as returning.

        The undetectable band, which is the most that can be given back without the other
        vessel being able to see it. Widening it does not help: the search optimises
        against whatever bound this is and drifts back to exactly the bound, so raising it
        to a third of the readily apparent angle simply produced a nine degree give-back
        instead of a two degree one, and the one second re-simulation of the same path
        still crossed the larger bound. The bound is not what needs fixing; while the
        objective charges cross-track offset there is always pressure against it, and the
        real answer is to take the give-back out of the ACTION SET while a hold is in
        force rather than to price it.
        """
        return self.colregs_constants.UNDETECTABLE_HEADING_CHANGE

    def condition(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        if next_monitored_scene.colregs_state_set[self.relation].actors_passed_each_other:
            return COLREGSRuleResult.PASSED

        if not self.has_to_hold(current_monitored_scene):
            return COLREGSRuleResult.UNKNOWN

        reverse_maneuver = OPPOSITE_MANEUVER_TYPE[self.avoidance_maneuver(current_monitored_scene)]
        if next_monitored_scene.maneuver_state_set[Relation(self.actor, self.actor)].type is reverse_maneuver:
            return COLREGSRuleResult.FAILED

        if self.has_drifted_back(next_monitored_scene):
            return COLREGSRuleResult.FAILED

        return COLREGSRuleResult.UNKNOWN

    def maneuver_suggestions(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        if not self.has_to_hold(current_monitored_scene):
            return ManeuverSuggestions()
        avoidance_maneuver = self.avoidance_maneuver(current_monitored_scene)
        return ManeuverSuggestions(
            {self.actor: {avoidance_maneuver, ManeuverType.PERSISTING_COURSE}},
            {self.actor: f"{self.__class__.__name__} : ({avoidance_maneuver}, {ManeuverType.PERSISTING_COURSE})"},
        )
