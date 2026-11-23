import math
from typing import Tuple

from concrete_level.colregs_monitoring.colregs_rules.colregs_rule_results import COLREGSRuleResult
from concrete_level.colregs_monitoring.colregs_rules.conditions.rule_condition import RuleCondition
from concrete_level.colregs_monitoring.colregs_rules.maneuver_suggestions import ManeuverSuggestions
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints


def position_in_frame_of(reference: ActorState, other: ActorState) -> Tuple[float, float]:
    """Where ``other`` is seen from ``reference``: (ahead along her heading, to port of it), in metres.

    Built from the heading rather than the velocity, so a vessel lying stopped still has a frame.
    """
    dx = other.x - reference.x
    dy = other.y - reference.y
    forward = dx * math.cos(reference.heading) + dy * math.sin(reference.heading)
    port = -dx * math.sin(reference.heading) + dy * math.cos(reference.heading)
    return forward, port


class GiveWayPassesAsternCondition(RuleCondition):
    """Rule 15: the give-way vessel of a crossing avoids crossing ahead of the stand-on vessel.

    Judged in the step in which the give-way vessel crosses the stand-on vessel's heading line:
    the crossing point is found by interpolating both positions in the stand-on vessel's frame
    over the step, and the vessel fails when that point lies ahead of the stand-on vessel.
    Crossing astern, or never crossing that line while the encounter runs, leaves the rule
    unknown, and the rule state machine passes it when the encounter ends.
    """

    def __init__(self, relation: Relation, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(relation, actor, colregs_constants)

    def condition(self, current_monitored_scene: MonitoredScene, next_monitored_scene: MonitoredScene) -> COLREGSRuleResult:
        next_colregs_state = next_monitored_scene.colregs_state_set.get(self.relation)
        if next_colregs_state is None or next_colregs_state.actors_passed_each_other:
            return COLREGSRuleResult.UNKNOWN
        stand_on = self.relation.actor2 if self.actor == self.relation.actor1 else self.relation.actor1
        crossing_point = self.heading_line_crossing(
            position_in_frame_of(current_monitored_scene.scene[stand_on], current_monitored_scene.scene[self.actor]),
            position_in_frame_of(next_monitored_scene.scene[stand_on], next_monitored_scene.scene[self.actor]),
        )
        if crossing_point is not None and crossing_point > 0.0:
            return COLREGSRuleResult.FAILED
        return COLREGSRuleResult.UNKNOWN

    @staticmethod
    def heading_line_crossing(current: Tuple[float, float], following: Tuple[float, float]):
        """How far ahead of the stand-on vessel the give-way vessel crosses her heading line in this step, or None when it does not cross it.

        A step that starts exactly on the line is not a crossing: the one that reached the line is.
        """
        forward0, port0 = current
        forward1, port1 = following
        if port0 == 0.0 or ((port0 > 0.0) == (port1 > 0.0) and port1 != 0.0):
            return None
        fraction = port0 / (port0 - port1)
        return forward0 + fraction * (forward1 - forward0)

    def maneuver_suggestions(self, current_monitored_scene: MonitoredScene, time_step: int) -> ManeuverSuggestions:
        # Rule 16 already asks the give-way vessel to turn to starboard, which takes her astern.
        return ManeuverSuggestions()
