from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import AVOIDANCE_DIRECTION_TO_MANEUVER_TYPE, RuleCondition
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.maneuver import ManeuverType
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints


class GoAroundCollisionDomainCondition(RuleCondition):
    def __init__(self, relation: Relation, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(relation, actor, colregs_constants)

    def condition(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        return COLREGSRuleResult.UNKNOWN

    def maneuver_suggestions(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        avoidance_direction = current_monitored_scene.situation_context_set.actor_avoidance_direction(self.actor)
        suggested_maneuver = AVOIDANCE_DIRECTION_TO_MANEUVER_TYPE[avoidance_direction]
        if not any(current_monitored_scene.colregs_state_set[self.relation].actors_passed_potential_collision_domain.values()):
            return ManeuverSuggestions(
                {self.actor: {suggested_maneuver, ManeuverType.PERSISTING_COURSE}}, {self.actor: f"{self.__class__.__name__} : ({suggested_maneuver}, {ManeuverType.PERSISTING_COURSE})"}
            )
        return ManeuverSuggestions()
