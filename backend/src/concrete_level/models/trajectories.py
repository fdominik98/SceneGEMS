from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type

import numpy as np

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from utils.math_utils import find_center_and_radius
from utils.safety_domains import CircularSafetyDomain, SafetyDomain
from utils.serializable import Serializable


@dataclass(frozen=True)
class Trajectories(Serializable):
    scene_list: List[ConcreteScene]
    time_step: int

    def state_list(self, actor: ConcreteActor) -> List[ActorState]:
        return [scene[actor] for scene in self.scene_list]

    def get_state_by_time(self, actor: ConcreteActor, t: int) -> ActorState:
        return self.get_scene_by_time(t)[actor]

    def get_scene_by_time(self, t: int) -> ConcreteScene:
        """
        Returns the scene at the given time.
        :param t: The time to get the scene at.
        :return: The scene at the given time.
        """
        return self.scene_list[t // self.time_step]

    def __len__(self):
        return len(self.scene_list)

    def __iter__(self):
        return iter(self.scene_list)

    def __repr__(self):
        return f"{self.__class__.__name__}(time_step={self.time_step}, trajectory={self.scene_list})"

    @property
    def timespan(self) -> int:
        return (len(self) - 1) * self.time_step

    @property
    def initial_scene(self) -> ConcreteScene:
        return self.scene_list[0]

    @property
    def last_scene(self) -> ConcreteScene:
        return self.scene_list[-1]

    def potential_collision_domain(self, vessel: ConcreteVessel) -> Optional[SafetyDomain]:
        max_radius = 0.0
        collision_points: List[np.ndarray] = []
        for scene in self.scene_list:
            # iterate over all vessels in the scene except the vessel
            for vessel2 in scene.vessels:
                if vessel2 is vessel:
                    continue
                sd1 = vessel.get_default_safety_domain(scene[vessel])
                sd2 = vessel2.get_default_safety_domain(scene[vessel2])
                if sd1.contains_point(scene[vessel2].p) or sd2.contains_point(scene[vessel].p):
                    collision_points += [scene[vessel].p, scene[vessel2].p]
                    max_radius = max(max_radius, vessel2.safety_radius)

        if len(collision_points) == 0:
            return None

        center, radius = find_center_and_radius(collision_points)
        radius += vessel.safety_radius + max_radius
        return CircularSafetyDomain(center, self.initial_scene[vessel].heading, radius)

    def to_dict(self):
        result = {}
        for key, value in self.__dict__.items():
            if key == "scene_list":
                result[key] = [scene.to_dict() for scene in self.scene_list]
            else:  # Handle primitive types
                result[key] = value
        return result

    @classmethod
    def from_dict(cls: Type["Trajectories"], data: Dict[str, Any]) -> "Trajectories":
        copy_data = data.copy()
        for attr, value in data.items():
            if attr == "scene_list":
                copy_data[attr] = [ConcreteScene.from_dict(scene) for scene in value]
        return Trajectories(**copy_data)

    @property
    def actors(self) -> List[ConcreteActor]:
        if len(self) == 0:
            return []
        return list(self.initial_scene.actors)

    @property
    def actor_state_dict(self) -> Dict[ConcreteActor, List[ActorState]]:
        return {actor: self.actor_states(actor) for actor in self.actors}

    def actor_states(self, actor: ConcreteActor, start_index: int = 0, end_index: Optional[int] = None) -> List[ActorState]:
        if end_index is None or end_index > len(self):
            end_index = len(self)
        return [scene[actor] for scene in self.scene_list[start_index:end_index]]

    def get_chunk_timespan(self, start_index: int, end_index: Optional[int] = None) -> float:
        if end_index is None:
            end_index = len(self)
        return (end_index - start_index) * self.time_step
    
    def get_max_speed(self, actor: ConcreteActor) -> float:
        return max(scene[actor].speed for scene in self.scene_list)
    