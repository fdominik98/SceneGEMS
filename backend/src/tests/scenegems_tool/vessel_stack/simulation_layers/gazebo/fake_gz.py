"""A fake gz-transport and gz sim for the actuator tests: thrust and helm topics, odometry, propeller feedback and world control.

FakeWorld advances only on a world control request, like a paused gz sim stepped by multi_step.
Every iteration, each Thruster publishes the propeller speed of the thrust it applies on its
ang_vel topic, and the odometry is published every ODOMETRY_PERIOD_NS of simulated time. The
hull moves 1 m per second per kN of total thrust, just enough to tell steps apart.
A model has the thrusters port and stbd unless `thrusters` names others, and a helm when it is in
`helms`: the helm angle it was last commanded is in `applied` under its steering topic, like a thrust.
A command can be delivered late (late_iterations), as a real message travelling to gz sim can.
With reception_rounds, command messages queue like gz sim's gz-transport reception thread takes
them: each round handles one topic message and then a waiting service request, and the thread
drains the rest of the queue after answering a request without iterations, but only while a
request with iterations is already stepping the world.
"""

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Tuple

from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_transport_actuator import propeller_speed

ODOMETRY_PERIOD_NS = 20_000_000


class _Stamp:
    def __init__(self, ns: int = 0):
        self.sec, self.nsec = divmod(ns, 1_000_000_000)


class _Vector:
    def __init__(self, x: float = 0.0, y: float = 0.0, z: float = 0.0, w: float = 1.0):
        self.x, self.y, self.z, self.w = x, y, z, w


class Double:
    def __init__(self, data: float = 0.0):
        self.data = data


class Boolean:
    def __init__(self, data: bool = False):
        self.data = data


class WorldControl:
    def __init__(self):
        self.pause = False
        self.multi_step = 0


class WorldStatistics:
    def __init__(self, ns: int = 0, paused: bool = True):
        self.sim_time = _Stamp(ns)
        self.paused = paused


class Odometry:
    def __init__(self, ns: int, x: float):
        self.header = type("Header", (), {"stamp": _Stamp(ns)})()
        self.pose = type("Pose", (), {"position": _Vector(x, 0.0, -0.1), "orientation": _Vector(0.0, 0.0, 0.0, 1.0)})()
        self.twist = type("Twist", (), {"linear": _Vector(1.0, 0.0, 0.0), "angular": _Vector(0.0, 0.0, 0.0)})()


MESSAGES = {"Boolean": Boolean, "Double": Double, "Odometry": Odometry, "WorldControl": WorldControl, "WorldStatistics": WorldStatistics}
THRUSTER = {"thrust_coefficient": 0.0076, "propeller_diameter": 0.18, "fluid_density": 1025.0, "max_thrust": 300.0}
SKID_MODEL = {"steering_type": "skid", "thrusters": ["port", "stbd"], "helm": False, **THRUSTER}  # a model's entry of the start request
HELM_MODEL = {"steering_type": "rudder", "thrusters": ["center"], "helm": True, **THRUSTER}
DEFAULT_THRUSTERS = ("port", "stbd")


@dataclass
class FakeWorld:
    models: Tuple[str, ...] = ("vessel_0",)
    step_ns: int = 5_000_000
    sim_time_ns: int = 0
    late_iterations: int = 0  # iterations a new thrust takes to reach the Thruster system
    refuse_requests: int = 0  # world control requests left unanswered first (discovery)
    reception_rounds: bool = False
    thrusters: Dict[str, Tuple[str, ...]] = field(default_factory=dict)  # per model, where not port and stbd
    helms: Tuple[str, ...] = ()  # the models with a helm
    queue: List[Tuple[str, float]] = field(default_factory=list)  # command messages not yet handled (reception_rounds)
    subscribers: Dict[str, List[Callable]] = field(default_factory=dict)
    applied: Dict[str, float] = field(default_factory=dict)  # thrust (or helm angle) in effect per topic
    pending: Dict[str, Tuple[int, float]] = field(default_factory=dict)  # topic: (iterations to wait, thrust)
    x: Dict[str, float] = field(default_factory=dict)
    requests: List[int] = field(default_factory=list)

    def deliver(self, topic: str, message) -> None:
        for callback in self.subscribers.get(topic, []):
            callback(message)

    def on_thrust(self, topic: str, value: float) -> None:
        if self.reception_rounds:
            self.queue.append((topic, value))
        elif self.late_iterations:
            self.pending[topic] = (self.late_iterations, value)
        else:
            self.applied[topic] = value

    def control(self, request: WorldControl) -> Tuple[bool, Boolean]:
        if self.refuse_requests:
            self.refuse_requests -= 1
            return False, Boolean(False)
        self.requests.append(request.multi_step)
        if self.queue:
            topic, value = self.queue.pop(0)
            self.applied[topic] = value
        if request.multi_step == 0:
            for topic, value in self.queue:
                self.applied[topic] = value
            self.queue.clear()
        for index in range(request.multi_step):
            self._iterate()
            if index == 0:
                for topic, value in self.queue:
                    self.applied[topic] = value
                self.queue.clear()
        self.deliver("/world/ocean_world/stats", WorldStatistics(self.sim_time_ns, True))
        return True, Boolean(True)

    def _iterate(self) -> None:
        for topic, (wait, value) in list(self.pending.items()):
            if wait <= 0:
                self.applied[topic] = value
                del self.pending[topic]
            else:
                self.pending[topic] = (wait - 1, value)
        for model in self.models:
            for thruster in self.thrusters.get(model, DEFAULT_THRUSTERS):
                thrust = self.applied.get(f"/model/{model}/joint/motor_{thruster}_joint/cmd_thrust", 0.0)
                self.deliver(f"/model/{model}/joint/motor_{thruster}_joint/ang_vel", Double(propeller_speed(thrust, **THRUSTER)))
        self.sim_time_ns += self.step_ns
        for model in self.models:
            total = sum(self.applied.get(f"/model/{model}/joint/motor_{thruster}_joint/cmd_thrust", 0.0) for thruster in self.thrusters.get(model, DEFAULT_THRUSTERS))
            self.x[model] = self.x.get(model, 0.0) + total / 1000.0 * self.step_ns / 1e9
            if self.sim_time_ns % ODOMETRY_PERIOD_NS == 0:
                self.deliver(f"/model/{model}/odometry", Odometry(self.sim_time_ns, self.x[model]))


class FakePublisher:
    def __init__(self, world: FakeWorld, topic: str):
        self.world, self.topic = world, topic

    def publish(self, message) -> None:
        self.world.on_thrust(self.topic, float(message.data))

    def has_connections(self) -> bool:
        """Whether the model has a system listening on the topic: one of its thrusters, or its helm."""
        _, _, model, _, joint, _ = self.topic.split("/")
        if joint == "steering_joint":
            return model in self.world.helms
        return joint in {f"motor_{thruster}_joint" for thruster in self.world.thrusters.get(model, DEFAULT_THRUSTERS)}


class FakeNode:
    def __init__(self, world: FakeWorld):
        self.world = world

    def advertise(self, topic: str, message_type):
        return FakePublisher(self.world, topic)

    def subscribe(self, message_type, topic: str, callback) -> None:
        self.world.subscribers.setdefault(topic, []).append(callback)

    def request(self, service: str, request, request_type, response_type, timeout: int):
        assert service == "/world/ocean_world/control"
        return self.world.control(request)


class FakeTransport:
    """Stands in for the gz.transport13 module: Node() is a node on the fake world."""

    def __init__(self, world: FakeWorld):
        self.world = world

    def Node(self) -> FakeNode:  # noqa: N802  (the gz.transport13 name)
        return FakeNode(self.world)


def expected_speed(thrust: float) -> float:
    return math.copysign(math.sqrt(abs(thrust) / (THRUSTER["fluid_density"] * THRUSTER["thrust_coefficient"] * THRUSTER["propeller_diameter"] ** 4)), thrust)
