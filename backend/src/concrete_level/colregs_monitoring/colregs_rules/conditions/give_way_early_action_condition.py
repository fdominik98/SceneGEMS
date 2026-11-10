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

# Share of IMMEDIATE_HEADING_CHANGE_TIME after which the first turn has to be under way.
ACTION_START_WINDOW_FRACTION: float = 0.5


def early_action_start_deadline(colregs_constants: COLREGSConstraints) -> int:
    """Seconds into an encounter by which the give-way vessel's first turn has to be under way.

    Rule 16 is failed once IMMEDIATE_HEADING_CHANGE_TIME is over without a manoeuvre, and
    nothing holds the first turn back: the persistence times only bind after a manoeuvre.
    So the vessel may keep its course for a while, but not until the last moment. A turn
    forced only in the last step before the limit left no margin: the planner turned at the
    last possible node, and the same path judged at one second, where the encounter is
    detected a few seconds earlier, reached the limit with the vessel three seconds into
    its turn and not yet displaced, so the rule failed on a path the planner had certified.
    Half the window is that margin. It used to be IMMEDIATE_HEADING_CHANGE_TIME minus
    READILY_APPARENT_COURSE_CHANGE_TIME, which is 0 with the shipped 60 s and 70 s and so
    demanded the turn at once.
    """
    return int(ACTION_START_WINDOW_FRACTION * colregs_constants.IMMEDIATE_HEADING_CHANGE_TIME)


class GiveWayEarlyActionCondition(RuleCondition):
    def __init__(self, relation: Relation, actor: ConcreteActor, colregs_constants: COLREGSConstraints):
        super().__init__(relation, actor, colregs_constants)

    def in_left_avoidance_maneuver_condition(self, next_colregs_state: COLREGSMonitorState) -> bool:
        return next_colregs_state.actors_left_of_start_state[self.actor] and next_colregs_state.actors_have_been_in_left_maneuver[self.actor]

    def in_right_avoidance_maneuver_condition(self, next_colregs_state: COLREGSMonitorState) -> bool:
        return next_colregs_state.actors_right_of_start_state[self.actor] and next_colregs_state.actors_have_been_in_right_maneuver[self.actor]

    def in_maneuver_condition(self, monitored_scene: MonitoredScene) -> bool:
        avoidance_direction = self.effective_avoidance_direction(monitored_scene)
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
        if self.in_maneuver_condition(current_monitored_scene):
            return ManeuverSuggestions()
        avoidance_direction = self.effective_avoidance_direction(current_monitored_scene)
        suggested_maneuver = AVOIDANCE_DIRECTION_TO_MANEUVER_TYPE[avoidance_direction]
        current_colregs_state = current_monitored_scene.colregs_state_set[self.relation]

        if self.is_time_to_give_way_early(current_monitored_scene, time_step):
            return ManeuverSuggestions({self.actor: {suggested_maneuver}}, {self.actor: f"{self.__class__.__name__} : ({suggested_maneuver})"})
        elif current_colregs_state.time_spent_in_current_context < self.action_start_deadline - time_step:
            return ManeuverSuggestions(
                {self.actor: {suggested_maneuver, ManeuverType.PERSISTING_COURSE}}, {self.actor: f"{self.__class__.__name__} : ({suggested_maneuver}, {ManeuverType.PERSISTING_COURSE})"}
            )
        else:
            return ManeuverSuggestions()

    @property
    def action_start_deadline(self) -> int:
        """Latest moment the alteration has to be under way to count as early action.

        Before it the suggestions offer the turn and holding the course, from one step
        before it only the turn. See ``early_action_start_deadline``.
        """
        return early_action_start_deadline(self.colregs_constants)

    def is_time_to_give_way_early(self, current_monitored_scene: MonitoredScene, time_step: int) -> bool:
        return (
            current_monitored_scene.colregs_state_set[self.relation].time_spent_in_current_context >= self.action_start_deadline - time_step
            and current_monitored_scene.colregs_state_set[self.relation].time_spent_in_current_context <= self.colregs_constants.IMMEDIATE_HEADING_CHANGE_TIME
            and not self.in_maneuver_condition(current_monitored_scene)
        )
