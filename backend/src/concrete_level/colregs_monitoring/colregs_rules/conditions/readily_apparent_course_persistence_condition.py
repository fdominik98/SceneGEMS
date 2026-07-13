from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import RuleCondition
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.maneuver import ManeuverType
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints
class ReadilyApparentCoursePersistenceCondition(RuleCondition):
    def __init__(self, relation: Relation, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(relation, actor, colregs_constants)

    def condition(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        current_maneuver_state = current_monitored_scene.maneuver_state_set[self.relation]

        if not current_maneuver_state.is_persisting_course:
            return COLREGSRuleResult.UNKNOWN

        next_maneuver_state = next_monitored_scene.maneuver_state_set[self.relation]
        if not next_maneuver_state.same_maneuver(current_maneuver_state) and current_maneuver_state.timespan < self.colregs_constants.HEADING_PERSISTENCE_TIME:
            return COLREGSRuleResult.FAILED

        return COLREGSRuleResult.UNKNOWN

    def maneuver_suggestions(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        current_maneuver_state = current_monitored_scene.maneuver_state_set[self.relation]
        if current_maneuver_state.is_persisting_course and current_maneuver_state.timespan < self.colregs_constants.HEADING_PERSISTENCE_TIME:
            return ManeuverSuggestions({self.actor: {ManeuverType.PERSISTING_COURSE}}, {self.actor: f"{self.__class__.__name__} : ({ManeuverType.PERSISTING_COURSE})"})
        return ManeuverSuggestions()
