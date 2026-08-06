import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Tuple, Type

import numpy as np

from concrete_level.models.actor_state import ActorState
from functional_level.metamodels.functional_object import FuncObject
from functional_level.models.functional_scenario_builder import FunctionalScenarioBuilder
from logical_level.mapping.static_obstacle import StaticObstacleType
from logical_level.mapping.vessel_type import VesselType
from logical_level.models.actor_variable import ActorVariable, OSVariable, StaticObstacleVariable, TSVariable, VesselVariable
from utils.global_constants import EPSILON, PHANTOM_SHIP_ANGLE
from utils.math_utils import abs_heading_diff, calculate_heading, distance, heading_diff, rotate_heading
from utils.safety_domains import CircularSafetyDomain, EllipticalSafetyDomain, SafetyDomain
from utils.serializable import Serializable


@dataclass(frozen=True)
class ConcreteActor(Serializable, ABC):
    id: int
    type: str
    length: float
    breadth: float
    height: float
    draft: float
    mass: float
    safety_radius: float

    is_vessel: bool = field(default=False, init=False)

    @classmethod
    def from_dict(cls: Type["ConcreteActor"], data: Dict[str, Any]) -> "ConcreteActor":
        new_data = {k: v for k, v in data.items() if k != "is_vessel"}
        if data["is_vessel"]:
            return ConcreteVessel.from_dict(new_data)
        return ConcreteStaticObstacle.from_dict(new_data)

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def max_speed(self) -> float:
        pass

    @property
    @abstractmethod
    def max_angular_speed(self) -> float:
        pass

    @property
    @abstractmethod
    def max_acceleration(self) -> float:
        pass

    @property
    @abstractmethod
    def is_os(self) -> bool:
        pass

    @property
    @abstractmethod
    def logical_variable(self) -> ActorVariable:
        pass

    def __repr__(self):
        return self.name

    def get_default_safety_domain(self, state: ActorState) -> CircularSafetyDomain:
        return CircularSafetyDomain(state.p, state.heading, self.safety_radius)

    @abstractmethod
    def get_overtaking_safety_domain(self, state: ActorState) -> SafetyDomain:
        pass

    @abstractmethod
    def get_crossing_from_port_safety_domain(self, state: ActorState) -> SafetyDomain:
        pass

    @abstractmethod
    def get_crossing_from_starboard_safety_domain(self, state: ActorState) -> SafetyDomain:
        pass

    @abstractmethod
    def get_head_on_safety_domain(self, state: ActorState) -> SafetyDomain:
        pass

    @abstractmethod
    def simulate(self, state: ActorState, u_ref: Tuple[float, float], dt: float) -> ActorState:
        pass

    @abstractmethod
    def simulate_to_state(self, state: ActorState, target_state: ActorState, dt: float, max_steps: int = 500) -> list[ActorState]:
        pass
    
    @abstractmethod
    def get_max_heading_step(self, dt: float) -> float:
        pass

    @abstractmethod
    def get_max_speed_step(self, dt: float) -> float:
        pass

    @abstractmethod
    def simulate_distance(self, state: ActorState, distance: float) -> ActorState:
        pass

    def distance_made(self, state: ActorState, u_ref: Tuple[float, float], dt: float) -> float:
        return distance(self.simulate(state, u_ref, dt).p, state.p)


@dataclass(frozen=True)
class ConcreteStaticObstacle(ConcreteActor):
    def __post_init__(self):
        object.__setattr__(self, "is_vessel", False)

    @property
    def name(self) -> str:
        return f"SO_{self.id}"

    @property
    def is_os(self) -> bool:
        return False

    @property
    def max_speed(self) -> float:
        return 0.0

    @property
    def max_angular_speed(self) -> float:
        return 0.0

    @property
    def max_acceleration(self) -> float:
        return 0.0
    
    @property
    def obstacle_type(self) -> StaticObstacleType:
        return StaticObstacleType(self.type,
                          min_radius=self.length,
                          max_radius=self.length)

    @property
    def logical_variable(self) -> "StaticObstacleVariable":
        t = self.obstacle_type
        return StaticObstacleVariable(self.id, t)

    def simulate(self, state: ActorState, u_ref: Tuple[float, float], dt: float) -> ActorState:
        return state

    def simulate_to_state(self, state: ActorState, target_state: ActorState, dt: float, max_steps: int = 500) -> list[ActorState]:
        return [state]

    @classmethod
    def from_dict(cls: Type["ConcreteStaticObstacle"], data: Dict[str, Any]) -> "ConcreteStaticObstacle":
        return ConcreteStaticObstacle(**data)

    def get_overtaking_safety_domain(self, state: ActorState) -> SafetyDomain:
        return self.get_default_safety_domain(state)

    def get_crossing_from_port_safety_domain(self, state: ActorState) -> SafetyDomain:
        return self.get_default_safety_domain(state)

    def get_crossing_from_starboard_safety_domain(self, state: ActorState) -> SafetyDomain:
        return self.get_default_safety_domain(state)

    def get_head_on_safety_domain(self, state: ActorState) -> SafetyDomain:
        return self.get_default_safety_domain(state)

    def get_max_heading_step(self, dt: float) -> float:
        return 0.0

    def get_max_speed_step(self, dt: float) -> float:
        return 0.0

    def simulate_distance(self, state: ActorState, distance: float) -> ActorState:
        return state


@dataclass(frozen=True)
class ConcreteVessel(ConcreteActor):
    _is_os: bool
    _max_speed: float
    _max_angular_speed: float
    _max_acceleration: float
    
    _rudder_mass: float
    _rudder_length: float
    _rudder_width: float
    _rudder_height: float
    
    _propeller_diameter: float
    _thruster_mass: float
    _motor_length: float

    def __post_init__(self):
        object.__setattr__(self, "is_vessel", True)

    @property
    def name(self) -> str:
        return f"OS_{self.id}" if self.is_os else f"TS_{self.id}"

    @property
    def is_os(self) -> bool:
        return self._is_os
    
    @property
    def propeller_diameter(self) -> float:
        return self._propeller_diameter
    
    @property
    def motor_length(self) -> float:
        return self._motor_length
    
    @property
    def rudder_mass(self) -> float:
        return self._rudder_mass
    
    @property
    def rudder_length(self) -> float:
        return self._rudder_length
    
    @property
    def rudder_width(self) -> float:
        return self._rudder_width
    
    @property
    def rudder_height(self) -> float:
        return self._rudder_height
    
    @property
    def thruster_mass(self) -> float:
        return self._thruster_mass
    
    @property
    def visible_height(self) -> float:
        return self.height - self.draft
    
    @property
    def max_speed(self) -> float:
        return self._max_speed

    @property
    def max_angular_speed(self) -> float:
        return self._max_angular_speed

    @property
    def max_acceleration(self) -> float:
        return self._max_acceleration
    
    @property
    def waypoint_radius(self) -> float:
        return self.length * 4.0
    
    # source: https://doi.org/10.1007/s10846-025-02222-7
    def simulate(self, state: ActorState, u_ref: Tuple[float, float], dt: float) -> ActorState:
        """
        Propagate the vessel one time-step using simple kinematics with
        rate/acceleration limits derived from the vessel attributes.

        Args:
            state: ActorState(x, y, speed, heading) -- current state
            u_ref: (heading_ref, speed_ref) -- guidance references
            dt: time_step in seconds

        Returns:
            ActorState(x_new, y_new, speed_new, heading_new)
        """
        x, y, heading, speed = state.x, state.y, state.heading, state.speed
        heading_ref, speed_ref = u_ref

        # 1) Heading slew limited by max_turning_angle (interpreted as max yaw rate [rad/s])
        max_heading_step = self.get_max_heading_step(dt)
        # Use math utils to compute heading error (already handles wrapping to [-pi, pi])
        heading_error = heading_diff(heading_ref, heading)
        heading_step = np.clip(heading_error, -max_heading_step, max_heading_step)
        # Use math utils to add heading step (automatically normalizes to [-pi, pi])
        heading_new = rotate_heading(heading_step, heading)

        # 2) Speed change limited by max_acceleration [m/s^2]
        max_speed_step = self.get_max_speed_step(dt)
        speed_error = speed_ref - speed
        speed_step = np.clip(speed_error, -max_speed_step, max_speed_step)
        speed_new = speed + speed_step
        speed_new = np.clip(speed_new, 0.0, self.max_speed)

        # --- 3) Form velocity vectors (inertial frame)
        v_new = np.array([np.cos(heading_new), np.sin(heading_new)]) * speed_new  # new inertial velocity

        # --- 4) Position update using average velocity (trapezoidal rule)
        v_avg = 0.5 * (state.v + v_new)
        x_new = x + v_avg[0] * dt
        y_new = y + v_avg[1] * dt

        return ActorState(x=x_new, y=y_new, speed=speed_new, heading=heading_new)

    def simulate_to_state(
        self,
        state: ActorState,
        target_state: ActorState,
        dt: float,
        max_steps: int = 500
    ) -> list[ActorState]:

        trajectory = [state]
        current = state

        for _ in range(max_steps):
            pos_error = target_state.p - current.p
            dist = np.linalg.norm(pos_error)

            # --- termination ---
            if dist < EPSILON and \
            abs(target_state.speed - current.speed) < EPSILON and \
            abs(heading_diff(target_state.heading, current.heading)) < EPSILON:
                break

            # --- heading control ---
            if dist > self.safety_radius:
                heading_ref = calculate_heading(pos_error)
            else:
                heading_ref = target_state.heading

            # --- speed control (physics-based) ---
            v0 = current.speed
            vf = target_state.speed

            if self.max_acceleration > 0 and dist > EPSILON:
                # required acceleration to hit position AND final speed
                a_req = (vf**2 - v0**2) / (2 * dist)

                # clamp to feasible limits
                a = np.clip(a_req, -self.max_acceleration, self.max_acceleration)

                # convert to speed reference
                speed_ref = v0 + a * dt
            else:
                # edge case: no acceleration -> cannot adjust speed
                speed_ref = v0

            # clamp to valid range
            speed_ref = np.clip(speed_ref, 0.0, self.max_speed)

            # --- simulate step ---
            next_state = self.simulate(current, (heading_ref, speed_ref), dt)

            # --- overshoot detection (important for discrete integration) ---
            new_dist = np.linalg.norm(target_state.p - next_state.p)

            if new_dist > dist:
                break

            trajectory.append(next_state)
            current = next_state

        return trajectory

    def get_max_speed_step(self, dt: float) -> float:
        return self.max_acceleration * dt

    def get_max_heading_step(self, dt: float) -> float:
        return min(self.max_angular_speed * dt, np.pi)

    def sample_random_heading(self, state: ActorState, h_ref: float, dt: float):
        max_heading_change = self.get_max_heading_step(dt)
        heading_change = heading_diff(h_ref, state.heading)
        heading_change = np.clip(heading_change, -max_heading_change, max_heading_change)
        heading_change = np.sign(heading_change) * random.uniform(0, abs(max_heading_change))
        return rotate_heading(state.heading, heading_change)

    def simulate_distance(self, state: ActorState, distance: float) -> ActorState:
        return self.simulate(state, (state.heading, state.speed), distance / state.speed)


    @property
    def vessel_type(self) -> VesselType:
        return VesselType(name=self.type,
                          min_length=self.length,
                          max_length=self.length,
                          min_beam=self.breadth,
                          max_beam=self.breadth,
                          max_speed=self.max_speed,
                          max_angular_speed=self.max_angular_speed,
                          max_acceleration=self.max_acceleration)

    @property
    def logical_variable(self) -> VesselVariable:
        t = self.vessel_type
        return OSVariable(self.id, t) if self.is_os else TSVariable(self.id, t)
    
    @classmethod
    def from_dict(cls: Type["ConcreteVessel"], data: Dict[str, Any]) -> "ConcreteVessel":
        return ConcreteVessel(**data)

    def get_overtaking_safety_domain(self, state: ActorState) -> SafetyDomain:
        a = self.length * 5
        b = self.length * 4
        return EllipticalSafetyDomain(state.p, state.heading, a, b).shift(a / 4, state.heading)

    def get_crossing_from_port_safety_domain(self, state: ActorState) -> SafetyDomain:
        shift_direction = rotate_heading(state.heading, -PHANTOM_SHIP_ANGLE)
        return CircularSafetyDomain(state.p, state.heading, self.safety_radius).shift(self.length * 2, shift_direction)

    def get_crossing_from_starboard_safety_domain(self, state: ActorState) -> SafetyDomain:
        shift_direction = rotate_heading(state.heading, PHANTOM_SHIP_ANGLE)
        return CircularSafetyDomain(state.p, state.heading, self.safety_radius).shift(self.length * 2, shift_direction)

    def get_head_on_safety_domain(self, state: ActorState) -> SafetyDomain:
        a = self.length * 8
        b = self.length * 4
        shift_direction = rotate_heading(state.heading, -PHANTOM_SHIP_ANGLE)
        base_domain = EllipticalSafetyDomain(state.p, state.heading, a, b)
        # should be into the other dir but we only need the distance which is the same
        intersection = base_domain.intersection_of_line_from_center(shift_direction)
        R = distance(intersection, state.p)
        return base_domain.shift(R / 4, shift_direction)
