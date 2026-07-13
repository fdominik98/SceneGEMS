import math
import random
from typing import Dict, Optional

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor, ConcreteStaticObstacle, ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from logical_level.constraint_satisfaction.assignments import Assignments
from logical_level.models.actor_variable import StaticObstacleVariable, VesselVariable
from logical_level.models.values import ObstacleValues, VesselValues

class SceneBuilder(Dict[ConcreteActor, ActorState]):
    def __init__(self, base_scene: Optional[ConcreteScene] = None, *args, **kwargs):
        # Initialize with an empty dict if no existing_dict is provided
        if base_scene is not None:
            existing_dict = base_scene._data.copy()
        else:
            existing_dict = {}
        self.base_scene = base_scene
        # Call the parent constructor with the provided data
        super().__init__(existing_dict, *args, **kwargs)

    def set_state(self, actor: ConcreteActor, state: ActorState) -> "SceneBuilder":
        self[actor] = state
        return self

    def set_states_as_dict(self, scene_dict: Dict[ConcreteActor, ActorState]) -> "SceneBuilder":
        for actor, state in scene_dict.items():
            self[actor] = state
        return self

    def merge(self, other: ConcreteScene) -> "SceneBuilder":
        for actor, state in other.items():
            self[actor] = state
        return self

    def remove_vessel(self, vessel: ConcreteVessel) -> "SceneBuilder":
        if vessel not in self:
            return self
        del self[vessel]
        return self

    def build(
        self,
        dcpa=None,
        tcpa=None,
        danger_sector=None,
        proximity_index=None,
        first_level_hash=None,
        second_level_hash=None,
        is_relevant_by_fec=None,
        is_relevant_by_fsm=None,
        is_ambiguous_by_fec=None,
        is_ambiguous_by_fsm=None,
    ) -> ConcreteScene:
        return ConcreteScene(
            self,
            **{
                key: value if value is not None else getattr(self.base_scene, key, None)
                for key, value in {
                    "dcpa": dcpa,
                    "tcpa": tcpa,
                    "danger_sector": danger_sector,
                    "proximity_index": proximity_index,
                    "first_level_hash": first_level_hash,
                    "second_level_hash": second_level_hash,
                    "is_relevant_by_fec": is_relevant_by_fec,
                    "is_relevant_by_fsm": is_relevant_by_fsm,
                    "is_ambiguous_by_fec": is_ambiguous_by_fec,
                    "is_ambiguous_by_fsm": is_ambiguous_by_fsm,
                }.items()
            },
        )

    @staticmethod
    def build_from_assignments(assignments: Assignments) -> ConcreteScene:
        builder = SceneBuilder()
        for actor_var, values in assignments.items():
            if isinstance(actor_var, VesselVariable) and isinstance(values, VesselValues):
                vessel_type = actor_var.vessel_type
                breadth = values.l * 0.4
                height = values.l * 0.15
                draft = height * 0.4
                
                """
                A rough naval architecture estimate is:
                displacement mass: Δ≈ρ * C_b * L * B * T
                Δ = displacement mass (kg)
                ρ = 1025 kg/m^3 for seawater
                C_b = block coefficient
                slender vessels: 0.35 - 0.5
                typical ships: 0.6 - 0.8
                L = length (m)
                B = breadth (m)
                T = draft (m)
                """
                block_coefficient = 0.6
                total_mass = 1025 * block_coefficient * values.l * breadth * draft
                # rudder_mass = mass * 0.01
                rudder_mass = 0.0
                r_l, r_b, r_h = values.l * 0.02, 0.1, height * 0.8
                thruster_mass = total_mass * 0.001
                mass = total_mass - 2 * thruster_mass
                prop_diameter = draft * 0.6
                motor_length = prop_diameter * 1.5
                
                builder.set_state(
                    ConcreteVessel(
                        id=actor_var.id,
                        type=vessel_type.name,
                        length=values.l,
                        breadth=breadth,
                        height=height,
                        draft=draft,
                        safety_radius=values.r,
                        _is_os=actor_var.is_os,
                        _rudder_mass=rudder_mass,
                        _rudder_length=r_l,
                        _rudder_width=r_b,
                        _rudder_height=r_h,
                        _propeller_diameter=prop_diameter,
                        _thruster_mass=thruster_mass,
                        _motor_length=motor_length,
                        _max_speed=vessel_type.max_speed,
                        _max_angular_speed=vessel_type.max_angular_speed,
                        _max_acceleration=vessel_type.max_acceleration,
                        mass=mass,
                    ),
                    ActorState(x=values.x, y=values.y, speed=values.sp, heading=values.h),
                )
            elif isinstance(actor_var, StaticObstacleVariable) and isinstance(values, ObstacleValues):
                obstacle_type = actor_var.obstacle_type
                mass = 5.6 * pow(values.l, 3)
                height = values.l * 0.1
                draft = height * 0.4
                builder.set_state(
                    ConcreteStaticObstacle(id=actor_var.id, type=obstacle_type.name, length=values.l, breadth=values.l, height=height, draft=draft, mass=mass, safety_radius=values.r),
                    ActorState(x=values.x, y=values.y, speed=0, heading=0),
                )
            else:
                raise TypeError("Unsupported Actor")
        return builder.build()
    