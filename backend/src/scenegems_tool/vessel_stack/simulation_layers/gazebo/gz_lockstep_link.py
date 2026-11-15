"""Runner side of the gz-transport actuator adapter: thrust and helm in, odometry out, over one TCP connection.

The adapter itself runs in the Gazebo container (gz_transport_actuator.py, which documents the
protocol). This side needs only the standard library, so the runner can live in the simulation
subsystem image, which has no gz bindings.
"""

import json
import math
import socket
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.control_layers.custom.actuator_allocation import ActuatorCommand
from scenegems_tool.vessel_stack.control_layers.custom.twin_thrust_autopilot import HullObservation
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_transport_actuator import DEFAULT_PORT, PROTOCOL_VERSION, WORLD_NAME


class GzLockstepLinkError(RuntimeError):
    pass


@dataclass(frozen=True)
class HullOdometry:
    """One model's gz.msgs.Odometry: world pose and body-frame twist (x forward, y port, z up)."""

    x: float
    y: float
    z: float
    qx: float
    qy: float
    qz: float
    qw: float
    surge: float
    sway: float
    heave: float
    roll_rate: float
    pitch_rate: float
    yaw_rate: float

    @classmethod
    def from_row(cls, row: List[float]) -> "HullOdometry":
        return cls(*(float(value) for value in row))

    @property
    def heading(self) -> float:
        """Yaw of the hull, counterclockwise from east (the world is ENU, as the local frame)."""
        return math.atan2(2.0 * (self.qw * self.qz + self.qx * self.qy), 1.0 - 2.0 * (self.qy * self.qy + self.qz * self.qz))

    @property
    def speed(self) -> float:
        return math.hypot(self.surge, self.sway)

    def actor_state(self) -> ActorState:
        return ActorState(x=self.x, y=self.y, speed=self.speed, heading=self.heading)

    def observation(self) -> HullObservation:
        return HullObservation(heading=self.heading, surge=self.surge, yaw_rate=self.yaw_rate, sway=self.sway)


@dataclass(frozen=True)
class GzStepResult:
    sim_time_ns: int
    odometry: Mapping[str, HullOdometry]  # by model name
    late: Tuple[str, ...]  # "<model>/<thruster>" thrusters whose command was not in effect from the step's first iteration


def command_message(command: ActuatorCommand) -> Dict[str, Any]:
    """The actuator protocol's form of one model's command: the thrusts in the order of its thrusters and, with a helm, the helm angle."""
    message: Dict[str, Any] = {"thrust": [float(thrust) for thrust in command.thrusts]}
    if command.helm_angle is not None:
        message["helm"] = float(command.helm_angle)
    return message


class GzLockstepLink:
    def __init__(self, host: str, port: int = DEFAULT_PORT, *, world: str = WORLD_NAME):
        self.host = host
        self.port = int(port)
        self.world = world
        self._socket: Optional[socket.socket] = None
        self._reader: Any = None
        self._writer: Any = None

    def connect(self, timeout_s: float = 300.0) -> None:
        """Connect and exchange hello, retrying while Gazebo and the adapter start.

        A published Docker port accepts connections before the adapter listens behind it, so
        only an answered hello counts as connected.
        """
        deadline = time.monotonic() + timeout_s
        last_error: Optional[BaseException] = None
        while time.monotonic() < deadline:
            try:
                self._socket = socket.create_connection((self.host, self.port), timeout=5.0)
                self._reader = self._socket.makefile("r", encoding="utf-8", newline="\n")
                self._writer = self._socket.makefile("w", encoding="utf-8", newline="\n")
                reply = self._exchange({"op": "hello"})
                if reply.get("protocol") != PROTOCOL_VERSION:
                    raise GzLockstepLinkError(f"{self.host}:{self.port} speaks protocol {reply.get('protocol')}, this runner {PROTOCOL_VERSION}")
                self._socket.settimeout(None)
                return
            except (OSError, ValueError) as error:
                last_error = error
                if self._socket is not None:
                    self._socket.close()
                self._socket = self._reader = self._writer = None
                time.sleep(1.0)
        raise GzLockstepLinkError(f"no gz-transport actuator at {self.host}:{self.port} within {timeout_s:g} s (last error: {last_error})")

    def start(self, models: Mapping[str, Mapping[str, Any]], step_ns: int, settle_iterations: int) -> GzStepResult:
        """Register the models and let them float settle_iterations with no thrust and the helm amidships.

        Each model's entry names its thrusters in the order their thrusts are commanded, says
        whether it has a helm and gives the thruster constants (gz_lockstep_runner.thruster_constants).
        """
        return self._request(
            {"op": "start", "world": self.world, "step_ns": int(step_ns), "settle_iterations": int(settle_iterations), "models": {name: dict(entry) for name, entry in models.items()}}
        )

    def step(self, iterations: int, commands: Mapping[str, ActuatorCommand]) -> GzStepResult:
        """Apply each model's command (its thrusts and, with a helm, the helm angle) and step the world."""
        return self._request({"op": "step", "iterations": int(iterations), "commands": {name: command_message(command) for name, command in commands.items()}})

    def close(self) -> None:
        if self._writer is not None:
            try:
                self._writer.write(json.dumps({"op": "close"}) + "\n")
                self._writer.flush()
            except OSError:
                pass
        if self._socket is not None:
            self._socket.close()
        self._socket = self._reader = self._writer = None

    def __enter__(self) -> "GzLockstepLink":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def _exchange(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if self._writer is None:
            raise GzLockstepLinkError(f"{self.host}:{self.port}: not connected")
        self._writer.write(json.dumps(request) + "\n")
        self._writer.flush()
        line = self._reader.readline()
        if not line:
            raise ConnectionError(f"{self.host}:{self.port}: the actuator closed the connection")
        reply = json.loads(line)
        if reply.get("op") == "error":
            raise GzLockstepLinkError(f"{self.host}:{self.port}: {reply.get('message')}")
        return reply

    def _request(self, request: Dict[str, Any]) -> GzStepResult:
        reply = self._exchange(request)
        return GzStepResult(
            sim_time_ns=int(reply["sim_time_ns"]),
            odometry={name: HullOdometry.from_row(row) for name, row in reply["odometry"].items()},
            late=tuple(reply.get("late", ())),
        )
