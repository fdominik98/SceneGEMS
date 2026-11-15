"""Drives generated vessel models in a real Gazebo world. It runs inside the Gazebo image, not in the test process.

test_generated_models_in_gazebo.py copies this file into a folder with the world, the models, their hull meshes
and a plan.json, mounts the folder into the image and runs it there with the image's system Python, the only
one that has the gz bindings. So it imports the standard library and the gz bindings and nothing of the backend.

plan.json:

    {"world_file": "ocean_world.sdf", "world": "ocean_world", "step_s": 0.005, "model_files": ["agent_0_model.sdf"],
     "models": {"agent_0": {"odometry": "/model/agent_0/odometry", "joint_state": "/world/ocean_world/model/agent_0/joint_state"}},
     "phases": [{"label": "rest", "seconds": 20, "commands": {"/model/agent_0/joint/motor_center_joint/cmd_thrust": 0.0}}]}

It validates the files with gz sdf, starts the world paused and steps it second by second through the world
control service. Before each second it publishes the phase's commands, gz.msgs.Double on their topics (the
systems of the models keep the last one). After each second it samples every model: pose and body velocities
from its odometry, and the angle and speed of its steering joint if it has one. result.json gets the samples by phase and
model; gz_server.log the server's output.

The world control requests go out from a child process with a node of its own and no subscriptions, as in
gz_transport_actuator.py: from the node that receives the odometry, many of them stay unanswered.
"""

import json
import math
import multiprocessing
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Tuple

STEERING_JOINT = "steering_joint"
SERVER_LOG = "gz_server.log"
REQUEST_TIMEOUT_MS = 5000
STALL_S = 60.0  # wall time one simulated second may take before the step is asked for again
STAMP_TOLERANCE_S = 0.03  # odometry is published every 0.02 s


def validate(files: List[str]) -> Dict[str, str]:
    """What gz sdf -k says about each file: "Valid." for a file libsdformat accepts."""
    verdicts = {}
    for name in files:
        checked = subprocess.run(["gz", "sdf", "-k", name], capture_output=True, text=True)
        verdicts[name] = (checked.stdout + checked.stderr).strip()
    return verdicts


def world_control_process(connection: Any) -> None:
    """Child process: answers each (world, iterations) with whether the paused world took the request to step that far."""
    from gz import transport13
    from gz.msgs10.boolean_pb2 import Boolean
    from gz.msgs10.world_control_pb2 import WorldControl

    node = transport13.Node()
    while True:
        try:
            world, iterations = connection.recv()
        except (EOFError, OSError, KeyboardInterrupt):
            return  # the check is over
        request = WorldControl()
        request.pause = True
        request.multi_step = iterations
        answered, reply = node.request(f"/world/{world}/control", request, WorldControl, Boolean, REQUEST_TIMEOUT_MS)
        connection.send(bool(answered and reply.data))


def stamp_s(message: Any) -> float:
    return message.header.stamp.sec + message.header.stamp.nsec * 1e-9


def state_of(message: Any) -> Dict[str, float]:
    """Pose (roll, pitch and yaw from the quaternion) and body velocities of an odometry message."""
    q = message.pose.orientation
    return {
        "t": stamp_s(message),
        "x": message.pose.position.x,
        "y": message.pose.position.y,
        "z": message.pose.position.z,
        "roll": math.atan2(2 * (q.w * q.x + q.y * q.z), 1 - 2 * (q.x * q.x + q.y * q.y)),
        "pitch": math.asin(max(-1.0, min(1.0, 2 * (q.w * q.y - q.z * q.x)))),
        "yaw": math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z)),
        "u": message.twist.linear.x,
        "v": message.twist.linear.y,
        "r": message.twist.angular.z,
    }


class World:
    """The running world: its models' latest odometry and helm angles, the command publishers and the stepping."""

    def __init__(self, plan: Dict[str, Any], server: subprocess.Popen):
        from gz import transport13
        from gz.msgs10.double_pb2 import Double
        from gz.msgs10.model_pb2 import Model
        from gz.msgs10.odometry_pb2 import Odometry

        self._plan = plan
        self._server = server
        self._double = Double
        self._lock = threading.Lock()
        self._odometry: Dict[str, Any] = {}
        self._helm: Dict[str, Tuple[float, float]] = {}  # angle (rad) and speed (rad/s) of the steering joint
        self._node = transport13.Node()
        for model, topics in plan["models"].items():
            self._node.subscribe(Odometry, topics["odometry"], self._on_odometry(model))
            self._node.subscribe(Model, topics["joint_state"], self._on_joint_state(model))
        topics = sorted({topic for phase in plan["phases"] for topic in phase["commands"]})
        self._publishers = {topic: self._node.advertise(topic, Double) for topic in topics}
        context = multiprocessing.get_context("spawn")
        self._control, child = context.Pipe()
        self._control_process = context.Process(target=world_control_process, args=(child,), daemon=True)
        self._control_process.start()

    def _on_odometry(self, model: str) -> Callable[[Any], None]:
        def callback(message: Any) -> None:
            with self._lock:
                self._odometry[model] = message

        return callback

    def _on_joint_state(self, model: str) -> Callable[[Any], None]:
        def callback(message: Any) -> None:
            for joint in message.joint:
                if joint.name == STEERING_JOINT:
                    with self._lock:
                        self._helm[model] = (joint.axis1.position, joint.axis1.velocity)

        return callback

    def sim_time(self) -> float:
        """The stamp of the oldest of the models' latest odometry; negative until every model has reported."""
        with self._lock:
            if len(self._odometry) < len(self._plan["models"]):
                return -1.0
            return min(stamp_s(message) for message in self._odometry.values())

    def request_steps(self, iterations: int) -> bool:
        self._control.send((self._plan["world"], iterations))
        return bool(self._control.recv())

    def wait_until(self, ready: Callable[[], bool], timeout_s: float, what: str, nudge: Callable[[], Any] = lambda: None) -> None:
        deadline = time.monotonic() + timeout_s
        while not ready():
            if self._server.poll() is not None:
                raise RuntimeError(f"gz sim ended with code {self._server.returncode}")
            if time.monotonic() > deadline:
                raise RuntimeError(what)
            nudge()
            time.sleep(0.1)

    def start(self) -> None:
        """Waits for the world, the first odometry of every model (it comes with the first steps) and a subscriber on every command topic."""
        self.wait_until(lambda: self.request_steps(0), 120.0, "the world control service did not answer")
        self.wait_until(lambda: self.sim_time() >= 0.0, 60.0, "a model published no odometry", nudge=lambda: self.request_steps(4))
        self.wait_until(lambda: all(publisher.has_connections() for publisher in self._publishers.values()), 60.0, "a command topic has no subscriber")

    def publish(self, commands: Dict[str, float]) -> None:
        for topic, value in commands.items():
            message = self._double()
            message.data = float(value)
            self._publishers[topic].publish(message)
        time.sleep(0.02)  # the commands reach gz sim
        self.request_steps(0)  # and are handled before this request, which gz sim takes in turn with them

    def advance(self, seconds: float) -> None:
        """Steps the world until its odometry is `seconds` later. A step request that went unanswered is not repeated while the world moves."""
        target = self.sim_time() + seconds
        while self.sim_time() < target - STAMP_TOLERANCE_S:
            self.request_steps(max(1, round((target - self.sim_time()) / self._plan["step_s"])))
            deadline = time.monotonic() + STALL_S
            while self.sim_time() < target - STAMP_TOLERANCE_S and time.monotonic() < deadline:
                if self._server.poll() is not None:
                    raise RuntimeError(f"gz sim ended with code {self._server.returncode}")
                time.sleep(0.002)

    def sample(self, model: str) -> Dict[str, float]:
        with self._lock:
            state = state_of(self._odometry[model])
            if model in self._helm:
                state["helm"], state["helm_velocity"] = self._helm[model]
        return state

    def run_phase(self, phase: Dict[str, Any]) -> Dict[str, List[Dict[str, float]]]:
        series: Dict[str, List[Dict[str, float]]] = {model: [] for model in self._plan["models"]}
        for _ in range(int(phase["seconds"])):
            self.publish(phase["commands"])
            self.advance(1.0)
            for model in self._plan["models"]:
                series[model].append(self.sample(model))
        return series

    def close(self) -> None:
        self._control_process.terminate()


def main() -> int:
    with open("plan.json", encoding="utf-8") as file:
        plan = json.load(file)
    result: Dict[str, Any] = {"valid": validate([plan["world_file"], *plan["model_files"]]), "phases": {}, "wall_s": {}}
    log = open(SERVER_LOG, "w", encoding="utf-8")
    server = subprocess.Popen(["gz", "sim", "-s", "-v", "2", plan["world_file"]], stdout=log, stderr=subprocess.STDOUT)
    world = World(plan, server)
    try:
        world.start()
        for phase in plan["phases"]:
            started = time.monotonic()
            series = world.run_phase(phase)
            result["phases"][phase["label"]] = series
            result["wall_s"][phase["label"]] = round(time.monotonic() - started, 1)
            print(phase["label"], {model: {key: round(value, 5) for key, value in samples[-1].items()} for model, samples in series.items()}, flush=True)
    except RuntimeError as error:
        result["error"] = str(error)
        print(f"failed: {error}", file=sys.stderr, flush=True)
    finally:
        world.close()
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()
        log.close()
        with open("result.json", "w", encoding="utf-8") as file:
            json.dump(result, file, indent=1)
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
