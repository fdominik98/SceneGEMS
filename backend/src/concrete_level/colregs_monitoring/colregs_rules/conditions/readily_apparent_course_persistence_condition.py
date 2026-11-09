from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import RuleCondition
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.maneuver import ManeuverType
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints

# The maneuvers after which a new heading has to be held: a persisting course that follows one of
# them is the course change's new heading. The persisting course a vessel starts with (it follows the
# undetected start) was never changed to, so it may end at any time.
COURSE_CHANGES = (ManeuverType.COURSE_CHANGE_TO_THE_LEFT, ManeuverType.COURSE_CHANGE_TO_THE_RIGHT)


class ReadilyApparentCoursePersistenceCondition(RuleCondition):
    def __init__(self, relation: Relation, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(relation, actor, colregs_constants)

    @staticmethod
    def holds_a_changed_course(maneuver_state) -> bool:
        """Whether the vessel holds the new heading of a course change, which HEADING_PERSISTENCE_TIME applies to."""
        return maneuver_state.is_persisting_course and maneuver_state.previous_maneuver_type in COURSE_CHANGES

    def condition(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        if self.give_way_has_taken_first_evasive(current_monitored_scene):
            return COLREGSRuleResult.UNKNOWN
        current_maneuver_state = current_monitored_scene.maneuver_state_set[self.relation]

        if not self.holds_a_changed_course(current_maneuver_state):
            return COLREGSRuleResult.UNKNOWN

        next_maneuver_state = next_monitored_scene.maneuver_state_set[self.relation]
        if not next_maneuver_state.same_maneuver(current_maneuver_state) and current_maneuver_state.timespan < self.colregs_constants.HEADING_PERSISTENCE_TIME:
            return COLREGSRuleResult.FAILED

        return COLREGSRuleResult.UNKNOWN

    def maneuver_suggestions(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        if self.give_way_has_taken_first_evasive(current_monitored_scene):
            return ManeuverSuggestions()
        current_maneuver_state = current_monitored_scene.maneuver_state_set[self.relation]
        if self.holds_a_changed_course(current_maneuver_state) and current_maneuver_state.timespan < self.colregs_constants.HEADING_PERSISTENCE_TIME:
            return ManeuverSuggestions({self.actor: {ManeuverType.PERSISTING_COURSE}}, {self.actor: f"{self.__class__.__name__} : ({ManeuverType.PERSISTING_COURSE})"})
        return ManeuverSuggestions()
