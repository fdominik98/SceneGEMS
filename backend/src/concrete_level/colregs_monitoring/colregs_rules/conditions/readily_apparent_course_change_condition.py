from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import RuleCondition
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.maneuver import ManeuverType
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints


class ReadilyApparentCourseChangeCondition(RuleCondition):
    def __init__(self, relation: Relation, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(relation, actor, colregs_constants)

    def condition(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        next_maneuver_state = next_monitored_scene.maneuver_state_set[self.relation]
        if not next_maneuver_state.is_course_change:
            return COLREGSRuleResult.UNKNOWN

        if next_maneuver_state.readily_apparent_time_passed and next_maneuver_state.heading_change.is_readily_apparent_since_readily_apparent_time:
            return COLREGSRuleResult.FAILED

        return COLREGSRuleResult.UNKNOWN

    def maneuver_suggestions(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        current_maneuver_state = current_monitored_scene.maneuver_state_set[self.relation]
        if not current_maneuver_state.is_course_change:
            return ManeuverSuggestions()

        if not current_maneuver_state.heading_change.is_readily_apparent_since_readily_apparent_time:
            return ManeuverSuggestions({self.actor: {current_maneuver_state.type}}, {self.actor: f"{self.__class__.__name__} : ({current_maneuver_state.type})"})
        return ManeuverSuggestions(
            {self.actor: {current_maneuver_state.type, ManeuverType.PERSISTING_COURSE}}, {self.actor: f"{self.__class__.__name__} : ({current_maneuver_state.type}, {ManeuverType.PERSISTING_COURSE})"}
        )
