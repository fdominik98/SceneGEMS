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
        avoidance_direction = self.effective_avoidance_direction(current_monitored_scene)
        suggested_maneuver = AVOIDANCE_DIRECTION_TO_MANEUVER_TYPE[avoidance_direction]
        # Only this actor's progress past its own potential collision domain matters;
        # `any(...)` also withdrew the suggestion when the OTHER actor had passed.
        if not current_monitored_scene.colregs_state_set[self.relation].actors_passed_potential_collision_domain.get(self.actor, False):
            return ManeuverSuggestions(
                {self.actor: {suggested_maneuver, ManeuverType.PERSISTING_COURSE}}, {self.actor: f"{self.__class__.__name__} : ({suggested_maneuver}, {ManeuverType.PERSISTING_COURSE})"}
            )
        return ManeuverSuggestions()
