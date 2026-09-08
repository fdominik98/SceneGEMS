from dataclasses import dataclass
from typing import Dict

from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation
from utils.math_utils import Direction


@dataclass(frozen=False)
class COLREGSMonitorState:
    actors_see_each_other: bool
    actors_passed_each_other: bool
    actors_right_of_start_state: Dict[ConcreteActor, bool]
    actors_left_of_start_state: Dict[ConcreteActor, bool]
    actors_have_been_in_right_maneuver: Dict[ConcreteActor, bool]
    actors_have_been_in_left_maneuver: Dict[ConcreteActor, bool]
    actors_passed_potential_collision_domain: Dict[ConcreteActor, bool]
    actors_in_front_of_potential_collision_domain: Dict[ConcreteActor, bool]
    actors_violate_safety_domain: bool
    actors_on_collision_course: bool
    actors_have_low_tcpa: bool
    current_timestamp: int
    time_spent_in_current_context: int
    # Continuous-valued companions of actors_violate_safety_domain. `clearance` is the
    # signed distance to a domain violation at this scene (negative when violating);
    # `min_step_clearance` is the smallest value reached anywhere inside the step that
    # led here, which is what catches a relative motion tunnelling through the domain.
    actors_clearance: Dict[ConcreteActor, float]
    actors_side_offset: Dict[ConcreteActor, float]
    min_step_clearance: float
    # The side each actor is being judged against for THIS encounter, decided once when
    # the encounter begins and carried unchanged for as long as it lasts. It cannot be
    # recomputed per scene: the value depends on which OTHER encounters the actor is in,
    # so an unrelated encounter ending would change it, and the vessel would then be
    # judged against a side opposite to the alteration the monitor itself demanded of it.
    actors_avoidance_direction: Dict[ConcreteActor, Direction]


class COLREGSMonitorStateSet(Dict[Relation, COLREGSMonitorState]):
    def __init__(self, monitor_state_dict: Dict[Relation, COLREGSMonitorState], actors_violate_safety_domain: Dict[ConcreteActor, bool]):
        super().__init__(monitor_state_dict)
        self.actors_violate_safety_domain = actors_violate_safety_domain

    def actor_violates_safety_domain(self, actor: ConcreteActor) -> bool:
        return self.actors_violate_safety_domain.get(actor, False)

    @staticmethod
    def collect_actors_violate_safety_domain(monitor_state_dict: Dict[Relation, COLREGSMonitorState]) -> Dict[ConcreteActor, bool]:
        """An actor violates a safety domain if ANY of its relations does.

        This used to read a leaked for-loop variable, so every actor was given the last
        relation's verdict, taken from the encounter's start scene rather than the scene
        being evaluated.
        """
        actors_violate: Dict[ConcreteActor, bool] = {}
        for relation, state in monitor_state_dict.items():
            for actor in relation:
                actors_violate[actor] = actors_violate.get(actor, False) or state.actors_violate_safety_domain
        return actors_violate
