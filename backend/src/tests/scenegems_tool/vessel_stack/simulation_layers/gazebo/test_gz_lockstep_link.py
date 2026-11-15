"""gz lockstep link: the runner's side of the actuator protocol, against the actuator on a fake gz sim over a real TCP socket."""

import json
import math
import socket
import threading

import pytest

from scenegems_tool.vessel_stack.control_layers.custom.actuator_allocation import ActuatorCommand
from scenegems_tool.vessel_stack.simulation_layers.gazebo import gz_lockstep_link
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_link import GzLockstepLink, GzLockstepLinkError, HullOdometry, command_message
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_transport_actuator import PROTOCOL_VERSION, GzTransportActuator, InProcessWorldControl, serve_connection, steering_topic, thrust_topic
from tests.scenegems_tool.vessel_stack.simulation_layers.gazebo.fake_gz import HELM_MODEL, MESSAGES, SKID_MODEL, FakeTransport, FakeWorld


def odometry(yaw: float = 0.0, surge: float = 0.0, sway: float = 0.0, yaw_rate: float = 0.0) -> HullOdometry:
    return HullOdometry(1.0, 2.0, -0.1, 0.0, 0.0, math.sin(yaw / 2), math.cos(yaw / 2), surge, sway, 0.0, 0.0, 0.0, yaw_rate)


def command(*thrusts: float, helm=None) -> ActuatorCommand:
    return ActuatorCommand(thrusts=thrusts, helm_angle=helm, force=0.0, moment=0.0, yaw_saturated=False, surge_saturated=False)


class Server:
    """A listening socket on localhost; each accepted connection goes to the next handler."""

    def __init__(self, *handlers):
        self.socket = socket.create_server(("127.0.0.1", 0))
        self.port = self.socket.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, args=(handlers,), daemon=True)
        self.thread.start()

    def _serve(self, handlers):
        for handler in handlers:
            connection, _ = self.socket.accept()
            handler(connection)
        self.socket.close()


def actuator_handler(world: FakeWorld):
    def handle(connection):
        transport = FakeTransport(world)
        serve_connection(GzTransportActuator(transport, MESSAGES, world_control=InProcessWorldControl(transport.Node(), MESSAGES), sleep=lambda _: None), connection)

    return handle


def replying(*replies):
    """A handler that answers every request line with the next reply."""

    def handle(connection):
        reader = connection.makefile("r", encoding="utf-8")
        for reply in replies:
            if not reader.readline():
                break
            connection.sendall((json.dumps(reply) + "\n").encode("utf-8"))
        connection.close()

    return handle


class TestHullOdometry:
    def test_heading_comes_from_the_quaternion(self):
        assert odometry(math.pi / 2).heading == pytest.approx(math.pi / 2)
        assert odometry(-2.5).heading == pytest.approx(-2.5)

    def test_speed_includes_sway(self):
        assert odometry(surge=3.0, sway=4.0).speed == 5.0

    def test_actor_state_and_observation(self):
        hull = odometry(0.3, surge=2.0, yaw_rate=0.1)
        state = hull.actor_state()
        assert (state.x, state.y, state.speed) == (1.0, 2.0, 2.0)
        assert state.heading == pytest.approx(0.3)
        observation = hull.observation()
        assert (observation.surge, observation.yaw_rate) == (2.0, 0.1)
        assert observation.heading == pytest.approx(0.3)

    def test_the_observation_carries_the_sway(self):
        assert odometry(surge=2.0, sway=-0.4).observation().sway == -0.4


class TestCommandMessage:
    def test_a_skid_command_is_its_two_thrusts(self):
        assert command_message(command(100.0, 200.0)) == {"thrust": [100.0, 200.0]}

    def test_a_command_with_a_helm_carries_the_angle(self):
        assert command_message(command(300.0, helm=-0.2)) == {"thrust": [300.0], "helm": -0.2}
        assert command_message(command(300.0, helm=0.0)) == {"thrust": [300.0], "helm": 0.0}, "amidships is an angle, not no helm"


class TestLink:
    def test_start_step_and_close_through_the_actuator(self):
        world = FakeWorld()
        server = Server(actuator_handler(world))
        with GzLockstepLink("127.0.0.1", server.port) as link:
            link.connect(timeout_s=5.0)
            started = link.start({"vessel_0": SKID_MODEL}, step_ns=5_000_000, settle_iterations=40)
            assert started.sim_time_ns == 200_000_000
            assert started.odometry["vessel_0"].x == 0.0
            result = link.step(20, {"vessel_0": command(100.0, 200.0)})
        server.thread.join(5.0)
        assert result.sim_time_ns == 300_000_000
        assert result.odometry["vessel_0"].x == world.x["vessel_0"]
        assert result.late == ()
        assert not server.thread.is_alive(), "close ends the actuator's connection"

    def test_a_thrust_and_a_helm_angle_reach_a_model_with_a_helm(self):
        world = FakeWorld(models=("vessel_0", "vessel_1"), thrusters={"vessel_0": ("center",)}, helms=("vessel_0",), late_iterations=1)
        server = Server(actuator_handler(world))
        with GzLockstepLink("127.0.0.1", server.port) as link:
            link.connect(timeout_s=5.0)
            link.start({"vessel_0": HELM_MODEL, "vessel_1": SKID_MODEL}, step_ns=5_000_000, settle_iterations=40)
            result = link.step(20, {"vessel_0": command(250.0, helm=-0.35), "vessel_1": command(10.0, 20.0)})
        assert world.applied[thrust_topic("vessel_0", "center")] == 250.0
        assert world.applied[steering_topic("vessel_0")] == -0.35
        assert world.applied[thrust_topic("vessel_1", "stbd")] == 20.0
        assert result.late == ("vessel_0/center", "vessel_1/port", "vessel_1/stbd"), "late thrusters by their names; a helm is not checked"

    def test_connect_retries_until_the_actuator_answers_hello(self, monkeypatch):
        """A published Docker port accepts and drops connections before the actuator listens behind it."""
        monkeypatch.setattr(gz_lockstep_link.time, "sleep", lambda _: None)
        server = Server(lambda connection: connection.close(), actuator_handler(FakeWorld()))
        link = GzLockstepLink("127.0.0.1", server.port)
        link.connect(timeout_s=5.0)
        link.close()

    def test_another_protocol_version_is_refused(self):
        server = Server(replying({"op": "hello", "protocol": 99}))
        with pytest.raises(GzLockstepLinkError, match="speaks protocol 99"):
            GzLockstepLink("127.0.0.1", server.port).connect(timeout_s=5.0)

    def test_an_error_reply_raises(self):
        server = Server(replying({"op": "hello", "protocol": PROTOCOL_VERSION}, {"op": "error", "message": "no command for ['vessel_0']"}))
        link = GzLockstepLink("127.0.0.1", server.port)
        link.connect(timeout_s=5.0)
        with pytest.raises(GzLockstepLinkError, match="no command for"):
            link.step(20, {})
        link.close()

    def test_an_actuator_of_protocol_1_is_refused(self):
        """A Gazebo image built before the steering types holds the actuator of protocol 1: the run must not start on it."""
        server = Server(replying({"op": "hello", "protocol": 1}))
        with pytest.raises(GzLockstepLinkError, match="speaks protocol 1, this runner 2"):
            GzLockstepLink("127.0.0.1", server.port).connect(timeout_s=5.0)

    def test_a_request_before_connecting_raises(self):
        with pytest.raises(GzLockstepLinkError, match="not connected"):
            GzLockstepLink("127.0.0.1", 1).step(20, {})
