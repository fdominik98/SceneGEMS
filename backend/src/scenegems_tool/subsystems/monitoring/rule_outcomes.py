"""Per rule outcomes of a monitored run, the summary both monitors of a run return.

monitoring.post_hoc builds it over a finished state log, the live monitor of a kinematic
simulation step by step; both add every monitored scene in order. The summary:

    rules         relation, rule, outcome ("passed", "failed"): the first timestamp it held
    failed_rules  [{relation, rule, first_failed_at}], by first failure time, then relation and rule
    encounters    per relation (keyed like rules), the situation types (COLREGSType names) of the pair
                  in order of first appearance; a scene judged alone has its one type per pair
    passed        no rule failed

How rule results evolve (concrete_level/colregs_monitoring): while a rule is active, its
result is checked every step and a failure sticks; a rule that turns inactive keeps its
result (an undecided one counts as passed); a rule that turns active again restarts as
unknown. A pass can therefore still become a failure later, and new relations and rules
appear as the situation changes. Only a failure is final, since the summary keeps the first
failure time of every rule (every_rule_decided).
"""

from typing import Any, Dict, List, Optional

from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult, COLREGSRuleResultMapSet
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredSceneWithResults

FirstOutcomes = Dict[str, Dict[str, Dict[str, int]]]  # relation, rule, outcome: first timestamp
Encounters = Dict[str, List[str]]  # relation: situation types (COLREGSType names) in order of first appearance


class RuleOutcomes:
    def __init__(self) -> None:
        self.first_outcomes: FirstOutcomes = {}
        self.encounters: Encounters = {}
        self.monitored_scenes = 0
        self._latest: Optional[COLREGSRuleResultMapSet] = None

    def add(self, monitored_scene: MonitoredSceneWithResults) -> None:
        self.monitored_scenes += 1
        self._latest = monitored_scene.monitor_result_map_set
        for relation, context in monitored_scene.situation_context_set.items():
            types = self.encounters.setdefault(str(relation), [])
            if context.situation_type.name not in types:
                types.append(context.situation_type.name)
        for relation, result_map in monitored_scene.monitor_result_map_set.items():
            rules = self.first_outcomes.setdefault(str(relation), {})
            for rule, outcome in result_map.items():
                if outcome != COLREGSRuleResult.UNKNOWN:
                    rules.setdefault(str(rule), {}).setdefault(outcome.name.lower(), monitored_scene.timestamp)

    def failed_rules(self) -> List[Dict[str, Any]]:
        return sorted(
            (
                {"relation": relation, "rule": rule, "first_failed_at": outcomes["failed"]}
                for relation, rules in self.first_outcomes.items()
                for rule, outcomes in rules.items()
                if "failed" in outcomes
            ),
            key=lambda item: (item["first_failed_at"], item["relation"], item["rule"]),
        )

    def every_rule_decided(self) -> bool:
        """Every rule of every relation in the latest monitored scene has a final outcome, which only a failure is.

        Conservative on purpose: a run stopped here has a final verdict (failed), but rules
        that would only have become active later are not in its summary.
        """
        if self._latest is None:
            return False
        rules = [(str(relation), str(rule)) for relation, result_map in self._latest.items() for rule in result_map]
        return bool(rules) and all("failed" in self.first_outcomes.get(relation, {}).get(rule, {}) for relation, rule in rules)

    def summary(self) -> Dict[str, Any]:
        failed = self.failed_rules()
        return {"rules": self.first_outcomes, "failed_rules": failed, "encounters": self.encounters, "passed": not failed}
