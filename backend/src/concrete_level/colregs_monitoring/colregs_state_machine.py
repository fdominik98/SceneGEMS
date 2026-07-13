from typing import Dict

from concrete_level.colregs_monitoring.colregs_monitor_state import COLREGSMonitorState, COLREGSMonitorStateSet
from concrete_level.colregs_monitoring.maneuver import ManeuverStateSet
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredScene
from concrete_level.colregs_monitoring.situation_context import SituationContext, SituationContextSet
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation


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
                actors_have_been_in_right_maneuver=situation_context.actors_left_of_start_state,
                actors_have_been_in_left_maneuver=situation_context.actors_right_of_start_state,
                actors_passed_potential_collision_domain=situation_context.get_actors_passed_potential_collision_domain(initial_scene),
                actors_in_front_of_potential_collision_domain=situation_context.get_actors_in_front_of_potential_collision_domain(initial_scene),
                current_timestamp=situation_context.start_timestamp,
                time_spent_in_current_context=0,
            )
        actors_violate_safety_domain: Dict[ConcreteActor, bool] = {actor: situation_context.actors_violate_safety_domain for actor in situation_context_set.actors}
        return COLREGSMonitorStateSet(initial_monitor_state_set, actors_violate_safety_domain=actors_violate_safety_domain)

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
            actors_have_been_in_right_maneuver = COLREGSStateMachine.get_actors_have_been_in_right_maneuver(situation_context, current_state, next_maneuver_state_set)
            actors_have_been_in_left_maneuver = COLREGSStateMachine.get_actors_have_been_in_left_maneuver(situation_context, current_state, next_maneuver_state_set)
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
            )
        actors_violate_safety_domain: Dict[ConcreteActor, bool] = {actor: situation_context.actors_violate_safety_domain for actor in next_situation_context_set.actors}
        return COLREGSMonitorStateSet(next_monitor_state_set, actors_violate_safety_domain=actors_violate_safety_domain)

    @staticmethod
    def get_actors_have_been_in_right_maneuver(situation_context: SituationContext, current_state: COLREGSMonitorState, next_maneuver_state_set: ManeuverStateSet) -> Dict[ConcreteActor, bool]:
        actors_have_been_in_right_maneuver = {actor: current_state.actors_have_been_in_right_maneuver[actor] for actor in situation_context.actors}
        for actor in situation_context.actors:
            actors_have_been_in_right_maneuver[actor] = current_state.actors_have_been_in_right_maneuver[actor] or next_maneuver_state_set[Relation(actor, actor)].is_course_change_to_the_right
        return actors_have_been_in_right_maneuver

    @staticmethod
    def get_actors_have_been_in_left_maneuver(situation_context: SituationContext, current_state: COLREGSMonitorState, next_maneuver_state_set: ManeuverStateSet) -> Dict[ConcreteActor, bool]:
        actors_have_been_in_left_maneuver = {actor: current_state.actors_have_been_in_left_maneuver[actor] for actor in situation_context.actors}
        for actor in situation_context.actors:
            actors_have_been_in_left_maneuver[actor] = current_state.actors_have_been_in_left_maneuver[actor] or next_maneuver_state_set[Relation(actor, actor)].is_course_change_to_the_left
        return actors_have_been_in_left_maneuver
