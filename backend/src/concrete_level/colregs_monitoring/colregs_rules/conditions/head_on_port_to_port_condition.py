import numpy as np

from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import RuleCondition
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints


def line_of_sight_rotation(scene: ConcreteScene, relation: Relation) -> float:
    """The z component of (p2 - p1) x (v2 - v1): positive when the line of sight turns counter-clockwise.

    Counter-clockwise means each vessel sees the other go by on her own port side, so the pair
    passes port to port; clockwise means starboard to starboard. The value is the same for
    either order of the pair and does not depend on the headings, so it still tells the side
    after large alterations of course, where a test against each vessel's own heading line
    would not.
    """
    state1 = scene[relation.actor1]
    state2 = scene[relation.actor2]
    p = state2.p - state1.p
    v = state2.v - state1.v
    return float(p[0] * v[1] - p[1] * v[0])


class HeadOnPortToPortCondition(RuleCondition):
    """Rule 14(a): two vessels meeting head-on each alter course to starboard so that each passes on the port side of the other.

    Judged where the closest point of approach is: in the step that ends with it at most one
    step ahead, or in the step it was crossed in. The rules of a step are those of the context
    the step ends in, so the step that ends the encounter is no longer judged by this rule;
    looking one step ahead catches a pair that reaches its closest approach and is past and
    clear within the same step. The pair fails when it passes starboard to starboard. A pass is
    given by the rule state machine when the encounter ends with the rule still unknown.
    """

    def __init__(self, relation: Relation, colregs_constants: COLREGSConstraints):
        super().__init__(relation, relation.actor1, colregs_constants)

    def condition(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        next_colregs_state = next_monitored_scene.colregs_state_set.get(self.relation)
        if next_colregs_state is None or next_colregs_state.actors_passed_each_other:
            return COLREGSRuleResult.UNKNOWN
        if not self.closest_approach_is_due(current_monitored_scene, next_monitored_scene):
            return COLREGSRuleResult.UNKNOWN
        if line_of_sight_rotation(next_monitored_scene.scene, self.relation) < 0.0:
            return COLREGSRuleResult.FAILED
        return COLREGSRuleResult.UNKNOWN

    def closest_approach_is_due(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> bool:
        """The closest point of approach was crossed in this step, or lies within the next one."""
        time_step = max(next_monitored_scene.timestamp - current_monitored_scene.timestamp, 1)
        current_tcpa = current_monitored_scene.scene.get_tcpa(self.relation.actor1, self.relation.actor2)
        next_tcpa = next_monitored_scene.scene.get_tcpa(self.relation.actor1, self.relation.actor2)
        crossed = current_tcpa >= 0.0 and next_tcpa < 0.0
        due = 0.0 <= next_tcpa <= time_step
        return bool(crossed or due) and not np.isclose(line_of_sight_rotation(next_monitored_scene.scene, self.relation), 0.0)

    def maneuver_suggestions(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        # Rule 16 already asks both vessels to turn to starboard; passing port to port follows from it.
        return ManeuverSuggestions()
