"""USV Navigation as a plug and play ASV software component: colav_automaton behind the lockstep wire protocol.

The image of this component (deploy/images/usv_navigation) holds colav_automaton, numpy, this
file and contracts/lockstep_wire.py, and nothing else of SceneGEMS. So this file imports only
those and the standard library. Everything it needs about the vessel and the scenario arrives in
the start message; the config is UsvNavigationParameters in wire form
(usv_navigation_participant.usv_navigation_start_config):

    "config": {"goal": [x, y], "speed": v, "horizon": 1852.0 or null, "runtime": {"Cs": .., "v": .., "tp": .., "tp_control": .., ..}}

Its report holds the automaton's transitions and when the goal was reached. Entry point:

    python -m scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_server --port 11410

UsvNavigator is the navigation step itself. The in-process participant
(usv_navigation_participant.py) runs the same class, so a run gives the same commands whether USV
Navigation is hosted in the runner or in its container.

Frame mapping, fixed by the WP5a frame test on the kinematic layer (design doc 12.9):

- Position: the runtime's [x, y] is the SceneGEMS local frame unchanged (x east, y north,
  meters).
- Heading: psi is the state's heading unchanged (radians, counterclockwise from east). The
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
  half a turn, which a wrapped heading difference would lose. Speed is the configured v.

In the frame test (head-on, crossing from starboard, crossing from port, overtaking, and a
goal behind the beam) this mapping reaches the goal, the runtime classifies each encounter
as SceneGEMS does, and its starboard choices turn the vessel clockwise. A compass heading
misses the goal, and a mirrored east-north swap reaches it with port and starboard swapped.
"""

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from scenegems_tool.vessel_stack.contracts.lockstep_wire import ROLE_ASV_SOFTWARE, Message, Session, WireError, serve_component

IMPLEMENTATION = "usv_navigation"
DEFAULT_PORT = 11410  # contracts/stack_services.ASV_SOFTWARE_PORT, which this file cannot import

State = Tuple[float, float, float, float]  # x, y, speed, heading


def participant_id(vessel_id: int) -> str:
    return f"{IMPLEMENTATION}/{vessel_id}"


def rotate_heading(heading: float, angle: float) -> float:
    """heading + angle within [-pi, pi], as utils.math_utils.rotate_heading computes it."""
    x, y = np.cos(heading), np.sin(heading)
    cos_a, sin_a = np.cos(angle), np.sin(angle)
    return np.arctan2(x * sin_a + y * cos_a, x * cos_a - y * sin_a)


class UsvNavigator:
    """Steps one SyncColavRuntime per simulation step and returns the heading and speed to command.

    The runtime is built on the first step from the first observation. Once the own ship is
    within the runtime's arrival radius of the goal, the navigator holds heading and speed for
    the rest of the run instead of circling the goal.
    """

    def __init__(self, *, goal: Sequence[float], speed: float, horizon: Optional[float], runtime: Mapping[str, float], max_angular_speed: float):
        self.goal = (float(goal[0]), float(goal[1]))
        self.speed = speed
        self.horizon = horizon
        self.runtime_arguments = dict(runtime)
        self.max_angular_speed = max_angular_speed
        self.reset()

    def reset(self) -> None:
        self._runtime: Any = None
        self.transitions: List[Tuple[float, str, str]] = []  # (simulated time, transition, mode after it)
        self.goal_reached_at: Optional[float] = None

    def step(self, time: float, dt: float, own: State, targets: Sequence[State]) -> Tuple[float, float]:
        """The (heading, speed) command for the step from time to time + dt. targets are the other actors' states, ordered by actor id."""
        own_x, own_y, _, own_heading = own
        if self.goal_reached_at is not None:
            return own_heading, self.speed
        state = [own_x, own_y, own_heading]
        obstacles = [(x, y, speed, heading) for x, y, speed, heading in targets if self.horizon is None or math.hypot(x - own_x, y - own_y) <= self.horizon]
        if self._runtime is None:
            self._runtime = self._build_runtime(obstacles, state)
        result = self._runtime.step_external(dt, state, obstacles)
        if result.transition is not None:
            self.transitions.append((time, result.transition, result.mode))
        if self._runtime.goal_reached():
            self.goal_reached_at = time
            return own_heading, self.speed
        yaw_rate = self._runtime.configuration["a"] * (result.u - own_heading)
        max_step = min(self.max_angular_speed * dt, np.pi)
        heading = rotate_heading(own_heading, float(np.clip(yaw_rate * dt, -max_step, max_step)))
        return float(heading), self.speed

    def report(self) -> Dict[str, Any]:
        return {"transitions": [[time, transition, mode] for time, transition, mode in self.transitions], "goal_reached_at": self.goal_reached_at}

    def _build_runtime(self, obstacles: List[State], state: List[float]) -> Any:
        from colav_automaton import SyncColavRuntime  # on the first step, so the module loads where colav_automaton is absent

        runtime = SyncColavRuntime(waypoint=self.goal, obstacles=obstacles, initial_state=state, **self.runtime_arguments)
        if self.horizon is not None:
            runtime.configuration["dsafe"] = self.horizon
        return runtime


class UsvNavigationSession(Session):
    def __init__(self) -> None:
        self._navigator: Optional[UsvNavigator] = None

    def on_start(self, request: Message) -> Message:
        vessel, config = request["vessel"], request["config"]
        self._navigator = UsvNavigator(
            goal=config["goal"],
            speed=float(config["speed"]),
            horizon=None if config.get("horizon") is None else float(config["horizon"]),
            runtime=config["runtime"],
            max_angular_speed=float(vessel["max_angular_speed"]),
        )
        return {"op": "started", "participant_id": participant_id(int(vessel["id"]))}

    def on_step(self, request: Message) -> Message:
        navigator = self._started()
        time, target_time = float(request["time"]), float(request["target_time"])
        targets = [tuple(row) for _, row in sorted(request["targets"].items(), key=lambda item: int(item[0]))]
        heading, speed = navigator.step(time, target_time - time, tuple(request["own"]), targets)
        return {"op": "command", "heading": heading, "speed": speed}

    def on_report(self, request: Message) -> Message:
        del request
        return {"op": "report", "report": self._started().report()}

    def _started(self) -> UsvNavigator:
        if self._navigator is None:
            raise WireError("step before start")
        return self._navigator


def main(argv: Optional[Sequence[str]] = None) -> None:
    serve_component(ROLE_ASV_SOFTWARE, IMPLEMENTATION, UsvNavigationSession, argv, default_port=DEFAULT_PORT)


if __name__ == "__main__":
    main()
