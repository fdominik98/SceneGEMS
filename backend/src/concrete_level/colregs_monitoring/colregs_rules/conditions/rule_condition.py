from abc import ABC, abstractmethod
from typing import Dict

from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult, COLREGSRuleResultMap, COLREGSRuleResultMapSet
from concrete_level.colregs_monitoring.colregs_rules.colregs_rules import COLREGSRule
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.maneuver import ManeuverType
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints
from utils.math_utils import Direction

AVOIDANCE_DIRECTION_TO_MANEUVER_TYPE: Dict[Direction, ManeuverType] = {
    Direction.LEFT: ManeuverType.COURSE_CHANGE_TO_THE_LEFT,
    Direction.RIGHT: ManeuverType.COURSE_CHANGE_TO_THE_RIGHT,
    Direction.FORWARD: ManeuverType.PERSISTING_COURSE,
    Direction.BACKWARD: ManeuverType.UNDETECTED,
}


class RuleCondition(ABC):
    def __init__(self, relation: Relation, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        self.relation = relation
        self.actor = actor
        self.colregs_constants = colregs_constants

    @abstractmethod
    def condition(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        pass

    @abstractmethod
    def maneuver_suggestions(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        pass

    def effective_avoidance_direction(self, monitored_scene: MonitoredScene) -> Direction:
        """Which side this actor should pass on, for the encounter this instance judges.

        Read from the monitor state, where it was decided when the encounter began and
        has been carried unchanged ever since. It must not be recomputed here. The value
        depends on which OTHER encounters the actor is in at the moment it is asked for,
        because encounters that ask for opposite sides are jointly unsatisfiable and have
        to be collapsed to one side. Recomputed per scene, an unrelated encounter ending
        silently flips this one: measured on a vessel overtaking two ships at once, both
        encounters collapsed to starboard, the vessel turned starboard, and 400 s later
        the first encounter cleared, the second reverted to its own port direction, and
        Rule 16 failed retroactively against the turn the monitor itself had demanded.
        Every successor was rejected and the search could not pass that step.

        See ``COLREGSStateMachine.get_actors_avoidance_direction`` for how it is seeded.
        """
        colregs_state = monitored_scene.colregs_state_set.get(self.relation)
        if colregs_state is None:
            # No state for this relation yet, which happens only before the first step.
            return monitored_scene.situation_context_set.resolved_avoidance_direction(self.relation, self.actor)
        return colregs_state.actors_avoidance_direction.get(self.actor, Direction.FORWARD)

    def actor_has_taken_evasive_in_this_encounter(self, monitored_scene: MonitoredScene) -> bool:
        """True once this actor has made a course change during the judged encounter."""
        state = monitored_scene.colregs_state_set.get(self.relation)
        if state is None:
            return False
        return state.actors_have_been_in_right_maneuver.get(self.actor, False) or state.actors_have_been_in_left_maneuver.get(self.actor, False)

    def give_way_has_taken_first_evasive(self, monitored_scene: MonitoredScene) -> bool:
        """True once this actor has made its give-way course change in any live encounter.

        Maneuver-level rules are keyed by (actor, actor), not by an encounter, so they
        have to look through the situation set. After that first evasive the give-way
        vessel may steer any way; stand-on vessels never match.
        """
        for relation, context in monitored_scene.situation_context_set.items():
            if self.actor not in relation:
                continue
            if not context.is_give_way_actor(self.actor):
                continue
            state = monitored_scene.colregs_state_set.get(relation)
            if state is None:
                continue
            if state.actors_have_been_in_right_maneuver.get(self.actor, False) or state.actors_have_been_in_left_maneuver.get(self.actor, False):
                return True
        return False

    def __str__(self) -> str:
        return f"{self.__class__.__name__} : ({self.relation}, {self.actor})"

    def __repr__(self) -> str:
        return str(self)

    def __hash__(self) -> int:
        return hash(self.__str__() + str(self.relation) + str(self.actor))


class COLREGSRuleConditionMap(Dict[COLREGSRule, RuleCondition]):
    def check(self, current_monitored_scene: MonitoredScene, current_monitor_result_map: COLREGSRuleResultMap, next_monitored_scene: MonitoredScene) -> COLREGSRuleResultMap:
        return COLREGSRuleResultMap(
            {
                rule: COLREGSRuleResult.FAILED if current_monitor_result_map.get_result(rule) is COLREGSRuleResult.FAILED else condition.condition(current_monitored_scene, next_monitored_scene)
                for rule, condition in self.items()
            }
        )

    def suggest_maneuvers(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        maneuver_suggestions = ManeuverSuggestions()
        for condition in self.values():
            maneuver_suggestions = maneuver_suggestions.merge(condition.maneuver_suggestions(current_monitored_scene, time_step))
        return maneuver_suggestions


class COLREGSRuleConditionMapSet(Dict[Relation, COLREGSRuleConditionMap]):
    def merge(self, other: "COLREGSRuleConditionMapSet") -> "COLREGSRuleConditionMapSet":
        return COLREGSRuleConditionMapSet({**self, **other})

    def check(
        self,
        current_monitored_scene: MonitoredScene,
        baseline_monitor_result_map_set: COLREGSRuleResultMapSet,
        next_monitored_scene: MonitoredScene,
    ) -> COLREGSRuleResultMapSet:
        all_relations = set(baseline_monitor_result_map_set.keys()) | set(self.keys())
        next_monitor_result_map_set = COLREGSRuleResultMapSet()

        for relation in all_relations:
            baseline_result_map = baseline_monitor_result_map_set.get_result(relation)
            if relation not in self:
                next_monitor_result_map_set[relation] = COLREGSRuleResultMap(dict(baseline_result_map))
                continue

            checked_active_results = self[relation].check(current_monitored_scene, baseline_result_map, next_monitored_scene)
            next_result_map = COLREGSRuleResultMap(dict(baseline_result_map))
            next_result_map.update(checked_active_results)
            next_monitor_result_map_set[relation] = next_result_map

        return next_monitor_result_map_set

    def suggest_maneuvers(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        maneuver_suggestions = ManeuverSuggestions()
        for condition_map in self.values():
            maneuver_suggestions = maneuver_suggestions.merge(condition_map.suggest_maneuvers(current_monitored_scene, time_step))
        return maneuver_suggestions
