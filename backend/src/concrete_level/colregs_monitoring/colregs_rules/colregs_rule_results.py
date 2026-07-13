# --- Rule Definition System ---
from enum import Enum, auto
from typing import Dict, List

from concrete_level.colregs_monitoring.colregs_rules.colregs_rules import COLREGSRule
from concrete_level.models.relation import Relation


class COLREGSRuleResult(Enum):
    PASSED = auto()
    FAILED = auto()
    UNKNOWN = auto()


class COLREGSRuleResultMap(Dict[COLREGSRule, COLREGSRuleResult]):
    def is_failed(self) -> bool:
        return any(rule_state == COLREGSRuleResult.FAILED for rule_state in self.values())

    def get_failed_rules(self) -> List["COLREGSRule"]:
        return [rule for rule, result in self.items() if result == COLREGSRuleResult.FAILED]

    def get_result(self, rule: "COLREGSRule") -> COLREGSRuleResult:
        if rule in self:
            return self[rule]
        return COLREGSRuleResult.UNKNOWN


class COLREGSRuleResultMapSet(Dict[Relation, COLREGSRuleResultMap]):
    def is_failed(self) -> bool:
        return any(state.is_failed() for state in self.values())

    def get_failed_rules(self) -> Dict[Relation, List["COLREGSRule"]]:
        return {rel: state.get_failed_rules() for rel, state in self.items()}

    def get_result(self, rel: Relation) -> COLREGSRuleResultMap:
        if rel in self:
            return self[rel]
        return COLREGSRuleResultMap({})

    def merge(self, other: "COLREGSRuleResultMapSet") -> "COLREGSRuleResultMapSet":
        return COLREGSRuleResultMapSet({**self, **other})
