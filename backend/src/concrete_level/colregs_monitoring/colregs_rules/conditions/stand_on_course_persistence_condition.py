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
        return (
            current_monitored_scene.situation_context_set.actor_has_to_give_way(self.actor)
            or current_monitored_scene.colregs_state_set.actor_violates_safety_domain(self.actor)
            or self.is_released_from_standing_on(current_monitored_scene)
        )

    def is_released_from_standing_on(self, current_monitored_scene: MonitoredScene) -> bool:
        """Rule 17(a)(ii) and 17(b): the stand-on vessel may, and eventually must, act.

        Rule 17 is not an absolute obligation to hold course. The stand-on vessel is
        released once it becomes clear the give-way vessel is not taking appropriate
        action, and it is obliged to act when collision cannot be avoided by the
        give-way vessel's action alone. Without this the stand-on vessel was pinned to
        its course no matter how close the encounter became.
        """
        for relation, situation_context in current_monitored_scene.situation_context_set.items():
            if self.actor not in relation or not situation_context.is_stand_on_actor(self.actor):
                continue
            colregs_state = current_monitored_scene.colregs_state_set[relation]
            if colregs_state.actors_passed_each_other:
                continue

            give_way_actor = situation_context.other_actor(self.actor)

            # 17(a)(ii): the give-way vessel has had its window and has not acted.
            if colregs_state.time_spent_in_current_context > self.colregs_constants.IMMEDIATE_HEADING_CHANGE_TIME and not (
                colregs_state.actors_have_been_in_right_maneuver.get(give_way_actor, False) or colregs_state.actors_have_been_in_left_maneuver.get(give_way_actor, False)
            ):
                return True

            # 17(b): so close that the give-way vessel's action alone can no longer help.
            clearance = colregs_state.actors_clearance.get(self.actor)
            if clearance is not None and clearance <= 0.0:
                return True
        return False
