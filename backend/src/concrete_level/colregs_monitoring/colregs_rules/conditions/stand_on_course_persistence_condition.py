from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import RuleCondition
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.maneuver import ManeuverType
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints


class StandOnCoursePersistenceCondition(RuleCondition):
    def __init__(self, relation: Relation, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(relation, actor, colregs_constants)

    def condition(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        if self.actor_has_to_give_way(current_monitored_scene):
            return COLREGSRuleResult.UNKNOWN

        next_maneuver_state = next_monitored_scene.maneuver_state_set[self.relation]
        current_maneuver_state = current_monitored_scene.maneuver_state_set[self.relation]
        if current_maneuver_state.is_persisting_course:
            if not next_maneuver_state.is_persisting_course:
                return COLREGSRuleResult.FAILED
            if next_maneuver_state.speed_change.speed_change_detected_since_start:
                return COLREGSRuleResult.FAILED
        return COLREGSRuleResult.UNKNOWN

    def maneuver_suggestions(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        if self.actor_has_to_give_way(current_monitored_scene):
            return ManeuverSuggestions()
        return ManeuverSuggestions({self.actor: {ManeuverType.PERSISTING_COURSE}}, {self.actor: f"{self.__class__.__name__} : ({ManeuverType.PERSISTING_COURSE})"})

    def actor_has_to_give_way(self, current_monitored_scene: MonitoredScene) -> bool:
        return current_monitored_scene.situation_context_set.actor_has_to_give_way(self.actor) or current_monitored_scene.colregs_state_set.actor_violates_safety_domain(self.actor)
