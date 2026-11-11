"""SimulationWorker: which driver runs an instance, and the states a lockstep run publishes."""

import queue
from types import SimpleNamespace

import pytest

from scenegems_tool.gateway.protocol import SimulationStatus
from scenegems_tool.messaging.mqtt_agent_client import MqttAgentClient
from scenegems_tool.subsystems.simulation import simulation_worker
from scenegems_tool.subsystems.simulation.simulation_worker import SimulationWorker
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentContext
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, mqtt_connection, stack_instance


class FakeService:
    def __init__(self, mqtt_connection, reference_geofence):
        self.info_update_rate = 1.0
        self.task_queue = queue.Queue()
        self.states = []

    def publish_simulation_state(self, status, clock, scene):
        self.states.append((status, clock, scene))


class FakeParser:
    def __init__(self, *args, **kwargs):
        self.created = True


@pytest.fixture(autouse=True)
def fake_messaging(monkeypatch):
    monkeypatch.setattr(simulation_worker, "MqttSimulationService", FakeService)
    monkeypatch.setattr(simulation_worker, "SimulationParser", FakeParser)


def worker(instance, timespan=10):
    return SimulationWorker(mqtt_connection(), GEOFENCE, instance, encounter_trajectories("head_on", timespan), 1)


def test_simulated_vessels_run_through_the_lockstep_driver():
    subject = worker(stack_instance(SimulationLayerId.KINEMATIC, [0, 1], control_layer=ControlLayerId.NONE))
    assert subject.lockstep_driver is not None and subject.simulation_parser is None


def test_an_instance_with_a_real_vessel_runs_through_arduagent():
    instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"])
    instance.vessels["1"].context = AgentContext.REAL
    subject = worker(instance)
    assert subject.lockstep_driver is None and isinstance(subject.simulation_parser, FakeParser)


def test_a_lockstep_instance_is_ready_at_once_and_publishes_every_step_while_running():
    subject = worker(stack_instance(SimulationLayerId.KINEMATIC, [0, 1], control_layer=ControlLayerId.NONE, speedup=1000))
    assert subject._compute_status() == SimulationStatus.READY_TO_START
    subject._handle_start_simulation(task=None)
    subject._runtime_thread.join(30.0)
    states = subject.mqtt_service.states
    running = [(clock, scene) for status, clock, scene in states if status == SimulationStatus.RUNNING]
    assert [clock for clock, _ in running] == [float(t) for t in range(11)]
    assert all(scene is not None for _, scene in running)
    assert states[0][0] == SimulationStatus.STARTING
    assert states[-1][0] == SimulationStatus.READY_TO_START, "back to ready when the run ends"


class RecordingAgentClient:
    """An ArduAgent client that records the start commands; its control mode properties are MqttAgentClient's."""

    on_board_control_mode = MqttAgentClient.on_board_control_mode
    external_control_mode = MqttAgentClient.external_control_mode

    def __init__(self, actor, control_mode):
        self.actor = actor
        self.control_mode = control_mode
        self.mission_waypoints = [{"latitude": 57.7, "longitude": 11.9}]
        self.commands = []

    def publish_go_to(self, *args):
        self.commands.append("go_to")

    def publish_follow_path(self, *args):
        self.commands.append("follow_path")


def test_start_commands_every_vessel_but_one_its_on_board_software_steers():
    instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"])
    instance.vessels["1"].context = AgentContext.REAL
    subject = worker(instance)
    scene = subject.trajectories.initial_scene
    clients = [RecordingAgentClient(scene.get_by_id("0"), "autonomous"), RecordingAgentClient(scene.get_by_id("1"), "on_board")]
    subject.simulation_parser = SimpleNamespace(are_agents_ready=True, clients=clients)
    subject.start_scenario()
    assert [client.commands for client in clients] == [["follow_path"], []]
