"""gz-transport actuator adapter of the custom control layer: thrust and helm in, odometry out, world stepped on request.

It runs inside the Gazebo container, next to gz sim, because gz-transport's Python bindings
exist only as packages of the Gazebo image's system Python (gazebo_entrypoint_prod.sh starts it
when GZ_ACTUATOR_PORT is set). So this file imports only the standard library, and the gz
bindings lazily: the backend imports it for its protocol, and the Gazebo image copies it. It
builds the topic names itself for that reason; they are those of the model generator
(generators/vessel_model_generator.py: thrust_topic, steering_topic).

The world starts paused. A runner (gz_lockstep_runner.py, through gz_lockstep_link.py) connects
over TCP and exchanges one JSON object per line. The start request names each model's thrusters
(port and stbd on a skid steered hull, center on one with a rudder or vectored thrust) and says
whether it has a helm. Each step request carries, per model, the thrust in N of every thruster
in that order and, for a model with a helm, the helm angle in rad (positive turns the vessel to
starboard). The adapter publishes them as gz.msgs.Double on
/model/<model>/joint/motor_<thruster>_joint/cmd_thrust and
/model/<model>/joint/steering_joint/cmd_pos, asks the world control service
/world/<world>/control for exactly that many physics iterations, and answers with every model's
gz.msgs.Odometry stamped at the end of the step. Controller and physics share Gazebo's clock:
the world advances only when the controller has acted.

The world control requests go out from a child process with a gz-transport node of its own and no
subscriptions (WorldControlProcess). In one process with the subscriptions, about one request in
eight went unanswered within its timeout while odometry and propeller messages were arriving
(measured on gz-transport 13.5 with the Python bindings).

A command message travels to gz sim asynchronously, so an iteration could still apply the old
command. Before the step's request the adapter waits COMMAND_SETTLE_S and then sends a barrier,
a world control request without iterations. gz sim's gz-transport reception thread handles topic
messages and service requests in turn, so once the barrier is answered every thrust and helm
message that reached gz sim before it has been handled. Without the barrier, about one control
step in 4000 started with an old thrust on the 4-core test machine (WP6); with a fixed wait alone
the step request could overtake the second thruster's message in the same reception round.
With velocity_control, the Thruster system publishes on .../ang_vel, every iteration, the
propeller speed of the thrust it applied. The adapter compares the first of these after the
step's first iteration with the speed of the commanded thrust and counts every thruster that
started late. A run with a late command is not repeatable by construction, and the runner
records the count. A helm command travels before the same barrier, but nothing checks that it
was in effect from the first iteration: the JointPositionController that moves the helm
publishes no feedback of the angle it was commanded.

    -> {"op": "hello"}
    <- {"op": "hello", "protocol": 2}
    -> {"op": "start", "world": "ocean_world", "step_ns": 5000000, "settle_iterations": 200,
        "models": {"<model>": {"thrusters": ["port", "stbd"], "helm": false,
                               "thrust_coefficient": .., "propeller_diameter": .., "fluid_density": 1025, "max_thrust": ..}}}
       (a model with a rudder or vectored thrust: "thrusters": ["center"], "helm": true; other keys are ignored)
    <- {"op": "state", "sim_time_ns": .., "odometry": {"<model>": [x, y, z, qx, qy, qz, qw, vx, vy, vz, wx, wy, wz]}, "late": []}
    -> {"op": "step", "iterations": 20, "commands": {"<model>": {"thrust": [port, starboard]}}}
       (a model with a helm: {"thrust": [center], "helm": <angle in rad>})
    <- {"op": "state", ...}        ("late": ["<model>/<thruster>", ..])
    -> {"op": "close"}

Protocol 1 knew two thrusters per model, port and starboard, and no helm.

Floats travel as JSON numbers in Python's shortest round-trip form, so they arrive bit for bit.
A failure answers {"op": "error", "message": ..} and ends the connection.
"""

import argparse
import json
import math
import multiprocessing
import socket
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

PROTOCOL_VERSION = 2
DEFAULT_PORT = 11400
WORLD_NAME = "ocean_world"
COMMAND_SETTLE_S = 0.002  # wall time between publishing the commands and stepping, so the model's systems usually have them
REPLY_TIMEOUT_S = 120.0  # wall time a step may take before the adapter gives up
ANG_VEL_TOLERANCE = 1e-9  # relative
THRUSTER_CONSTANTS = ("thrust_coefficient", "propeller_diameter", "fluid_density", "max_thrust")  # of a model's start entry, for propeller_speed


def thrust_topic(model: str, thruster: str) -> str:
    return f"/model/{model}/joint/motor_{thruster}_joint/cmd_thrust"


def ang_vel_topic(model: str, thruster: str) -> str:
    return f"/model/{model}/joint/motor_{thruster}_joint/ang_vel"


def steering_topic(model: str) -> str:
    """gz.msgs.Double helm angle in rad of a model with a rudder or vectored thrust."""
    return f"/model/{model}/joint/steering_joint/cmd_pos"


def odometry_topic(model: str) -> str:
    return f"/model/{model}/odometry"


def control_service(world: str) -> str:
    return f"/world/{world}/control"


def stats_topic(world: str) -> str:
    return f"/world/{world}/stats"


def propeller_speed(thrust: float, thrust_coefficient: float, propeller_diameter: float, fluid_density: float, max_thrust: float = math.inf) -> float:
    """The Thruster system's ThrustToAngularVec of the thrust it applies (clamped to max_thrust_cmd): omega = sign(T) sqrt(|T| / (rho C_T D^4))."""
    thrust = min(max(thrust, -max_thrust), max_thrust)
    return math.copysign(math.sqrt(abs(thrust) / (fluid_density * thrust_coefficient * propeller_diameter**4)), thrust)


def odometry_row(message: Any) -> List[float]:
    pose, twist = message.pose, message.twist
    return [
        pose.position.x,
        pose.position.y,
        pose.position.z,
        pose.orientation.x,
        pose.orientation.y,
        pose.orientation.z,
        pose.orientation.w,
        twist.linear.x,
        twist.linear.y,
        twist.linear.z,
        twist.angular.x,
        twist.angular.y,
        twist.angular.z,
    ]


def stamp_ns(message: Any) -> int:
    return int(message.header.stamp.sec) * 1_000_000_000 + int(message.header.stamp.nsec)


class ActuatorError(RuntimeError):
    pass


class WorldControl(Protocol):
    def request(self, world: str, iterations: int) -> bool:
        """Pause the world and ask for that many iterations (none: only pause). True once answered."""


def _gz_world_control_request(node: Any, messages: Dict[str, Any], world: str, iterations: int) -> bool:
    control = messages["WorldControl"]()
    control.pause = True
    control.multi_step = iterations
    accepted, response = node.request(control_service(world), control, messages["WorldControl"], messages["Boolean"], 5000)
    return bool(accepted and response.data)


def _world_control_process(connection: Any) -> None:
    """Child process of WorldControlProcess: one gz-transport node that only sends world control requests."""
    from gz import transport13
    from gz.msgs10.boolean_pb2 import Boolean
    from gz.msgs10.world_control_pb2 import WorldControl as WorldControlMessage

    node = transport13.Node()
    messages = {"WorldControl": WorldControlMessage, "Boolean": Boolean}
    while True:
        request = connection.recv()
        if request is None:
            return
        world, iterations = request
        connection.send(_gz_world_control_request(node, messages, world, iterations))


class WorldControlProcess:
    """World control requests from a child process (see the module docstring for why)."""

    def __init__(self) -> None:
        context = multiprocessing.get_context("spawn")
        self._connection, child = context.Pipe()
        self._process = context.Process(target=_world_control_process, args=(child,), daemon=True)
        self._process.start()

    def request(self, world: str, iterations: int) -> bool:
        self._connection.send((world, iterations))
        return bool(self._connection.recv())


class InProcessWorldControl:
    """World control requests from the adapter's own node; for tests with a fake transport."""

    def __init__(self, node: Any, messages: Dict[str, Any]):
        self._node = node
        self._messages = messages

    def request(self, world: str, iterations: int) -> bool:
        return _gz_world_control_request(self._node, self._messages, world, iterations)


class GzTransportActuator:
    """The adapter's gz-transport side. transport and messages default to gz.transport13 and the gz.msgs10 modules."""

    def __init__(
        self,
        transport: Any = None,
        messages: Optional[Dict[str, Any]] = None,
        world_control: Optional[WorldControl] = None,
        sleep: Callable[[float], None] = time.sleep,
        reply_timeout_s: float = REPLY_TIMEOUT_S,
    ):
        if transport is None:
            from gz import transport13 as transport
        if messages is None:
            from gz.msgs10.boolean_pb2 import Boolean
            from gz.msgs10.double_pb2 import Double
            from gz.msgs10.odometry_pb2 import Odometry
            from gz.msgs10.world_control_pb2 import WorldControl
            from gz.msgs10.world_stats_pb2 import WorldStatistics

            messages = {"Boolean": Boolean, "Double": Double, "Odometry": Odometry, "WorldControl": WorldControl, "WorldStatistics": WorldStatistics}
        self._messages = messages
        self._node = transport.Node()
        self._world_control = world_control if world_control is not None else WorldControlProcess()
        self._sleep = sleep
        self._reply_timeout_s = reply_timeout_s
        self._condition = threading.Condition()
        self._world = WORLD_NAME
        self._step_ns = 0
        self._sim_time_ns = 0
        self._thrusters: Dict[str, Tuple[str, ...]] = {}  # each model's thrusters, in the order their thrusts are commanded
        self._constants: Dict[str, Dict[str, float]] = {}  # each model's Thruster system constants
        self._publishers: Dict[Tuple[str, str], Any] = {}  # by (model, thruster)
        self._helm_publishers: Dict[str, Any] = {}  # by model, for the models with a helm
        self._odometry: Dict[str, Tuple[int, List[float]]] = {}  # latest message per model
        self._ang_vel: Dict[Tuple[str, str], List[float]] = {}  # this step's messages per thruster
        self._commanded: Dict[Tuple[str, str], float] = {}
        self._stats: List[Tuple[int, bool]] = []  # (sim time, paused) of every world statistics message

    # gz-transport callbacks (transport threads)

    def _on_odometry(self, model: str) -> Callable[[Any], None]:
        def callback(message: Any) -> None:
            with self._condition:
                self._odometry[model] = (stamp_ns(message), odometry_row(message))
                self._condition.notify_all()

        return callback

    def _on_stats(self, message: Any) -> None:
        with self._condition:
            self._stats.append((int(message.sim_time.sec) * 1_000_000_000 + int(message.sim_time.nsec), bool(message.paused)))
            self._condition.notify_all()

    def _on_ang_vel(self, key: Tuple[str, str]) -> Callable[[Any], None]:
        def callback(message: Any) -> None:
            with self._condition:
                if key in self._ang_vel:  # not a thruster of an earlier start that this one left out
                    self._ang_vel[key].append(float(message.data))
                    self._condition.notify_all()

        return callback

    # Requests

    def start(self, request: Dict[str, Any]) -> Dict[str, Any]:
        self._world = str(request.get("world", WORLD_NAME))
        self._step_ns = int(request["step_ns"])
        models = {str(model): dict(entry) for model, entry in request["models"].items()}
        thrusters: Dict[str, Tuple[str, ...]] = {}
        for model, entry in models.items():
            thrusters[model] = tuple(str(name) for name in entry["thrusters"])
            if not thrusters[model] or len(set(thrusters[model])) != len(thrusters[model]):
                raise ActuatorError(f"{model} needs at least one thruster and each one once, got {list(thrusters[model])}")
        self._thrusters = thrusters
        self._constants = {model: {key: float(entry[key]) for key in THRUSTER_CONSTANTS} for model, entry in models.items()}
        self._publishers, self._helm_publishers, self._commanded = {}, {}, {}
        with self._condition:
            self._ang_vel = {(model, thruster): [] for model, names in self._thrusters.items() for thruster in names}
        for model in sorted(self._thrusters):
            self._node.subscribe(self._messages["Odometry"], odometry_topic(model), self._on_odometry(model))
            for thruster in self._thrusters[model]:
                key = (model, thruster)
                self._publishers[key] = self._node.advertise(thrust_topic(model, thruster), self._messages["Double"])
                self._node.subscribe(self._messages["Double"], ang_vel_topic(model, thruster), self._on_ang_vel(key))
            if models[model].get("helm"):
                self._helm_publishers[model] = self._node.advertise(steering_topic(model), self._messages["Double"])
        self._wait_for_subscribers()
        self._sim_time_ns = self._paused_sim_time()
        # Settling: no thrust and the helm amidships.
        commands = {model: {"thrust": [0.0] * len(names), "helm": 0.0 if model in self._helm_publishers else None} for model, names in self._thrusters.items()}
        return self.step({"iterations": int(request.get("settle_iterations", 0)) or 4, "commands": commands})

    def step(self, request: Dict[str, Any]) -> Dict[str, Any]:
        iterations = int(request["iterations"])
        if iterations <= 0:
            raise ActuatorError(f"a step needs at least one iteration, got {iterations}")
        commands = request["commands"]
        self._check_commands(commands)  # all of them, before any is published
        with self._condition:
            for key in self._ang_vel:
                self._ang_vel[key] = []
        for model, names in sorted(self._thrusters.items()):
            if model in self._helm_publishers:
                self._publish(self._helm_publishers[model], commands[model]["helm"])
            for thruster, value in zip(names, commands[model]["thrust"]):
                self._publish(self._publishers[(model, thruster)], value)
                self._commanded[(model, thruster)] = float(value)
        self._sleep(COMMAND_SETTLE_S)
        if not self._control(0):
            raise ActuatorError(f"{control_service(self._world)} did not answer the barrier before a step")
        target_ns = self._sim_time_ns + iterations * self._step_ns
        if not self._control(iterations):
            raise ActuatorError(f"{control_service(self._world)} did not answer a request for {iterations} iterations")
        self._wait_for_step(target_ns, iterations)
        self._sim_time_ns = target_ns
        return self._state()

    # Internals

    def _check_commands(self, commands: Dict[str, Any]) -> None:
        """Every model has a command with one thrust per thruster, and a helm angle exactly when it has a helm."""
        missing = sorted(set(self._thrusters) - set(commands))
        if missing:
            raise ActuatorError(f"no command for {missing}")
        for model, names in sorted(self._thrusters.items()):
            thrust, helm = commands[model]["thrust"], commands[model].get("helm")
            if len(thrust) != len(names):
                raise ActuatorError(f"{model} has the thrusters {list(names)}, got {len(thrust)} thrusts")
            if model in self._helm_publishers and helm is None:
                raise ActuatorError(f"{model} has a helm and got no helm angle")
            if model not in self._helm_publishers and helm is not None:
                raise ActuatorError(f"{model} has no helm and got a helm angle")

    def _publish(self, publisher: Any, value: float) -> None:
        message = self._messages["Double"]()
        message.data = float(value)
        publisher.publish(message)

    def _control(self, iterations: int) -> bool:
        return self._world_control.request(self._world, iterations)

    def _paused_sim_time(self) -> int:
        """Gazebo's time with the world paused, after its control service answered.

        A fresh node's first service request can go unanswered before discovery finds the
        service, so a pause without iterations is repeated until answered: it changes nothing.
        The time comes from the world statistics, so a world stepped before still lines up.
        """
        self._node.subscribe(self._messages["WorldStatistics"], stats_topic(self._world), self._on_stats)
        deadline = time.monotonic() + self._reply_timeout_s
        with self._condition:
            seen = len(self._stats)
        while not self._control(0):
            if time.monotonic() > deadline:
                raise ActuatorError(f"{control_service(self._world)} did not answer within {self._reply_timeout_s:g} s")
            self._sleep(0.2)
        with self._condition:
            # The statistics come about five times a wall second; wait for a paused one sent after the pause request.
            while len(self._stats) <= seen or not self._stats[-1][1]:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ActuatorError(f"no paused world statistics on {stats_topic(self._world)} within {self._reply_timeout_s:g} s")
                self._condition.wait(min(remaining, 1.0))
            return self._stats[-1][0]

    def _wait_for_subscribers(self) -> None:
        deadline = time.monotonic() + self._reply_timeout_s
        publishers = list(self._publishers.values()) + list(self._helm_publishers.values())
        while not all(publisher.has_connections() for publisher in publishers):
            if time.monotonic() > deadline:
                raise ActuatorError(
                    "the Thruster systems and helm controllers did not subscribe to the command topics;"
                    " is the model loaded, has it no ArduPilotPlugin and has it the steering type the runner derived?"
                )
            self._sleep(0.05)

    def _wait_for_step(self, target_ns: int, iterations: int) -> None:
        deadline = time.monotonic() + self._reply_timeout_s

        def done() -> bool:
            odometry_ready = all(model in self._odometry and self._odometry[model][0] >= target_ns for model in self._thrusters)
            return odometry_ready and all(len(values) >= iterations for values in self._ang_vel.values())

        with self._condition:
            while not done():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    stamps = {model: self._odometry.get(model, (None,))[0] for model in self._thrusters}
                    counts = {f"{model}/{thruster}": len(values) for (model, thruster), values in self._ang_vel.items()}
                    raise ActuatorError(
                        f"no odometry at {target_ns} ns within {self._reply_timeout_s:g} s (odometry stamps {stamps}, ang_vel counts {counts});"
                        " the control step must be a multiple of the odometry period"
                    )
                self._condition.wait(min(remaining, 1.0))
            stale = sorted(model for model in self._thrusters if self._odometry[model][0] != target_ns)
            if stale:
                raise ActuatorError(f"odometry of {stale} is not stamped at the step's end {target_ns} ns; the control step must be a multiple of the odometry period")

    def _late_thrusters(self) -> List[str]:
        late = []
        for (model, thruster), values in sorted(self._ang_vel.items()):
            expected = propeller_speed(self._commanded[(model, thruster)], **self._constants[model])
            if abs(values[0] - expected) > ANG_VEL_TOLERANCE * max(1.0, abs(expected)):
                late.append(f"{model}/{thruster}")
        return late

    def _state(self) -> Dict[str, Any]:
        with self._condition:
            return {
                "op": "state",
                "sim_time_ns": self._sim_time_ns,
                "odometry": {model: self._odometry[model][1] for model in sorted(self._thrusters)},
                "late": self._late_thrusters(),
            }


def serve_connection(actuator: GzTransportActuator, connection: socket.socket) -> None:
    """Answer one client's requests, one JSON object per line, until it closes."""
    reader = connection.makefile("r", encoding="utf-8", newline="\n")
    writer = connection.makefile("w", encoding="utf-8", newline="\n")
    handlers = {"hello": lambda request: {"op": "hello", "protocol": PROTOCOL_VERSION}, "start": actuator.start, "step": actuator.step}
    for line in reader:
        if not line.strip():
            continue
        request = json.loads(line)
        operation = request.get("op")
        if operation == "close":
            break
        try:
            if operation not in handlers:
                raise ActuatorError(f"unknown op {operation!r}")
            reply = handlers[operation](request)
        except Exception as error:
            writer.write(json.dumps({"op": "error", "message": f"{type(error).__name__}: {error}"}) + "\n")
            writer.flush()
            break
        writer.write(json.dumps(reply) + "\n")
        writer.flush()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="gz-transport actuator adapter of the SceneGEMS custom control layer")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args(argv)
    actuator = GzTransportActuator()
    with socket.create_server((args.host, args.port)) as server:
        print(f"gz_transport_actuator: protocol {PROTOCOL_VERSION} on {args.host}:{args.port}", flush=True)
        while True:
            connection, address = server.accept()
            with connection:
                print(f"gz_transport_actuator: runner connected from {address[0]}", flush=True)
                serve_connection(actuator, connection)


if __name__ == "__main__":
    raise SystemExit(main())
