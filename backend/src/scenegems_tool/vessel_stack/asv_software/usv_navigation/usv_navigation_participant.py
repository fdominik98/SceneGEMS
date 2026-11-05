"""USV Navigation as a lockstep participant on the heading_speed_cmd port.

Every step the participant hands the observed own state and target tracks to
SyncColavRuntime.step_external, which evaluates the automaton without integrating, and turns
the returned control u into a heading and speed command for the simulation layer.

Frame mapping, fixed by the WP5a frame test on the kinematic layer (design doc 12.9):

- Position: the runtime's [x, y] is the SceneGEMS local frame unchanged (x east, y north,
  meters).
- Heading: psi is ActorState.heading unchanged (radians, counterclockwise from east). The
  upstream plant integrates dx/dt = v cos(psi), dy/dt = v sin(psi), and its encounter logic
  reads a positive relative bearing as port. The runtime uses psi only through sine, cosine
  and wrapped differences, so the heading in [-pi, pi] needs no unwrapping.
- Obstacles: one (x, y, speed, heading) tuple per other actor within the horizon, same frame
  and units, ordered by actor id. Static obstacles enter with speed 0.
- Horizon: it replaces the runtime's dsafe, which is how far the unsafe set reaches when
  avoidance starts. Upstream's Cs + v * tp is far shorter than the range avoidance starts at,
  so a target beyond it gets a virtual waypoint beside its current position, and a head-on
  pass keeps only about 0.6 Cs. The runtime has no argument for dsafe, and tp cannot carry it
  because tp also sizes the arrival radius, so the configuration is set directly.
- Output: u is the input of the upstream heading plant yaw_rate = a * (u - psi), which both
  upstream hosts (CommonOcean and ROS 2) apply in every mode, so this adapter does too (in
  CONSTANT_CONTROL the runtime's own integrator would hold the heading instead). The yaw
  rate is integrated over the step and limited to the turn the vessel can make in dt; the
  result is the desired heading. The limit keeps the sense of rotation of a demand beyond
  half a turn, which ConcreteVessel.simulate would otherwise wrap. Speed is the configured v.

In the frame test (head-on, crossing from starboard, crossing from port, overtaking, and a
goal behind the beam) this mapping reaches the goal, the runtime classifies each encounter
as SceneGEMS does, and its starboard choices turn the vessel clockwise. A compass heading
misses the goal, and a mirrored east-north swap reaches it with port and starboard swapped.
"""

import math
from typing import List, Optional, Tuple

import numpy as np
from colav_automaton import SyncColavRuntime

from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_parameters import UsvNavigationParameters
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_specs import USV_NAVIGATION_IN_PROCESS
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand, VesselStateObservation
from utils.math_utils import rotate_heading


class UsvNavigationParticipant:
    """Steps one SyncColavRuntime per simulation step and commands heading and speed.

    The runtime is built on step 0 from the first observation. Once the own ship is within
    the runtime's arrival radius of the goal, the participant holds heading and speed for
    the rest of the run instead of circling the goal.
    """

    spec = USV_NAVIGATION_IN_PROCESS

    def __init__(self, vessel: ConcreteVessel, parameters: UsvNavigationParameters):
        self.vessel = vessel
        self.parameters = parameters
        self.participant_id = f"usv_navigation/{vessel.id}"
        self._runtime: Optional[SyncColavRuntime] = None
        self.transitions: List[Tuple[float, str, str]] = []  # (simulated time, transition, mode after it)
        self.goal_reached_at: Optional[float] = None

    def start(self, seed: int) -> None:
        del seed  # SyncColavRuntime has no randomness
        self._runtime = None
        self.transitions = []
        self.goal_reached_at = None

    def on_step(self, request: StepRequest, observation: VesselStateObservation) -> HeadingSpeedCommand:
        own = observation.own_state
        speed = self.parameters.speed
        if self.goal_reached_at is not None:
            return HeadingSpeedCommand(heading=own.heading, speed=speed)
        state = [own.x, own.y, own.heading]
        obstacles = self._obstacles_in_view(observation)
        if self._runtime is None:
            self._runtime = self._build_runtime(obstacles, state)
        dt = request.target_time - request.time
        result = self._runtime.step_external(dt, state, obstacles)
        if result.transition is not None:
            self.transitions.append((request.time, result.transition, result.mode))
        if self._runtime.goal_reached():
            self.goal_reached_at = request.time
            return HeadingSpeedCommand(heading=own.heading, speed=speed)
        yaw_rate = self._runtime.configuration["a"] * (result.u - own.heading)
        max_step = self.vessel.get_max_heading_step(dt)
        heading = rotate_heading(own.heading, float(np.clip(yaw_rate * dt, -max_step, max_step)))
        return HeadingSpeedCommand(heading=float(heading), speed=speed)

    def _obstacles_in_view(self, observation: VesselStateObservation) -> List[Tuple[float, float, float, float]]:
        own = observation.own_state
        horizon = self.parameters.horizon
        return [
            (target.x, target.y, target.speed, target.heading)
            for _, target in sorted(observation.target_states.items())
            if horizon is None or math.hypot(target.x - own.x, target.y - own.y) <= horizon
        ]

    def _build_runtime(self, obstacles: List[Tuple[float, float, float, float]], state: List[float]) -> SyncColavRuntime:
        runtime = SyncColavRuntime(waypoint=self.parameters.goal, obstacles=obstacles, initial_state=state, **self.parameters.runtime_kwargs())
        if self.parameters.horizon is not None:
            runtime.configuration["dsafe"] = self.parameters.horizon
        return runtime
