from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import RuleCondition
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints


class HoldAvoidanceCourseCondition(RuleCondition):
    """After the first evasive, the give-way vessel may steer any way.

    The first alteration is still required by Rule 16 and must be readily apparent.
    Once that manoeuvre has been made, this rule does not keep the vessel on the
    avoidance heading: it may turn toward or away from the original course, including
    to line up with the remaining path around the encounter.
    """

    def __init__(self, relation: Relation, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(relation, actor, colregs_constants)

    def condition(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        if next_monitored_scene.colregs_state_set[self.relation].actors_passed_each_other:
            return COLREGSRuleResult.PASSED
        if self.actor_has_taken_evasive_in_this_encounter(current_monitored_scene):
            return COLREGSRuleResult.PASSED
        return COLREGSRuleResult.UNKNOWN

    def maneuver_suggestions(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        return ManeuverSuggestions()
