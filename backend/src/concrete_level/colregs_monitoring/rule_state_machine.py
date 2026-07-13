from typing import Set, Tuple

from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult, COLREGSRuleResultMap, COLREGSRuleResultMapSet
from concrete_level.colregs_monitoring.colregs_rules.colregs_rules import COLREGSRule
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import COLREGSRuleConditionMapSet
from concrete_level.colregs_monitoring.colregs_rules.default_rules import make_default_maneuver_context_rules, make_default_situation_context_rules
from concrete_level.colregs_monitoring.maneuver_context import ManeuverContextSet
from concrete_level.colregs_monitoring.situation_context import SituationContextSet
from concrete_level.models.relation import Relation


class RuleStateMachine:
    """Static class for updating active rules and rule results when situation contexts change."""

    @staticmethod
    def build_rules(situation_context_set: SituationContextSet, maneuver_context_set: ManeuverContextSet) -> COLREGSRuleConditionMapSet:
        return make_default_situation_context_rules(situation_context_set).merge(make_default_maneuver_context_rules(maneuver_context_set))

    @staticmethod
    def create_initial_rules(situation_context_set: SituationContextSet, maneuver_context_set: ManeuverContextSet) -> COLREGSRuleConditionMapSet:
        """Create the initial active rule set."""
        return RuleStateMachine.build_rules(situation_context_set, maneuver_context_set)

    @staticmethod
    def step(
        current_situation_context_set: SituationContextSet,
        next_situation_context_set: SituationContextSet,
        maneuver_context_set: ManeuverContextSet,
        current_monitor_result_map_set: COLREGSRuleResultMapSet,
    ) -> Tuple[COLREGSRuleConditionMapSet, COLREGSRuleResultMapSet]:
        """Build the next active rules and transition rule results without mutating prior state."""
        current_rules = RuleStateMachine.build_rules(current_situation_context_set, maneuver_context_set)
        next_rules = RuleStateMachine.build_rules(next_situation_context_set, maneuver_context_set)
        next_monitor_result_map_set = RuleStateMachine.transition_rule_results(current_rules, current_monitor_result_map_set, next_rules)
        return next_rules, next_monitor_result_map_set

    @staticmethod
    def transition_rule_results(
        current_rules: COLREGSRuleConditionMapSet,
        current_monitor_result_map_set: COLREGSRuleResultMapSet,
        next_rules: COLREGSRuleConditionMapSet,
    ) -> COLREGSRuleResultMapSet:
        all_relations = set(current_monitor_result_map_set.keys()) | set(current_rules.keys()) | set(next_rules.keys())
        next_monitor_result_map_set = COLREGSRuleResultMapSet()

        for relation in all_relations:
            current_active_rules = RuleStateMachine._active_rules(current_rules, relation)
            next_active_rules = RuleStateMachine._active_rules(next_rules, relation)
            current_result_map = current_monitor_result_map_set.get_result(relation)
            next_result_map = COLREGSRuleResultMap({})

            for rule, result in current_result_map.items():
                next_result_map[rule] = RuleStateMachine._transition_rule_result(rule, result, current_active_rules, next_active_rules)

            for rule in next_active_rules:
                if rule not in next_result_map:
                    next_result_map[rule] = COLREGSRuleResult.UNKNOWN

            next_monitor_result_map_set[relation] = next_result_map

        return next_monitor_result_map_set

    @staticmethod
    def _active_rules(rules: COLREGSRuleConditionMapSet, relation: Relation) -> Set[COLREGSRule]:
        if relation not in rules:
            return set()
        return set(rules[relation].keys())

    @staticmethod
    def _transition_rule_result(
        rule: COLREGSRule,
        result: COLREGSRuleResult,
        current_active_rules: Set[COLREGSRule],
        next_active_rules: Set[COLREGSRule],
    ) -> COLREGSRuleResult:
        if rule in current_active_rules and rule in next_active_rules:
            return result
        if rule in next_active_rules:
            return COLREGSRuleResult.UNKNOWN
        if result == COLREGSRuleResult.UNKNOWN:
            return COLREGSRuleResult.PASSED
        return result
