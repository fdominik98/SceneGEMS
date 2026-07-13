from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import RuleCondition
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.maneuver import ManeuverType
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints


class SafeDistanceCondition(RuleCondition):
    def __init__(self, relation: Relation, colregs_constants: COLREGSConstraints):
        super().__init__(relation, relation.actor1, colregs_constants)

    def condition(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        next_colregs_state = next_monitored_scene.colregs_state_set[self.relation]
        if next_colregs_state.actors_violate_safety_domain:
            return COLREGSRuleResult.FAILED
        return COLREGSRuleResult.UNKNOWN

    def maneuver_suggestions(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        if current_monitored_scene.colregs_state_set[self.relation].actors_violate_safety_domain:
            return ManeuverSuggestions(
                {
                    self.relation.actor1: {ManeuverType.COURSE_CHANGE_TO_THE_LEFT, ManeuverType.COURSE_CHANGE_TO_THE_RIGHT},
                    self.relation.actor2: {ManeuverType.COURSE_CHANGE_TO_THE_LEFT, ManeuverType.COURSE_CHANGE_TO_THE_RIGHT},
                },
                {
                    self.relation.actor1: f"{self.__class__.__name__} : ({ManeuverType.COURSE_CHANGE_TO_THE_LEFT}, {ManeuverType.COURSE_CHANGE_TO_THE_RIGHT})",
                    self.relation.actor2: f"{self.__class__.__name__} : ({ManeuverType.COURSE_CHANGE_TO_THE_LEFT}, {ManeuverType.COURSE_CHANGE_TO_THE_RIGHT})",
                },
            )
        return ManeuverSuggestions()
