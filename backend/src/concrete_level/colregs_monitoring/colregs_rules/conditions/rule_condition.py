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
