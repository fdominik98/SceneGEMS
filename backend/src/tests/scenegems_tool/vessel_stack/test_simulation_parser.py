"""SimulationParser: ArduAgent clients of a resolved instance, without Docker or a broker."""

from types import SimpleNamespace

import pytest

from concrete_level.models.actor_state import ActorState
from scenegems_tool.messaging.mqtt_agent_client import ExecutionState
from scenegems_tool.vessel_stack import simulation_parser
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentContext, VesselConfig, VesselStackConfig
from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError
from scenegems_tool.vessel_stack.simulation_parser import SimulationParser
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, mqtt_connection, stack_instance


class FakeAgentClient:
    created = []

    def __init__(self, vessel, mqtt_connection, topic, control_mode, agent_name, reference_geofence, initial_state, parent_service_name, mission_waypoints):
        self.actor = vessel
        self.mqtt_connection = mqtt_connection
        self.topic = topic
        self.control_mode = control_mode
        self.agent_name = agent_name
        self.initial_state = initial_state
        self.parent_service_name = parent_service_name
        self.mission_waypoints = mission_waypoints
        self.connected = False
        self.disconnected = False
        self.published_trajectory = None
        self.is_connected = True
        self.position_received = True
        self.is_armable = True
        self.execution_state = ExecutionState.RUNNING
        self.clock = 0.0
        self.current_agent_state = initial_state
        self.start_point_reached = True
        FakeAgentClient.created.append(self)

    def connect(self):
        self.connected = True

    def disconnect(self):
        self.disconnected = True

    def publish_trajectory(self, points):
        self.published_trajectory = points

    def at_start_point(self):
        return self.start_point_reached


@pytest.fixture(autouse=True)
def fake_clients(monkeypatch):
    FakeAgentClient.created = []
    monkeypatch.setattr(simulation_parser, "MqttAgentClient", FakeAgentClient)
    monkeypatch.setattr(simulation_parser, "destroy_simulation_docker_stack", lambda: pytest.fail("the Docker stack must not be touched"))
    yield


PARENT = SimpleNamespace(name="scenario_execution_service", reference_geofence=GEOFENCE)


def parser_for(instance, trajectories=None, connection=None):
    return SimulationParser(instance, trajectories or encounter_trajectories("head_on", 60), connection or mqtt_connection(), PARENT, spawn_docker_stack=False)


ARDUAGENT = ["replay_arduagent_follower"]


def test_one_connected_client_per_vessel_with_its_agent_connection():
    parser = parser_for(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=ARDUAGENT))
    assert [client.agent_name for client in parser.clients] == ["agent_0", "agent_1"]
    assert all(client.connected for client in FakeAgentClient.created)
    assert [client.topic for client in parser.clients] == ["waraps/unit/surface/agent_0", "waraps/unit/surface/agent_1"]
    assert all(client.parent_service_name == "scenario_execution_service" for client in parser.clients)


def test_replay_vessels_run_the_autonomous_control_mode():
    parser = parser_for(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=ARDUAGENT))
    assert {client.control_mode for client in parser.clients} == {"autonomous"}


def test_mission_planner_vessels_run_the_external_control_mode():
    instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], asv_software=AsvSoftwareId.MISSION_PLANNER, adapter_ids=["mission_planner_mavlink_port"])
    assert {client.control_mode for client in parser_for(instance).clients} == {"external"}


def test_mission_planner_on_its_ground_station_port_is_not_an_arduagent_vessel():
    """The default Mission Planner adapter has no ArduAgent; the lockstep driver runs those instances."""
    instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0], asv_software=AsvSoftwareId.MISSION_PLANNER)
    with pytest.raises(StackUnavailableError, match="vessel 0 uses mission_planner_gcs_port"):
        parser_for(instance)


def test_the_trajectory_is_published_as_latitude_longitude_pairs():
    parser = parser_for(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=ARDUAGENT))
    for client in parser.clients:
        assert client.published_trajectory
        assert all(len(point) == 2 for point in client.published_trajectory)
        assert [point["latitude"] for point in client.mission_waypoints] == [point[0] for point in client.published_trajectory]


def test_each_client_starts_from_its_initial_scene_state():
    trajectories = encounter_trajectories("head_on", 60)
    parser = parser_for(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=ARDUAGENT), trajectories)
    by_id = {client.actor.id: client for client in parser.clients}
    assert by_id[1].initial_state.x == 6000.0
    assert by_id[0].initial_state.x == 0.0


def test_the_lockstep_adapter_is_rejected_because_the_worker_drives_vessels_through_arduagent():
    with pytest.raises(StackUnavailableError, match="drives vessels only through ArduAgent: vessel 0 uses replay_mavlink_lockstep"):
        parser_for(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0]))
    assert FakeAgentClient.created == []


def test_unavailable_stacks_are_rejected_before_any_client_exists():
    with pytest.raises(StackUnavailableError, match="Gazebo needs actuator commands"):
        parser_for(stack_instance(SimulationLayerId.GAZEBO, [0, 1], control_layer=ControlLayerId.NONE))
    assert FakeAgentClient.created == []


def test_a_vessel_that_is_not_in_the_scene_is_rejected():
    instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0], adapter_ids=ARDUAGENT)
    instance.vessels["7"] = VesselConfig(
        agent_id="7",
        stack=VesselStackConfig(AsvSoftwareId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM),
        connection=instance.vessels["0"].connection,
        adapter_ids=tuple(ARDUAGENT),
    )
    with pytest.raises(ValueError, match="Vessel with id 7 not found in the scene"):
        parser_for(instance)


def test_os_client_is_the_own_ship():
    parser = parser_for(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=ARDUAGENT))
    assert parser.os_client.actor.id == 0


def test_agents_are_ready_when_connected_armable_and_at_the_start_point():
    parser = parser_for(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=ARDUAGENT))
    assert parser.are_agents_initialized
    assert parser.are_agents_ready
    parser.clients[1].start_point_reached = False
    assert parser.are_agents_initialized
    assert not parser.are_agents_ready


def test_agents_are_not_initialized_until_every_position_arrived():
    parser = parser_for(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=ARDUAGENT))
    parser.clients[0].position_received = False
    assert not parser.are_agents_initialized
    assert not parser.are_agents_ready


def test_agents_are_running_when_every_execution_state_is_running():
    parser = parser_for(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=ARDUAGENT))
    assert parser.are_agents_running
    parser.clients[0].execution_state = ExecutionState.STOPPED
    assert not parser.are_agents_running


def test_current_scene_collects_the_state_of_every_client():
    parser = parser_for(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=ARDUAGENT))
    parser.clients[0].current_agent_state = ActorState(5.0, 6.0, 1.0, 0.0)
    scene = parser.get_current_scene
    assert scene[parser.clients[0].actor].x == 5.0
    assert scene[parser.clients[1].actor].x == 6000.0


def test_simulator_clocks_are_those_reported_by_each_client():
    parser = parser_for(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=ARDUAGENT))
    parser.clients[0].clock = 12.5
    assert parser.simulator_clocks == [12.5, 0.0]


def test_destroy_disconnects_every_client_without_touching_docker_when_no_stack_was_spawned():
    parser = parser_for(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=ARDUAGENT))
    parser.destroy()
    assert all(client.disconnected for client in parser.clients)
    assert parser._shutdown.is_set()


SESSION_PREFIX = "scenegems/m1/workbench/live-ab12cd34/"


def test_the_agents_of_an_instance_of_simulated_vessels_use_the_session_prefix():
    parser = parser_for(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=ARDUAGENT), connection=mqtt_connection().with_topic_prefix(SESSION_PREFIX))
    assert [client.mqtt_connection.topic_prefix for client in parser.clients] == [SESSION_PREFIX, SESSION_PREFIX]
    assert [client.topic for client in parser.clients] == ["waraps/unit/surface/agent_0", "waraps/unit/surface/agent_1"], "the client adds the prefix itself"


def test_with_a_real_vessel_every_agent_client_keeps_the_unscoped_wara_ps_topics():
    instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=ARDUAGENT)
    instance.vessels["1"].context = AgentContext.REAL
    instance.vessels["1"].stack = VesselStackConfig(AsvSoftwareId.REPLAY, ControlLayerId.REAL_VESSEL, SimulationLayerId.REAL_VESSEL)
    instance.vessels["1"].adapter_ids = ("replay_arduagent_real_vessel",)
    session_connection = mqtt_connection().with_topic_prefix(SESSION_PREFIX)
    parser = parser_for(instance, connection=session_connection)
    assert [client.mqtt_connection.topic_prefix for client in parser.clients] == ["", ""], "the real vessel's on-board ArduAgent and the simulated one that watches it"
    assert session_connection.topic_prefix == SESSION_PREFIX, "the service's own connection keeps the session prefix"
