"""Horizontal-plane model of the generated hull: the plant the custom autopilot is designed on and tested against.

The coefficients are the VesselDynamics the Gazebo model generator writes into the SDF
(simulation_layers/gazebo/generators/vessel_dynamics.py), restricted to surge, sway and yaw:

    (m - xDotU) du/dt =  m v r + X - (|xU| u + |xUabsU| u|u|)
    (m - yDotV) dv/dt = -m u r + Y - (|yV| v + |yVabsV| v|v|)
    (Izz - nDotR) dr/dt =        N - (|nR| r + |nRabsR| r|r|)

with body x forward, y to port and the yaw rate r counterclockwise from above. X, Y and N are
the forces of the steering gear, by the hull's steering type:

- skid: X = Tp + Ts, Y = 0, N = y (Ts - Tp), so the starboard thruster turns the hull to port.
- rudder: X is the thrust and the rudder's drag, Y the rudder's side force in the flow at the
  stern, v + steering_x r across the hull, and N = steering_x Y.
- vectored_thrust: (X, Y) = T (cos d, sin d) and N = steering_x Y.

A positive helm angle d turns the hull to starboard. The helm travels toward the commanded angle
at the steering rate and stops on it or at hard over, as the model's JointPositionController moves
steering_joint.

The rigid-body Coriolis terms are kept (Gazebo's physics has them) and the added-mass ones left
out, as the SDF disables them. There is no buoyancy, roll, pitch, wind or wave here: the model is
for designing gains and for tests, not a substitute for Gazebo.
"""

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from logical_level.mapping.vessel_type import SteeringType
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import VesselDynamics


def damping(linear: float, quadratic: float, value: float) -> float:
    """Magnitude-signed damping force (or moment) |linear| v + |quadratic| v|v| of a velocity v."""
    return abs(linear) * value + abs(quadratic) * value * abs(value)


@dataclass(frozen=True)
class HullState:
    x: float  # m, local frame (east)
    y: float  # m, local frame (north)
    heading: float  # rad, counterclockwise from east
    surge: float  # m/s, body x
    sway: float  # m/s, body y (to port)
    yaw_rate: float  # rad/s, counterclockwise
    helm_angle: float = 0.0  # rad, where the helm is; stays 0 on a skid steered hull

    @property
    def speed(self) -> float:
        return math.hypot(self.surge, self.sway)


class HullSurgeYawModel:
    def __init__(self, dynamics: VesselDynamics):
        self.dynamics = dynamics
        self.mass = dynamics.total_mass
        self.surge_mass = self.mass + abs(dynamics.xDotU)
        self.sway_mass = self.mass + abs(dynamics.yDotV)
        self.yaw_inertia = dynamics.hull_izz + abs(dynamics.nDotR)
        self.skid = dynamics.steering_type == SteeringType.SKID.value

    def step(self, state: HullState, thrusts: Sequence[float], helm_angle: Optional[float], dt: float) -> HullState:
        """One semi-implicit Euler step: velocities first, then the pose from the new velocities.

        thrusts are in N in the order of the hull's thrusters (port and starboard, or the one
        in the center); helm_angle is the commanded angle in rad, None for a skid steered hull.
        The forces act with the helm where the state has it, and the helm then travels on.
        """
        d = self.dynamics
        limit = d.max_thrust
        if len(thrusts) != d.thruster_count:
            raise ValueError(f"a {d.steering_type} steered hull takes {d.thruster_count} thrusts, got {len(thrusts)}")
        u, v, r = state.surge, state.sway, state.yaw_rate
        helm = state.helm_angle
        if self.skid:
            if helm_angle is not None:
                raise ValueError("a skid steered hull has no helm")
            port = min(max(thrusts[0], -limit), limit)
            starboard = min(max(thrusts[1], -limit), limit)
            u_dot = (self.mass * v * r + port + starboard - damping(d.xU, d.xUabsU, u)) / self.surge_mass
            v_dot = (-self.mass * u * r - damping(d.yV, d.yVabsV, v)) / self.sway_mass
            r_dot = (d.thruster_y * (starboard - port) - damping(d.nR, d.nRabsR, r)) / self.yaw_inertia
        else:
            if helm_angle is None:
                raise ValueError(f"a {d.steering_type} steered hull needs a helm angle")
            thrust = min(max(thrusts[0], -limit), limit)
            force_x, force_y = d.helm_force(helm, u, v + d.steering_x * r, thrust)
            u_dot = (self.mass * v * r + force_x - damping(d.xU, d.xUabsU, u)) / self.surge_mass
            v_dot = (-self.mass * u * r + force_y - damping(d.yV, d.yVabsV, v)) / self.sway_mass
            r_dot = (d.steering_x * force_y - damping(d.nR, d.nRabsR, r)) / self.yaw_inertia
            target = min(max(helm_angle, -d.steering_max_angle), d.steering_max_angle)
            travel = d.steering_rate * dt
            helm = helm + min(max(target - helm, -travel), travel)
        u, v, r = u + u_dot * dt, v + v_dot * dt, r + r_dot * dt
        heading = state.heading + r * dt
        cos_heading, sin_heading = math.cos(heading), math.sin(heading)
        return HullState(
            x=state.x + (u * cos_heading - v * sin_heading) * dt,
            y=state.y + (u * sin_heading + v * cos_heading) * dt,
            heading=math.atan2(sin_heading, cos_heading),
            surge=u,
            sway=v,
            yaw_rate=r,
            helm_angle=helm,
        )
