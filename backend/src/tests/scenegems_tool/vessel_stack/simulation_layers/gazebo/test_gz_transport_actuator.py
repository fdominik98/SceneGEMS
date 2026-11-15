"""gz-transport actuator: thrust, helm, stepping and odometry on a fake gz sim, the late-thrust check, and the line protocol."""

import json
import socket
import threading

import pytest

from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators import vessel_model_generator
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_transport_actuator import (
    PROTOCOL_VERSION,
    ActuatorError,
    GzTransportActuator,
    InProcessWorldControl,
    ang_vel_topic,
    odometry_topic,
    propeller_speed,
    serve_connection,
    steering_topic,
    thrust_topic,
)
from tests.scenegems_tool.vessel_stack.simulation_layers.gazebo.fake_gz import HELM_MODEL, MESSAGES, SKID_MODEL, THRUSTER, FakeTransport, FakeWorld, expected_speed

HELM = steering_topic("vessel_0")


def actuator(world: FakeWorld, reply_timeout_s: float = 5.0) -> GzTransportActuator:
    transport = FakeTransport(world)
    node = transport.Node()
    return GzTransportActuator(transport, MESSAGES, world_control=InProcessWorldControl(node, MESSAGES), sleep=lambda _: None, reply_timeout_s=reply_timeout_s)


def start(adapter: GzTransportActuator, settle: int = 400, model=SKID_MODEL):
    return adapter.start({"step_ns": 5_000_000, "settle_iterations": settle, "models": {"vessel_0": model}})


def helm_world(**kwargs) -> FakeWorld:
    """A world whose vessel_0 has one thruster and a helm, as a hull with a rudder or vectored thrust."""
    return FakeWorld(thrusters={"vessel_0": ("center",)}, helms=("vessel_0",), **kwargs)


def skid(port: float, starboard: float):
    return {"vessel_0": {"thrust": [port, starboard]}}


class TestTopics:
    def test_topics_follow_the_thruster_and_odometry_systems(self):
        assert thrust_topic("vessel_0", "port") == "/model/vessel_0/joint/motor_port_joint/cmd_thrust"
        assert ang_vel_topic("vessel_0", "stbd") == "/model/vessel_0/joint/motor_stbd_joint/ang_vel"
        assert odometry_topic("vessel_0") == "/model/vessel_0/odometry"
        assert steering_topic("vessel_0") == "/model/vessel_0/joint/steering_joint/cmd_pos"

    @pytest.mark.parametrize("steering", ["skid", "rudder", "vectored_thrust"])
    def test_the_command_topics_are_the_model_generators(self, steering):
        """The actuator builds its topic names itself (it runs without the backend); they must stay the generated model's."""
        for thruster in vessel_model_generator.thruster_names(steering):
            assert thrust_topic("agent_3", thruster) == vessel_model_generator.thrust_topic("agent_3", thruster)
        assert steering_topic("agent_3") == vessel_model_generator.steering_topic("agent_3")

    def test_propeller_speed_is_the_thrusters_and_clamped_to_its_limit(self):
        assert propeller_speed(100.0, **THRUSTER) == pytest.approx(expected_speed(100.0))
        assert propeller_speed(-100.0, **THRUSTER) == pytest.approx(-expected_speed(100.0))
        assert propeller_speed(1e6, **THRUSTER) == pytest.approx(expected_speed(THRUSTER["max_thrust"]))


class TestStart:
    def test_start_settles_without_thrust_and_reports_the_odometry_at_the_end(self):
        world = FakeWorld()
        state = start(actuator(world))
        assert state["op"] == "state"
        assert state["sim_time_ns"] == 400 * 5_000_000
        assert state["odometry"]["vessel_0"][0] == 0.0
        assert state["late"] == []
        assert world.requests == [0, 0, 400], "a pause without iterations first, then the settling step after its barrier"

    def test_a_world_stepped_before_lines_up_from_its_statistics(self):
        world = FakeWorld(sim_time_ns=1_000_000_000)
        assert start(actuator(world))["sim_time_ns"] == 1_000_000_000 + 400 * 5_000_000

    def test_an_unanswered_first_request_is_repeated_before_any_iteration(self):
        world = FakeWorld(refuse_requests=3)
        start(actuator(world))
        assert world.requests == [0, 0, 400]

    def test_a_model_with_a_helm_settles_with_the_helm_amidships(self):
        world = helm_world()
        world.applied[HELM] = 0.3  # left over from an earlier run
        state = start(actuator(world), model=HELM_MODEL)
        assert world.applied == {HELM: 0.0, thrust_topic("vessel_0", "center"): 0.0}
        assert state["late"] == []

    def test_a_thruster_the_model_does_not_have_is_an_error(self):
        """The runner derived another steering type than the model in the world has: nothing listens on the thrust topic."""
        adapter = actuator(FakeWorld(), reply_timeout_s=0.05)
        with pytest.raises(ActuatorError, match="did not subscribe to the command topics"):
            start(adapter, model=HELM_MODEL)

    @pytest.mark.parametrize("thrusters", [[], ["port", "port"]])
    def test_a_model_needs_its_thrusters_named_once(self, thrusters):
        with pytest.raises(ActuatorError, match="at least one thruster and each one once"):
            start(actuator(FakeWorld()), model={**SKID_MODEL, "thrusters": thrusters})


class TestStep:
    def test_a_step_applies_the_thrust_for_exactly_its_iterations(self):
        world = FakeWorld()
        adapter = actuator(world)
        start(adapter)
        state = adapter.step({"iterations": 20, "commands": skid(200.0, 300.0)})
        assert state["sim_time_ns"] == 420 * 5_000_000
        assert state["odometry"]["vessel_0"][0] == pytest.approx(0.5 * 0.1)
        assert state["late"] == []

    def test_a_thrust_that_arrives_after_the_first_iteration_is_reported_late(self):
        world = FakeWorld(late_iterations=2)
        adapter = actuator(world)
        start(adapter)
        assert adapter.step({"iterations": 20, "commands": skid(200.0, 200.0)})["late"] == ["vessel_0/port", "vessel_0/stbd"]
        assert adapter.step({"iterations": 20, "commands": skid(200.0, 200.0)})["late"] == [], "an unchanged thrust is in effect"

    def test_every_step_sends_a_barrier_before_its_iterations(self):
        world = FakeWorld()
        adapter = actuator(world)
        start(adapter)
        adapter.step({"iterations": 20, "commands": skid(1.0, 2.0)})
        assert world.requests[-2:] == [0, 20]

    def test_the_barrier_lets_gz_sim_handle_both_thrusts_before_the_step(self):
        """Without the barrier the step request would be handled with the second thrust message still queued."""
        world = FakeWorld(reception_rounds=True)
        adapter = actuator(world)
        start(adapter)
        assert adapter.step({"iterations": 20, "commands": skid(200.0, 300.0)})["late"] == []

    def test_a_thrust_beyond_the_limit_is_checked_against_the_clamped_thrust(self):
        world = FakeWorld()
        adapter = actuator(world)
        start(adapter)
        world.on_thrust = lambda topic, value: world.applied.__setitem__(topic, max(-300.0, min(300.0, value)))
        assert adapter.step({"iterations": 4, "commands": skid(5000.0, -5000.0)})["late"] == []

    def test_every_model_needs_a_command(self):
        adapter = actuator(FakeWorld())
        start(adapter)
        with pytest.raises(ActuatorError, match="no command for"):
            adapter.step({"iterations": 4, "commands": {}})

    def test_a_step_needs_iterations(self):
        adapter = actuator(FakeWorld())
        start(adapter)
        with pytest.raises(ActuatorError, match="at least one iteration"):
            adapter.step({"iterations": 0, "commands": skid(0.0, 0.0)})

    def test_a_step_off_the_odometry_period_is_an_error(self):
        """5 iterations end at 25 ms, between the odometry stamps every 20 ms: no odometry ever matches the step's end."""
        adapter = actuator(FakeWorld(), reply_timeout_s=0.05)
        start(adapter)
        with pytest.raises(ActuatorError, match="no odometry at 2025000000 ns.*multiple of the odometry period"):
            adapter.step({"iterations": 5, "commands": skid(0.0, 0.0)})

    def test_a_world_with_another_physics_step_is_an_error(self):
        """The runner asks for 5 ms iterations, the world takes 10 ms: the odometry lands past the step's end."""
        adapter = actuator(FakeWorld(step_ns=10_000_000))
        with pytest.raises(ActuatorError, match="not stamped at the step's end"):
            start(adapter, settle=4)

    def test_a_world_that_never_answers_is_an_error(self):
        adapter = actuator(FakeWorld(refuse_requests=10**9), reply_timeout_s=0.05)
        with pytest.raises(ActuatorError, match="did not answer within"):
            start(adapter)


class TestHelm:
    def test_a_step_applies_the_one_thrust_and_the_helm_angle(self):
        world = helm_world()
        adapter = actuator(world)
        start(adapter, model=HELM_MODEL)
        state = adapter.step({"iterations": 20, "commands": {"vessel_0": {"thrust": [250.0], "helm": -0.4}}})
        assert world.applied == {HELM: -0.4, thrust_topic("vessel_0", "center"): 250.0}
        assert state["odometry"]["vessel_0"][0] == pytest.approx(0.25 * 0.1), "one thruster moves the hull"
        assert state["late"] == []

    def test_a_late_thrust_is_reported_by_the_thrusters_name(self):
        world = helm_world(late_iterations=2)
        adapter = actuator(world)
        start(adapter, model=HELM_MODEL)
        assert adapter.step({"iterations": 20, "commands": {"vessel_0": {"thrust": [200.0], "helm": 0.1}}})["late"] == ["vessel_0/center"]

    def test_a_late_helm_is_not_reported(self):
        """Nothing tells the actuator which angle the helm's controller had in an iteration, so only thrusters are checked."""
        world = helm_world(late_iterations=2)
        adapter = actuator(world)
        start(adapter, model=HELM_MODEL)
        assert adapter.step({"iterations": 20, "commands": {"vessel_0": {"thrust": [0.0], "helm": 0.5}}})["late"] == []
        assert world.applied[HELM] == 0.5

    def test_the_barrier_covers_the_helm_message_too(self):
        """The reception thread takes one message per round: the helm and the thrust are both handled before the step's first iteration."""
        world = helm_world(reception_rounds=True)
        adapter = actuator(world)
        start(adapter, model=HELM_MODEL)
        seen = []
        world.subscribers.setdefault(ang_vel_topic("vessel_0", "center"), []).append(lambda message: seen.append(world.applied.get(HELM)))
        assert adapter.step({"iterations": 20, "commands": {"vessel_0": {"thrust": [200.0], "helm": 0.2}}})["late"] == []
        assert seen[0] == 0.2, "the helm angle in effect in the step's first iteration"

    def test_a_model_with_a_helm_needs_a_helm_angle(self):
        adapter = actuator(helm_world())
        start(adapter, model=HELM_MODEL)
        with pytest.raises(ActuatorError, match="has a helm and got no helm angle"):
            adapter.step({"iterations": 4, "commands": {"vessel_0": {"thrust": [1.0]}}})

    def test_a_model_without_a_helm_takes_no_helm_angle(self):
        adapter = actuator(FakeWorld())
        start(adapter)
        with pytest.raises(ActuatorError, match="has no helm and got a helm angle"):
            adapter.step({"iterations": 4, "commands": {"vessel_0": {"thrust": [1.0, 1.0], "helm": 0.1}}})

    def test_a_model_takes_one_thrust_per_thruster(self):
        world = helm_world()
        adapter = actuator(world)
        start(adapter, model=HELM_MODEL)
        with pytest.raises(ActuatorError, match=r"has the thrusters \['center'\], got 2 thrusts"):
            adapter.step({"iterations": 4, "commands": {"vessel_0": {"thrust": [1.0, 1.0], "helm": 0.0}}})
        assert world.applied[thrust_topic("vessel_0", "center")] == 0.0, "nothing is published from a refused step"

    def test_models_of_different_steering_types_step_together(self):
        world = FakeWorld(models=("vessel_0", "vessel_1"), thrusters={"vessel_0": ("center",)}, helms=("vessel_0",))
        adapter = actuator(world)
        adapter.start({"step_ns": 5_000_000, "settle_iterations": 40, "models": {"vessel_0": HELM_MODEL, "vessel_1": SKID_MODEL}})
        state = adapter.step({"iterations": 20, "commands": {"vessel_0": {"thrust": [100.0], "helm": 0.3}, "vessel_1": {"thrust": [200.0, 300.0]}}})
        assert state["odometry"]["vessel_0"][0] == pytest.approx(0.1 * 0.1)
        assert state["odometry"]["vessel_1"][0] == pytest.approx(0.5 * 0.1)
        assert world.applied[HELM] == 0.3 and state["late"] == []


class TestProtocol:
    def serve(self, world: FakeWorld):
        server, client = socket.socketpair()
        thread = threading.Thread(target=serve_connection, args=(actuator(world), server), daemon=True)
        thread.start()
        reader = client.makefile("r", encoding="utf-8")
        writer = client.makefile("w", encoding="utf-8")

        def exchange(request):
            writer.write(json.dumps(request) + "\n")
            writer.flush()
            return json.loads(reader.readline())

        return exchange, client, thread

    def test_hello_start_step_and_close(self):
        exchange, client, thread = self.serve(FakeWorld())
        assert PROTOCOL_VERSION == 2
        assert exchange({"op": "hello"}) == {"op": "hello", "protocol": PROTOCOL_VERSION}
        assert exchange({"op": "start", "step_ns": 5_000_000, "settle_iterations": 40, "models": {"vessel_0": SKID_MODEL}})["sim_time_ns"] == 200_000_000
        reply = exchange({"op": "step", "iterations": 20, "commands": skid(100.0, 100.0)})
        assert reply["op"] == "state" and reply["sim_time_ns"] == 300_000_000
        client.sendall(b'{"op": "close"}\n')
        thread.join(5.0)
        assert not thread.is_alive()

    def test_a_helm_angle_travels_as_a_number_and_no_helm_as_null_or_nothing(self):
        world = FakeWorld(models=("vessel_0", "vessel_1"), thrusters={"vessel_0": ("center",)}, helms=("vessel_0",))
        exchange, client, _ = self.serve(world)
        exchange({"op": "start", "step_ns": 5_000_000, "settle_iterations": 4, "models": {"vessel_0": HELM_MODEL, "vessel_1": SKID_MODEL}})
        reply = exchange({"op": "step", "iterations": 4, "commands": {"vessel_0": {"thrust": [1.0], "helm": 0.1 + 0.2}, "vessel_1": {"thrust": [1.0, 2.0], "helm": None}}})
        assert reply["op"] == "state" and world.applied[HELM] == 0.1 + 0.2
        client.close()

    def test_floats_travel_bit_for_bit(self):
        exchange, client, _ = self.serve(FakeWorld())
        exchange({"op": "start", "step_ns": 5_000_000, "settle_iterations": 4, "models": {"vessel_0": SKID_MODEL}})
        reply = exchange({"op": "step", "iterations": 4, "commands": skid(0.1 + 0.2, 1.0 / 3.0)})
        assert reply["odometry"]["vessel_0"][0] == (0.1 + 0.2 + 1.0 / 3.0) / 1000.0 * 0.02
        client.close()

    def test_a_protocol_1_start_is_refused(self):
        """Protocol 1 gave the models under "thrusters", with two thrusters each."""
        exchange, client, thread = self.serve(FakeWorld())
        reply = exchange({"op": "start", "step_ns": 5_000_000, "settle_iterations": 4, "thrusters": {"vessel_0": THRUSTER}})
        assert reply["op"] == "error" and "models" in reply["message"]
        thread.join(5.0)
        client.close()

    def test_an_error_is_answered_and_ends_the_connection(self):
        exchange, client, thread = self.serve(FakeWorld())
        reply = exchange({"op": "fly"})
        assert reply["op"] == "error" and "unknown op 'fly'" in reply["message"]
        thread.join(5.0)
        assert not thread.is_alive()
        client.close()
