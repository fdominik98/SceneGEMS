from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, List, Tuple

from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from utils.colregs_approximations import COLREGSConstraints
from utils.math_utils import Direction, relative_heading_direction
from utils.safety_domains import SafetyDomain


class COLREGSType(Enum):
    OVERTAKING_TO_PORT = auto()  # v1 is in the stern sector of v2; v2 is in the port side sector of v1
    OVERTAKING_TO_STARBOARD = auto()  # v1 is in the stern sector of v2; v2 is in the starboard side sector of v1
    CROSSING_FROM_PORT = auto()  # v1 is in the port side sector of v2; v2 is in the starboard side sector of v1
    HEAD_ON = auto()  # v1 is in the head-on sector of v2; v2 is in the head-on sector of v1
    TWO_WAY_CROSSING_FROM_PORT = auto()  # v1 is in the port side sector of v2; v2 is in the port side sector of v1
    TWO_WAY_CROSSING_FROM_STARBOARD = auto()  # v1 is in the starboard side sector of v2; v2 is in the starboard side sector of v1
    OTHER = auto()  # other situation

    @property
    def custom_name(self) -> str:
        custom_names = {
            COLREGSType.OVERTAKING_TO_PORT: "Overtaking to Port",
            COLREGSType.OVERTAKING_TO_STARBOARD: "Overtaking to Starboard",
            COLREGSType.CROSSING_FROM_PORT: "Crossing from Port",
            COLREGSType.HEAD_ON: "Head-On",
            COLREGSType.TWO_WAY_CROSSING_FROM_PORT: "Two Way Crossing from Port",
            COLREGSType.TWO_WAY_CROSSING_FROM_STARBOARD: "Two Way Crossing from Starboard",
            COLREGSType.OTHER: "Other",
        }
        return custom_names[self]


class SituationContext(ABC):
    def __init__(
        self,
        situation_type: COLREGSType,
        actor1: ConcreteActor,
        actor2: ConcreteActor,
        start_scene: ConcreteScene,
        start_timestamp: int,
        colregs_constants: COLREGSConstraints,
    ):
        self.colregs_constants = colregs_constants
        self.situation_type = situation_type
        self.actor1 = actor1
        self.actor2 = actor2
        self.relation = Relation.canonical(actor1, actor2)
        self.start_scene = start_scene
        self.start_timestamp = start_timestamp
        self.actors_on_collision_course = self.get_actors_on_collision_course(start_scene)
        self.actors_have_low_tcpa = self.get_actors_have_low_tcpa(start_scene)
        self.actors_see_each_other = self.get_actors_see_each_other(start_scene)
        self.actors_passed_each_other = self.get_actors_passed_each_other(start_scene)
        self.actors_violate_safety_domain = self.get_actors_violate_safety_domain(start_scene)
        self.actors_right_of_start_state = self.get_actors_right_of_start_state(start_scene)
        self.actors_left_of_start_state = self.get_actors_left_of_start_state(start_scene)
        domain1, domain2 = start_scene.potential_safety_domains(actor1, actor2)
        self.start_potential_collision_domains = {actor1: domain1, actor2: domain2}

    def __str__(self):
        return f"{self.situation_type} - {self.actor1} - {self.actor2}"

    def __repr__(self):
        return str(self)

    @abstractmethod
    def get_safety_domains(self, scene: ConcreteScene) -> Tuple[SafetyDomain, SafetyDomain]:
        pass

    def get_actors_violate_safety_domain(self, scene: ConcreteScene) -> bool:
        os_safety_domain, ts_safety_domain = self.get_safety_domains(scene)
        return os_safety_domain.contains_point(scene[self.actor2].p) or ts_safety_domain.contains_point(scene[self.actor1].p)

    def get_actors_passed_each_other(self, current_scene: ConcreteScene) -> bool:
        return (self._get_actors_passed_each_other_condition(current_scene) and
                current_scene.get_tcpa(self.actor2, self.actor1) < 0)
    
    @abstractmethod
    def _get_actors_passed_each_other_condition(self, current_scene: ConcreteScene) -> bool:
        pass

    def get_actors_see_each_other(self, scene: ConcreteScene) -> bool:
        return not scene.out_of_visibility_distance(self.actor2, self.actor1)

    def get_actors_on_collision_course(self, scene: ConcreteScene) -> bool:
        return scene.on_collision_course(self.actor2, self.actor1)

    def get_actors_have_low_tcpa(self, scene: ConcreteScene) -> bool:
        return scene.low_tcpa(self.actor2, self.actor1, self.colregs_constants)

    @abstractmethod
    def is_give_way_actor(self, actor: ConcreteActor) -> bool:
        pass

    @abstractmethod
    def is_stand_on_actor(self, actor: ConcreteActor) -> bool:
        pass

    @abstractmethod
    def avoidance_direction(self, actor: ConcreteActor) -> Direction:
        pass

    @property
    def actors(self) -> List[ConcreteActor]:
        return [self.actor1, self.actor2]

    def get_actors_passed_potential_collision_domain(self, scene: ConcreteScene) -> Dict[ConcreteActor, bool]:
        return {
            self.actor1: self.start_potential_collision_domains[self.actor1].has_passed(scene[self.actor1]),
            self.actor2: self.start_potential_collision_domains[self.actor2].has_passed(scene[self.actor2]),
        }

    def get_actors_in_front_of_potential_collision_domain(self, scene: ConcreteScene) -> Dict[ConcreteActor, bool]:
        return {
            self.actor1: self.start_potential_collision_domains[self.actor1].in_front_of(scene[self.actor1]),
            self.actor2: self.start_potential_collision_domains[self.actor2].in_front_of(scene[self.actor2]),
        }

    def get_actors_right_of_start_state(self, next_scene: ConcreteScene) -> Dict[ConcreteActor, bool]:
        return {
            self.actor1: next_scene[self.actor1].right_of(self.start_scene[self.actor1]),
            self.actor2: next_scene[self.actor2].right_of(self.start_scene[self.actor2]),
        }

    def get_actors_left_of_start_state(self, next_scene: ConcreteScene) -> Dict[ConcreteActor, bool]:
        return {
            self.actor1: next_scene[self.actor1].left_of(self.start_scene[self.actor1]),
            self.actor2: next_scene[self.actor2].left_of(self.start_scene[self.actor2]),
        }


class HeadOnSituationContext(SituationContext):
    def __init__(self, vessel1: ConcreteActor, vessel2: ConcreteActor, start_scene: ConcreteScene, start_timestamp: int, colregs_constants: COLREGSConstraints):
        super().__init__(COLREGSType.HEAD_ON, vessel1, vessel2, start_scene, start_timestamp, colregs_constants)

    def avoidance_direction(self, actor: ConcreteActor) -> Direction:
        return Direction.RIGHT

    def get_safety_domains(self, scene: ConcreteScene) -> Tuple[SafetyDomain, SafetyDomain]:
        return (
            self.actor1.get_head_on_safety_domain(scene[self.actor1]),
            self.actor2.get_head_on_safety_domain(scene[self.actor2]),
        )

    def _get_actors_passed_each_other_condition(self, current_scene: ConcreteScene) -> bool:
        return current_scene[self.actor1].behind(current_scene[self.actor2]) and current_scene[self.actor2].behind(current_scene[self.actor1])

    def is_give_way_actor(self, actor: ConcreteActor) -> bool:
        return self.actor1 == actor or self.actor2 == actor

    def is_stand_on_actor(self, actor: ConcreteActor) -> bool:
        return False


class OvertakingSituationContext(SituationContext):
    def __init__(self, vessel1: ConcreteActor, vessel2: ConcreteActor, start_scene: ConcreteScene, start_timestamp: int, colregs_constants: COLREGSConstraints):
        if start_scene.in_overtaking_to_port_cr(vessel1, vessel2, colregs_constants):
            situation_type = COLREGSType.OVERTAKING_TO_PORT
        elif start_scene.in_overtaking_to_starboard_cr(vessel1, vessel2, colregs_constants):
            situation_type = COLREGSType.OVERTAKING_TO_STARBOARD
        else:
            raise ValueError(f"Invalid overtaking situation: {start_scene.in_overtaking_cr(vessel1, vessel2, colregs_constants)}")
        super().__init__(situation_type, vessel1, vessel2, start_scene, start_timestamp, colregs_constants)

        # if actor2 is facing right of the collision domain of actor1 then left else right
        actor2_relative_heading_to_collision_domain = relative_heading_direction(self.start_scene[self.actor2].heading, self.start_potential_collision_domains[self.actor1].heading)

        self.avoidance_directions = {
            self.actor1: Direction.LEFT if actor2_relative_heading_to_collision_domain == Direction.RIGHT else Direction.RIGHT,
            self.actor2: Direction.FORWARD,
        }

    def avoidance_direction(self, actor: ConcreteActor) -> Direction:
        return self.avoidance_directions[actor]

    def get_safety_domains(self, scene: ConcreteScene) -> Tuple[SafetyDomain, SafetyDomain]:
        return (
            self.actor1.get_overtaking_safety_domain(scene[self.actor1]),
            self.actor2.get_default_safety_domain(scene[self.actor2]),
        )

    def _get_actors_passed_each_other_condition(self, current_scene: ConcreteScene) -> bool:
        return current_scene[self.actor1].in_front_of(current_scene[self.actor2]) and current_scene[self.actor2].behind(current_scene[self.actor1])

    def is_give_way_actor(self, actor: ConcreteActor) -> bool:
        return self.actor1 == actor

    def is_stand_on_actor(self, actor: ConcreteActor) -> bool:
        return self.actor2 == actor


class CrossingFromPortSituationContext(SituationContext):
    def __init__(self, vessel1: ConcreteActor, vessel2: ConcreteActor, start_scene: ConcreteScene, start_timestamp: int, colregs_constants: COLREGSConstraints):
        super().__init__(COLREGSType.CROSSING_FROM_PORT, vessel1, vessel2, start_scene, start_timestamp, colregs_constants)

        self.avoidance_directions = {
            self.actor1: Direction.RIGHT,
            self.actor2: Direction.FORWARD,
        }

    def avoidance_direction(self, actor: ConcreteActor) -> Direction:
        return self.avoidance_directions[actor]

    def get_safety_domains(self, scene: ConcreteScene) -> Tuple[SafetyDomain, SafetyDomain]:
        return (
            self.actor1.get_crossing_from_port_safety_domain(scene[self.actor1]),
            self.actor2.get_default_safety_domain(scene[self.actor2]),
        )

    def _get_actors_passed_each_other_condition(self, current_scene: ConcreteScene) -> bool:
        return current_scene[self.actor1].right_of(current_scene[self.actor2]) and current_scene[self.actor1].behind(current_scene[self.actor2])

    def is_give_way_actor(self, actor: ConcreteActor) -> bool:
        return self.actor1 == actor

    def is_stand_on_actor(self, actor: ConcreteActor) -> bool:
        return self.actor2 == actor


class TwoWayCrossingFromPortSituationContext(SituationContext):
    def __init__(self, vessel1: ConcreteActor, vessel2: ConcreteActor, start_scene: ConcreteScene, start_timestamp: int, colregs_constants: COLREGSConstraints):
        super().__init__(COLREGSType.TWO_WAY_CROSSING_FROM_PORT, vessel1, vessel2, start_scene, start_timestamp, colregs_constants)

    def avoidance_direction(self, actor: ConcreteActor) -> Direction:
        return Direction.RIGHT

    def get_safety_domains(self, scene: ConcreteScene) -> Tuple[SafetyDomain, SafetyDomain]:
        return (
            self.actor1.get_crossing_from_port_safety_domain(scene[self.actor1]),
            self.actor2.get_crossing_from_port_safety_domain(scene[self.actor2]),
        )

    def is_give_way_actor(self, actor: ConcreteActor) -> bool:
        return self.actor1 == actor or self.actor2 == actor

    def is_stand_on_actor(self, actor: ConcreteActor) -> bool:
        return False

    def _get_actors_passed_each_other_condition(self, current_scene: ConcreteScene) -> bool:
        return current_scene[self.actor1].behind(current_scene[self.actor2]) and current_scene[self.actor2].behind(current_scene[self.actor1])


class TwoWayCrossingFromStarboardSituationContext(SituationContext):
    def __init__(self, vessel1: ConcreteActor, vessel2: ConcreteActor, start_scene: ConcreteScene, start_timestamp: int, colregs_constants: COLREGSConstraints):
        super().__init__(COLREGSType.TWO_WAY_CROSSING_FROM_STARBOARD, vessel1, vessel2, start_scene, start_timestamp, colregs_constants)

    def avoidance_direction(self, actor: ConcreteActor) -> Direction:
        return Direction.LEFT

    def get_safety_domains(self, scene: ConcreteScene) -> Tuple[SafetyDomain, SafetyDomain]:
        return (
            self.actor1.get_crossing_from_starboard_safety_domain(scene[self.actor1]),
            self.actor2.get_crossing_from_starboard_safety_domain(scene[self.actor2]),
        )

    def is_give_way_actor(self, actor: ConcreteActor) -> bool:
        return self.actor1 == actor or self.actor2 == actor

    def is_stand_on_actor(self, actor: ConcreteActor) -> bool:
        return False

    def _get_actors_passed_each_other_condition(self, current_scene: ConcreteScene) -> bool:
        return current_scene[self.actor1].behind(current_scene[self.actor2]) and current_scene[self.actor2].behind(current_scene[self.actor1])


class OtherSituationContext(SituationContext):
    def __init__(self, actor1: ConcreteActor, actor2: ConcreteActor, start_scene: ConcreteScene, start_timestamp: int, colregs_constants: COLREGSConstraints):
        super().__init__(COLREGSType.OTHER, actor1, actor2, start_scene, start_timestamp, colregs_constants)

    def get_safety_domains(self, scene: ConcreteScene) -> Tuple[SafetyDomain, SafetyDomain]:
        return (
            self.actor1.get_default_safety_domain(scene[self.actor1]),
            self.actor2.get_default_safety_domain(scene[self.actor2]),
        )

    def _get_actors_passed_each_other_condition(self, current_scene: ConcreteScene) -> bool:
        return True

    def is_give_way_actor(self, actor: ConcreteActor) -> bool:
        return False

    def is_stand_on_actor(self, actor: ConcreteActor) -> bool:
        return self.actor1 == actor or self.actor2 == actor

    def avoidance_direction(self, actor: ConcreteActor) -> Direction:
        return {self.actor1: Direction.FORWARD, self.actor2: Direction.FORWARD}[actor]


@dataclass(frozen=False)
class SituationContextSet(Dict[Relation, SituationContext]):
    def __init__(self, situation_contexts: Dict[Relation, SituationContext], actors_have_to_give_way: Dict[ConcreteActor, bool], actors_avoidance_directions: Dict[ConcreteActor, Direction]):
        super().__init__(situation_contexts)
        self.actors_have_to_give_way = actors_have_to_give_way
        self.actors_avoidance_directions = actors_avoidance_directions

    def actor_has_to_give_way(self, actor: ConcreteActor) -> bool:
        return self.actors_have_to_give_way.get(actor, False)

    def actor_avoidance_direction(self, actor: ConcreteActor) -> Direction:
        return self.actors_avoidance_directions.get(actor, Direction.FORWARD)

    @property
    def actors(self) -> List[ConcreteActor]:
        return list(set([context.actor1 for context in self.values()] + [context.actor2 for context in self.values()]))

    @property
    def relations(self) -> List[Relation]:
        return list(self.keys())

    @staticmethod
    def get_actor_has_to_give_way(actor: ConcreteActor, situation_context_set: Dict[Relation, SituationContext]) -> bool:
        return any(actor in relation and situation_context.is_give_way_actor(actor) for relation, situation_context in situation_context_set.items())

    @staticmethod
    def get_actor_avoidance_direction(actor: ConcreteActor, situation_context_set: Dict[Relation, SituationContext]) -> Direction:
        avoidance_directions = {situation_context.avoidance_direction(actor) for relation, situation_context in situation_context_set.items() if actor in relation}
        if Direction.RIGHT in avoidance_directions:
            return Direction.RIGHT

        if Direction.LEFT in avoidance_directions:
            return Direction.LEFT

        return Direction.FORWARD
