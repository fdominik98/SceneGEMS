from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import RuleCondition
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.maneuver import ManeuverType
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints


class OverturningCondition(RuleCondition):
    def __init__(self, relation: Relation, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(relation, actor, colregs_constants)

    def condition(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        # current_maneuver = state_path.last_state.vessel_maneuvers[self.vessel]
        # if not current_maneuver.heading_change.full_turn_detected:
        #     return COLREGSRuleResult.UNKNOWN

        # return COLREGSRuleResult.FAILED
        return COLREGSRuleResult.UNKNOWN

    def maneuver_suggestions(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        current_maneuver_state = current_monitored_scene.maneuver_state_set[self.relation]
        if current_maneuver_state.heading_change.overturning_detected:
            return ManeuverSuggestions({self.actor: {ManeuverType.PERSISTING_COURSE}}, {self.actor: f"{self.__class__.__name__} : ({ManeuverType.PERSISTING_COURSE})"})
        return ManeuverSuggestions()
