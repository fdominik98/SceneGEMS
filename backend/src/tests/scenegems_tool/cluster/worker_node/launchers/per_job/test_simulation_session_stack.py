"""The workbench's live session stacks: names from each session's scope, its networks, the ground station ports it
reports, and several sessions side by side on one machine."""

import asyncio
import subprocess
import threading
from types import SimpleNamespace

import pytest

from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope
from scenegems_tool.cluster.worker_node.launchers import compose_project
from scenegems_tool.cluster.worker_node.launchers.per_job import simulation_session_stack as session_stack
from scenegems_tool.cluster.worker_node.launchers.per_job.simulation_session_stack import (
    LEGACY_COMPOSE_PROJECTS,
    SERVICE_NAME,
    SimulationSessionStack,
    build_unified_compose,
    ground_control_services,
    new_live_session_scope,
    session_trajectories_file,
)
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.subsystems.scenario_execution import empty_simulation_session
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, SimulationInstanceConfig, VesselStackConfig
from tests.scenegems_tool.vessel_stack.scenarios import encounter_trajectories, stack_instance
from utils.file_system_utils import docker_volume_path

GEOFENCE = Geofence(57.7, 11.9, 2000.0)
SCOPE = InstanceScope.live_session("m1", "ab12cd34")
VESSEL_STACK = {"services": {"vessel_0": {"image": "sitl", "networks": ["maritime_net"]}}, "networks": {"maritime_net": {"driver": "bridge"}}}


def _connection(topic_prefix: str = "") -> MQttConnectionInfo:
    return MQttConnectionInfo("user", "secret", "broker", "localhost", 1883, False, False, topic_prefix=topic_prefix)


def _unified(stack, config, scope=SCOPE, topic_prefix=""):
    return build_unified_compose(stack, _connection(topic_prefix), GEOFENCE, config, 1, scope)


def test_a_live_session_scope_names_its_stack():
    assert SCOPE.compose_project == "scenegems-m1-workbench-live-ab12cd34"
    assert SCOPE.topic_prefix == "scenegems/m1/workbench/live-ab12cd34/"
    assert session_trajectories_file(SCOPE).endswith("/instances/scenegems-m1-workbench-live-ab12cd34/gen/trajectories.json")


def test_new_scopes_belong_to_the_control_node_and_differ_per_session():
    first, second = new_live_session_scope({"SCENEGEMS_CONTROL_NODE_ID": "m1"}), new_live_session_scope({"SCENEGEMS_CONTROL_NODE_ID": "m1"})
    assert first.control_node_id == second.control_node_id == "m1"
    assert first.worker_node_id == "workbench" and first.instance_id.startswith("live-")
    assert first.compose_project != second.compose_project
    assert new_live_session_scope({}).control_node_id == "local", "a gateway without a control node"


def test_unified_compose_names_everything_from_the_session_scope(monkeypatch):
    monkeypatch.delenv("SCENARIO_EXECUTION_IMAGE", raising=False)
    monkeypatch.delenv("SCENEGEMS_DOCKER_NETWORK", raising=False)
    config = SimulationInstanceConfig(simulation_layer=SimulationLayerId.ARDUPILOT_SIM, environment=EnvironmentConfig.calm())
    compose = _unified(VESSEL_STACK, config)

    service = compose["services"][SERVICE_NAME]
    assert service["container_name"] == "scenegems-m1-workbench-live-ab12cd34-scenario_execution"
    assert service["hostname"] == "scenario_execution"
    assert compose["services"]["vessel_0"]["container_name"] == "scenegems-m1-workbench-live-ab12cd34-vessel_0"
    assert service["image"] == "scenegems-scenario-execution-subsystem:latest"
    assert service["depends_on"] == ["vessel_0"]
    assert service["environment"]["TRAJECTORIES_PATH"] == docker_volume_path(session_trajectories_file(SCOPE))
    assert "MQTT_TOPIC_PREFIX" not in service["environment"]
    assert list(compose["services"]) == ["vessel_0", SERVICE_NAME]
    assert list(compose["networks"]) == ["scenario_execution_net", "maritime_net", "scenegems_broker"]
    assert compose["networks"]["scenario_execution_net"]["name"] == "scenegems-m1-workbench-live-ab12cd34-scenario_execution_net"
    assert compose["networks"]["maritime_net"]["name"] == "scenegems-m1-workbench-live-ab12cd34-maritime_net"
    assert "name" not in VESSEL_STACK["networks"]["maritime_net"], "the generated stack is not changed in place"


def test_on_the_control_node_broker_the_service_gets_the_session_prefix():
    config = SimulationInstanceConfig(simulation_layer=SimulationLayerId.KINEMATIC, environment=EnvironmentConfig.calm())
    compose = _unified({"services": {}, "networks": {}}, config, topic_prefix=SCOPE.topic_prefix)
    assert compose["services"][SERVICE_NAME]["environment"]["MQTT_TOPIC_PREFIX"] == SCOPE.topic_prefix


def test_two_sessions_have_disjoint_names():
    config = SimulationInstanceConfig(simulation_layer=SimulationLayerId.ARDUPILOT_SIM, environment=EnvironmentConfig.calm())
    other = InstanceScope.live_session("m1", "ef56ab78")
    first, second = _unified(VESSEL_STACK, config), _unified(VESSEL_STACK, config, scope=other)

    def names(compose):
        own_networks = {network["name"] for network in compose["networks"].values() if not network.get("external")}
        return {service["container_name"] for service in compose["services"].values()} | own_networks

    assert len(names(first)) == 4, "two containers, two networks"
    assert not names(first) & names(second), "only the external broker network is shared"


def test_the_scenario_execution_service_joins_the_vessel_network_to_drive_the_lockstep_runners():
    config = SimulationInstanceConfig(simulation_layer=SimulationLayerId.ARDUPILOT_SIM, environment=EnvironmentConfig.calm())
    assert "maritime_net" in _unified(VESSEL_STACK, config)["services"][SERVICE_NAME]["networks"]


def test_a_kinematic_session_has_its_simulator_and_an_asv_software_container_per_vessel():
    trajectories = encounter_trajectories("head_on", 20)
    instance = stack_instance(SimulationLayerId.KINEMATIC, [0, 1], control_layer=ControlLayerId.NONE)
    instance.vessels["0"].stack = VesselStackConfig(AsvSoftwareId.USV_NAVIGATION, ControlLayerId.NONE, SimulationLayerId.KINEMATIC)
    _, stack = session_stack.build_simulation_docker_stack_artifacts(instance, trajectories, _connection(), GEOFENCE, embedded_in_subsystem=True, gen_folder=session_stack.session_gen_folder(SCOPE))
    compose = _unified(stack, instance)
    assert list(compose["services"]) == ["agent_0_asv_software", "agent_1_asv_software", "kinematic_sim", SERVICE_NAME], "named by the vessels' agents"
    service = compose["services"][SERVICE_NAME]
    assert service["depends_on"] == ["agent_0_asv_software", "agent_1_asv_software", "kinematic_sim"]
    assert "maritime_net" in service["networks"], "the service steps the containers on the stack's network"
    assert "scenegems-usv-navigation" in compose["services"]["agent_0_asv_software"]["image"]
    assert compose["services"]["kinematic_sim"]["container_name"] == SCOPE.container_name("kinematic_sim")


def test_mission_planner_vessels_on_their_ground_station_port_are_found_by_their_mavproxy():
    instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1])
    operated = instance.vessels["1"]
    operated.stack = VesselStackConfig(AsvSoftwareId.MISSION_PLANNER, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM)
    assert ground_control_services(instance) == {"1": "agent_1_mavproxy"}
    operated.adapter_ids = ("mission_planner_mavlink_port",)
    assert ground_control_services(instance) == {}, "ArduAgent's external mode forwards to a fixed UDP port instead"


def test_only_the_ground_station_ports_are_published_on_the_host():
    instance = stack_instance(SimulationLayerId.GAZEBO, [0, 1])
    instance.vessels["1"].stack = VesselStackConfig(AsvSoftwareId.MISSION_PLANNER, ControlLayerId.ARDUPILOT, SimulationLayerId.GAZEBO)
    _, stack = session_stack.build_simulation_docker_stack_artifacts(
        instance, encounter_trajectories("head_on", 20), _connection(), GEOFENCE, embedded_in_subsystem=True, gen_folder=session_stack.session_gen_folder(SCOPE)
    )
    compose = _unified(stack, instance)
    published = {key: service["ports"] for key, service in compose["services"].items() if "ports" in service}
    assert published == {"agent_1_mavproxy": ["5770"]}, "Docker picks a free host port per session; Gazebo publishes none"


class FakeProject:
    def __init__(self, ports):
        self.ports = ports
        self.asked = []

    def published_port(self, service, container_port):
        self.asked.append((service, container_port))
        return self.ports.get(service)


def test_the_published_ground_station_ports_are_reported_by_agent_id():
    instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0], asv_software=AsvSoftwareId.MISSION_PLANNER)
    reported = []
    stack = SimulationSessionStack.__new__(SimulationSessionStack)
    stack.project = FakeProject({"agent_0_mavproxy": 49153})
    stack._on_ground_control_ports = reported.append
    stack._shutdown = threading.Event()
    stack._report_ground_control_ports(instance)
    assert reported == [{"0": 49153}]
    assert stack.project.asked == [("agent_0_mavproxy", 5770)]


def test_published_port_reads_the_host_port_compose_prints(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="0.0.0.0:49153\n", stderr="")

    monkeypatch.setattr(compose_project.subprocess, "run", fake_run)
    project = compose_project.ComposeProject("p", "/tmp/compose.yml")
    assert project.published_port("agent_0_mavproxy", 5770) == 49153
    assert calls[0][-3:] == ["port", "agent_0_mavproxy", "5770"]
    monkeypatch.setattr(compose_project.subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 1, stdout="", stderr="no port"))
    assert project.published_port("agent_0_mavproxy", 5770) is None


@pytest.fixture
def docker(monkeypatch):
    """The Docker side of the stacks, recorded: which projects were removed, written and started."""
    calls = SimpleNamespace(removed=[], written={}, up=[])
    monkeypatch.setattr(session_stack, "_remove_project", lambda project, folder=None: calls.removed.append(project))
    monkeypatch.setattr(session_stack, "write_simulation_gen_files", lambda writes, folder: None)
    monkeypatch.setattr(SimulationSessionStack, "_verify_gen_files", lambda self, writes: None)
    monkeypatch.setattr(compose_project.ComposeProject, "write", lambda self, compose: calls.written.__setitem__(self.name, compose))
    monkeypatch.setattr(compose_project.ComposeProject, "up", lambda self, *options: calls.up.append(self.name))
    return calls


def _start(scope: InstanceScope) -> SimulationSessionStack:
    config = SimulationInstanceConfig(simulation_layer=SimulationLayerId.KINEMATIC, environment=EnvironmentConfig.calm())
    stack = SimulationSessionStack(_connection(scope.topic_prefix), GEOFENCE, config, encounter_trajectories("head_on", 20), 1, scope=scope)
    stack._spawn_thread.join(timeout=10)
    return stack


def _join_destroys(scope: InstanceScope) -> None:
    for thread in threading.enumerate():
        if thread.name == f"{scope.compose_project}_destroy":
            thread.join(timeout=10)


def test_two_sessions_side_by_side_keep_their_stacks(docker):
    first_scope, second_scope = new_live_session_scope({"SCENEGEMS_CONTROL_NODE_ID": "m1"}), new_live_session_scope({"SCENEGEMS_CONTROL_NODE_ID": "m1"})
    first = _start(first_scope)
    second = _start(second_scope)
    assert docker.up == [first_scope.compose_project, second_scope.compose_project]
    assert first_scope.compose_project not in docker.removed[1:], "starting the second session leaves the first one's stack alone"
    assert docker.removed == [first_scope.compose_project, second_scope.compose_project], "each spawn clears only its own session's leftovers"
    assert docker.written[second_scope.compose_project]["services"][SERVICE_NAME]["environment"]["MQTT_TOPIC_PREFIX"] == second_scope.topic_prefix

    second.destroy()
    _join_destroys(second_scope)
    assert docker.removed[-1] == second_scope.compose_project
    assert docker.removed.count(first_scope.compose_project) == 1, "ending one session never tears down the other"
    first.destroy()
    _join_destroys(first_scope)
    assert docker.removed.count(first_scope.compose_project) == 2


def test_a_replaced_simulation_does_not_tear_down_its_successor(docker):
    scope = new_live_session_scope({"SCENEGEMS_CONTROL_NODE_ID": "m1"})
    previous = _start(scope)
    successor = _start(scope)
    previous.destroy()
    _join_destroys(scope)
    assert docker.removed == [scope.compose_project, scope.compose_project], "only the spawns cleared the session's stack"
    successor.destroy()
    _join_destroys(scope)
    assert docker.removed == [scope.compose_project] * 3


def test_an_empty_simulation_tears_down_its_own_session_stack_only(docker):
    scope, other = new_live_session_scope({"SCENEGEMS_CONTROL_NODE_ID": "m1"}), new_live_session_scope({"SCENEGEMS_CONTROL_NODE_ID": "m1"})
    _start(other)

    async def replace_with_an_empty_simulation():
        empty = empty_simulation_session.EmptySimulationSession(lambda payload: None, session_scope=scope)
        empty.status_update_worker.cancel()

    asyncio.run(replace_with_an_empty_simulation())
    _join_destroys(scope)
    assert docker.removed == [other.compose_project, scope.compose_project]


def test_leftovers_of_an_earlier_process_are_removed_but_not_this_process_stacks(docker, monkeypatch):
    owned = new_live_session_scope({"SCENEGEMS_CONTROL_NODE_ID": "m1"})
    _start(owned)
    leftover = "scenegems-m1-workbench-live-0badf00d"
    asked = []

    def projects(prefix):
        asked.append(prefix)
        return [owned.compose_project, leftover]

    monkeypatch.setattr(session_stack, "compose_projects_with_prefix", projects)
    docker.removed.clear()
    session_stack.remove_leftover_session_stacks("m1")
    assert asked == ["scenegems-m1-workbench-live-"]
    assert docker.removed == [leftover, *LEGACY_COMPOSE_PROJECTS]
