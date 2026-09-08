from typing import Callable, Dict

from concrete_level.colregs_monitoring.colregs_monitor_state import COLREGSMonitorState, COLREGSMonitorStateSet
from concrete_level.colregs_monitoring.maneuver import ManeuverState, ManeuverStateSet
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.colregs_monitoring.situation_context import COLREGSType, SituationContext, SituationContextSet
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from utils.math_utils import Direction


class COLREGSStateMachine:
    """Static class for monitoring COLREGS compliance for vessel pairs"""

    @staticmethod
    def create_initial_state_set(situation_context_set: SituationContextSet) -> COLREGSMonitorStateSet:
        """Create initial COLREGS monitor state"""
        initial_monitor_state_set: Dict[Relation, COLREGSMonitorState] = {}
        for relation, situation_context in situation_context_set.items():
            initial_scene = situation_context.start_scene

            initial_monitor_state_set[relation] = COLREGSMonitorState(
                actors_see_each_other=situation_context.actors_see_each_other,
                actors_passed_each_other=situation_context.actors_passed_each_other,
                actors_violate_safety_domain=situation_context.actors_violate_safety_domain,
                actors_on_collision_course=situation_context.actors_on_collision_course,
                actors_have_low_tcpa=situation_context.actors_have_low_tcpa,
                actors_right_of_start_state=situation_context.get_actors_right_of_start_state(initial_scene),
                actors_left_of_start_state=situation_context.get_actors_left_of_start_state(initial_scene),
                # Nobody has manoeuvred yet at t=0. These were seeded from the
                # left/right-of-start-state position predicates, which are a different
                # quantity and were additionally swapped left for right.
                actors_have_been_in_right_maneuver={actor: False for actor in situation_context.actors},
                actors_have_been_in_left_maneuver={actor: False for actor in situation_context.actors},
                actors_passed_potential_collision_domain=situation_context.get_actors_passed_potential_collision_domain(initial_scene),
                actors_in_front_of_potential_collision_domain=situation_context.get_actors_in_front_of_potential_collision_domain(initial_scene),
                current_timestamp=situation_context.start_timestamp,
                time_spent_in_current_context=0,
                actors_clearance={actor: situation_context.get_actor_clearance(initial_scene, actor) for actor in situation_context.actors},
                actors_side_offset={actor: situation_context.get_actor_side_offset(initial_scene, actor) for actor in situation_context.actors},
                min_step_clearance=situation_context.get_actor_min_step_clearance(initial_scene, initial_scene),
                # Every context is created at once here, so there is no earlier
                # commitment to respect and the set-wide tie-break decides.
                actors_avoidance_direction={actor: situation_context_set.resolved_avoidance_direction(relation, actor) for actor in situation_context.actors},
            )
        return COLREGSMonitorStateSet(
            initial_monitor_state_set,
            actors_violate_safety_domain=COLREGSMonitorStateSet.collect_actors_violate_safety_domain(initial_monitor_state_set),
        )

    @staticmethod
    def step(
        current_monitored_scene: MonitoredScene,
        next_situation_context_set: SituationContextSet,
        next_scene: ConcreteScene,
        next_maneuver_state_set: ManeuverStateSet,
        current_timestamp: int,
    ) -> COLREGSMonitorStateSet:
        """Calculate next COLREGS monitor state"""
        next_monitor_state_set: Dict[Relation, COLREGSMonitorState] = {}
        committed_avoidance_directions = COLREGSStateMachine.get_committed_avoidance_directions(current_monitored_scene)

        for relation in next_situation_context_set.relations:
            situation_context = next_situation_context_set[relation]

            current_state = current_monitored_scene.colregs_state_set[relation]

            actors_passed_each_other = situation_context.get_actors_passed_each_other(next_scene)
            actors_right_of_start_state = situation_context.get_actors_right_of_start_state(next_scene)
            actors_left_of_start_state = situation_context.get_actors_left_of_start_state(next_scene)
            actors_passed_potential_collision_domain = situation_context.get_actors_passed_potential_collision_domain(next_scene)
            actors_in_front_of_potential_collision_domain = situation_context.get_actors_in_front_of_potential_collision_domain(next_scene)
            is_safety_domain_violation = situation_context.get_actors_violate_safety_domain(next_scene)
            vessels_on_collision_course = situation_context.get_actors_on_collision_course(next_scene)
            actors_have_low_tcpa = situation_context.get_actors_have_low_tcpa(next_scene)
            actors_see_each_other = situation_context.get_actors_see_each_other(next_scene)
            # SituationContextStateMachine.step returns the SAME context object while an
            # encounter holds and a new one when it changes, so identity is exactly the
            # "this encounter just started" test.
            current_context = current_monitored_scene.situation_context_set.get(relation)
            context_is_new = current_context is not situation_context

            actors_have_been_in_right_maneuver = COLREGSStateMachine.get_actors_have_been_in_right_maneuver(situation_context, current_state, next_maneuver_state_set, context_is_new)
            actors_have_been_in_left_maneuver = COLREGSStateMachine.get_actors_have_been_in_left_maneuver(situation_context, current_state, next_maneuver_state_set, context_is_new)
            time_spent_in_current_context = current_timestamp - situation_context.start_timestamp

            next_monitor_state_set[relation] = COLREGSMonitorState(
                actors_see_each_other=actors_see_each_other,
                actors_violate_safety_domain=is_safety_domain_violation,
                actors_on_collision_course=vessels_on_collision_course,
                actors_have_low_tcpa=actors_have_low_tcpa,
                actors_right_of_start_state=actors_right_of_start_state,
                actors_left_of_start_state=actors_left_of_start_state,
                actors_have_been_in_right_maneuver=actors_have_been_in_right_maneuver,
                actors_have_been_in_left_maneuver=actors_have_been_in_left_maneuver,
                actors_passed_potential_collision_domain=actors_passed_potential_collision_domain,
                actors_in_front_of_potential_collision_domain=actors_in_front_of_potential_collision_domain,
                actors_passed_each_other=actors_passed_each_other,
                current_timestamp=current_timestamp,
                time_spent_in_current_context=time_spent_in_current_context,
                actors_clearance={actor: situation_context.get_actor_clearance(next_scene, actor) for actor in situation_context.actors},
                actors_side_offset={actor: situation_context.get_actor_side_offset(next_scene, actor) for actor in situation_context.actors},
                min_step_clearance=situation_context.get_actor_min_step_clearance(current_monitored_scene.scene, next_scene),
                actors_avoidance_direction=COLREGSStateMachine.get_actors_avoidance_direction(next_situation_context_set, relation, current_state, committed_avoidance_directions, context_is_new),
            )
        return COLREGSMonitorStateSet(
            next_monitor_state_set,
            actors_violate_safety_domain=COLREGSMonitorStateSet.collect_actors_violate_safety_domain(next_monitor_state_set),
        )

    @staticmethod
    def get_committed_avoidance_directions(monitored_scene: MonitoredScene) -> Dict[ConcreteActor, Direction]:
        """The side each actor has already committed to, across its live encounters.

        Only encounters that are still running commit anything, and only a real side
        does: FORWARD means no alteration was called for, which contradicts nothing. An
        actor cannot un-commit, so if two live encounters somehow hold opposite sides the
        starboard one is reported, matching ``get_actor_avoidance_direction``.
        """
        committed: Dict[ConcreteActor, Direction] = {}
        for relation, state in monitored_scene.colregs_state_set.items():
            context = monitored_scene.situation_context_set.get(relation)
            if context is None or context.situation_type is COLREGSType.OTHER:
                continue
            for actor, direction in state.actors_avoidance_direction.items():
                if direction is Direction.FORWARD:
                    continue
                if committed.get(actor) is Direction.RIGHT:
                    continue
                committed[actor] = direction
        return committed

    @staticmethod
    def get_actors_avoidance_direction(
        next_situation_context_set: SituationContextSet,
        relation: Relation,
        current_state: COLREGSMonitorState,
        committed_avoidance_directions: Dict[ConcreteActor, Direction],
        context_is_new: bool,
    ) -> Dict[ConcreteActor, Direction]:
        """The side each actor is judged against for this encounter, fixed at its start.

        While the encounter runs the value is simply carried. Recomputing it per scene
        made it depend on which OTHER encounters the actor happened to be in at that
        moment: on a vessel give-way to two ships at once, the tie-break collapsed both
        to starboard, and when the first encounter ended 400 s later the second reverted
        to its own port direction and failed Rule 16 retroactively, against the very turn
        the monitor had demanded. Every successor died there and the search could not
        pass that step.

        A new encounter takes its own side unless the actor has already committed to the
        opposite one elsewhere. It cannot undo a turn it has already made, so the earlier
        commitment wins; without this the two sides would intersect to nothing in the
        suggestion sets and the branch would be pruned in silence.
        """
        situation_context = next_situation_context_set[relation]
        if not context_is_new:
            return dict(current_state.actors_avoidance_direction)

        directions: Dict[ConcreteActor, Direction] = {}
        for actor in situation_context.actors:
            own_direction = next_situation_context_set.resolved_avoidance_direction(relation, actor)
            committed = committed_avoidance_directions.get(actor)
            if committed is None or committed is Direction.FORWARD or own_direction is Direction.FORWARD:
                directions[actor] = own_direction
                continue
            directions[actor] = committed
        return directions

    @staticmethod
    def get_actors_have_been_in_right_maneuver(
        situation_context: SituationContext,
        current_state: COLREGSMonitorState,
        next_maneuver_state_set: ManeuverStateSet,
        context_is_new: bool = False,
    ) -> Dict[ConcreteActor, bool]:
        """Has each actor made a starboard course change DURING THIS encounter.

        The history is dropped when a new encounter begins. Carrying it across meant a
        momentary classification made long before the encounter existed counted as its
        give-way action, so GiveWayEarlyActionCondition believed the manoeuvre was
        already done and never asked the planner to turn.
        """
        return COLREGSStateMachine._accumulate_maneuver_flags(
            situation_context,
            current_state.actors_have_been_in_right_maneuver,
            next_maneuver_state_set,
            context_is_new,
            lambda maneuver_state: maneuver_state.is_course_change_to_the_right,
        )

    @staticmethod
    def get_actors_have_been_in_left_maneuver(
        situation_context: SituationContext,
        current_state: COLREGSMonitorState,
        next_maneuver_state_set: ManeuverStateSet,
        context_is_new: bool = False,
    ) -> Dict[ConcreteActor, bool]:
        return COLREGSStateMachine._accumulate_maneuver_flags(
            situation_context,
            current_state.actors_have_been_in_left_maneuver,
            next_maneuver_state_set,
            context_is_new,
            lambda maneuver_state: maneuver_state.is_course_change_to_the_left,
        )

    @staticmethod
    def _accumulate_maneuver_flags(
        situation_context: SituationContext,
        previous_flags: Dict[ConcreteActor, bool],
        next_maneuver_state_set: ManeuverStateSet,
        context_is_new: bool,
        is_matching_course_change: Callable[[ManeuverState], bool],
    ) -> Dict[ConcreteActor, bool]:
        flags: Dict[ConcreteActor, bool] = {}
        for actor in situation_context.actors:
            carried = False if context_is_new else previous_flags.get(actor, False)
            # Only vessels have a maneuver state; a static obstacle never maneuvers.
            if not actor.is_vessel:
                flags[actor] = carried
                continue
            flags[actor] = carried or is_matching_course_change(next_maneuver_state_set[Relation(actor, actor)])
        return flags
