from dataclasses import dataclass
from typing import Dict

from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.relation import Relation


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


class COLREGSMonitorStateSet(Dict[Relation, COLREGSMonitorState]):
    def __init__(self, monitor_state_dict: Dict[Relation, COLREGSMonitorState], actors_violate_safety_domain: Dict[ConcreteActor, bool]):
        super().__init__(monitor_state_dict)
        self.actors_violate_safety_domain = actors_violate_safety_domain

    def actor_violates_safety_domain(self, actor: ConcreteActor) -> bool:
        return self.actors_violate_safety_domain.get(actor, False)
