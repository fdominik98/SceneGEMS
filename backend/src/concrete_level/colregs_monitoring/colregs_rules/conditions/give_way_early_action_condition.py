from concrete_level.colregs_monitoring.colregs_monitor_state import COLREGSMonitorState
from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import AVOIDANCE_DIRECTION_TO_MANEUVER_TYPE, RuleCondition
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.maneuver import ManeuverType
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints
from utils.math_utils import Direction


class GiveWayEarlyActionCondition(RuleCondition):
    def __init__(self, relation: Relation, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(relation, actor, colregs_constants)

    def in_left_avoidance_maneuver_condition(self, next_colregs_state: COLREGSMonitorState) -> bool:
        return next_colregs_state.actors_left_of_start_state[self.actor] and next_colregs_state.actors_have_been_in_left_maneuver[self.actor]

    def in_right_avoidance_maneuver_condition(self, next_colregs_state: COLREGSMonitorState) -> bool:
        return next_colregs_state.actors_right_of_start_state[self.actor] and next_colregs_state.actors_have_been_in_right_maneuver[self.actor]

    def in_maneuver_condition(self, monitored_scene: MonitoredScene) -> bool:
        avoidance_direction = monitored_scene.situation_context_set.actor_avoidance_direction(self.actor)
        if avoidance_direction is Direction.LEFT:
            return self.in_left_avoidance_maneuver_condition(monitored_scene.colregs_state_set[self.relation])
        elif avoidance_direction is Direction.RIGHT:
            return self.in_right_avoidance_maneuver_condition(monitored_scene.colregs_state_set[self.relation])
        return True

    def condition(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        next_colregs_state = next_monitored_scene.colregs_state_set[self.relation]
        if next_colregs_state.actors_passed_each_other:
            return COLREGSRuleResult.PASSED

        if next_colregs_state.time_spent_in_current_context <= self.colregs_constants.IMMEDIATE_HEADING_CHANGE_TIME:
            return COLREGSRuleResult.UNKNOWN

        if not self.in_maneuver_condition(next_monitored_scene):
            return COLREGSRuleResult.FAILED

        return COLREGSRuleResult.UNKNOWN

    def maneuver_suggestions(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        avoidance_direction = current_monitored_scene.situation_context_set.actor_avoidance_direction(self.actor)
        suggested_maneuver = AVOIDANCE_DIRECTION_TO_MANEUVER_TYPE[avoidance_direction]
        current_colregs_state = current_monitored_scene.colregs_state_set[self.relation]

        if self.is_time_to_give_way_early(current_monitored_scene, time_step):
            return ManeuverSuggestions({self.actor: {suggested_maneuver}}, {self.actor: f"{self.__class__.__name__} : ({suggested_maneuver})"})
        elif current_colregs_state.time_spent_in_current_context < self.colregs_constants.IMMEDIATE_HEADING_CHANGE_TIME - time_step:
            return ManeuverSuggestions(
                {self.actor: {suggested_maneuver, ManeuverType.PERSISTING_COURSE}}, {self.actor: f"{self.__class__.__name__} : ({suggested_maneuver}, {ManeuverType.PERSISTING_COURSE})"}
            )
        else:
            return ManeuverSuggestions()

    def is_time_to_give_way_early(self, current_monitored_scene: MonitoredScene, time_step: int) -> bool:
        return (
            current_monitored_scene.colregs_state_set[self.relation].time_spent_in_current_context >= self.colregs_constants.IMMEDIATE_HEADING_CHANGE_TIME - time_step
            and current_monitored_scene.colregs_state_set[self.relation].time_spent_in_current_context <= self.colregs_constants.IMMEDIATE_HEADING_CHANGE_TIME
            and not self.in_maneuver_condition(current_monitored_scene)
        )
