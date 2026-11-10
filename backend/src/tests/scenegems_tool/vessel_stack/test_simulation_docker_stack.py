"""Snapshots of the generated Docker stacks (compose file, world, vessel model, ArduPilot parameters).

The data files under data/stacks/<case>/ record the generator's output. A deliberate change of the
generators, container names or topics changes them: run `pytest --update-snapshots` on this file,
review the diff of the data files and commit them with the change.
"""

import pytest

from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentContext, VesselStackConfig
from scenegems_tool.vessel_stack.simulation_docker_stack import SIMULATION_COMPOSE_PROJECT, build_simulation_docker_stack_artifacts
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, mqtt_connection, stack_instance
from tests.scenegems_tool.vessel_stack.stack_cases import CASE_NAMES

SNAPSHOT_FILES = {
    "gazebo_lockstep_wind": ("ocean_world.sdf", "agent_0_model.sdf", "params-agent_0.params"),
    "ardupilot_sim_lockstep": ("ocean_world.sdf", "agent_0_model.sdf", "params-agent_0.params"),
    "ardupilot_sim_arduagent": ("params-agent_0.params", "params-agent_1.params"),
}


@pytest.mark.parametrize("case", CASE_NAMES)
def test_compose_file_matches_snapshot(stacks, snapshot, case):
    snapshot.check(f"stacks/{case}/docker-compose.yml", stacks[case].compose_yaml)


@pytest.mark.parametrize("case", CASE_NAMES)
def test_generated_files_match_snapshots(stacks, snapshot, case):
    for name in SNAPSHOT_FILES[case]:
        snapshot.check(f"stacks/{case}/{name}", stacks[case].files[name])


@pytest.mark.parametrize("case", CASE_NAMES)
def test_written_files_match_snapshot_list(stacks, snapshot, case):
    snapshot.check(f"stacks/{case}/written_files.txt", "\n".join(stacks[case].pending_paths))


@pytest.mark.parametrize("case", CASE_NAMES)
def test_generation_is_deterministic(stacks, case):
    from tests.scenegems_tool.vessel_stack.stack_cases import generate_stack

    again = generate_stack(case)
    assert again.files == stacks[case].files
    assert again.compose == stacks[case].compose


@pytest.mark.parametrize("case", CASE_NAMES)
def test_trajectories_are_written_last_for_the_worker(stacks, case):
    assert stacks[case].pending_paths[-1] == "trajectories.json"


@pytest.mark.parametrize("case", CASE_NAMES)
def test_every_service_joins_the_maritime_network(stacks, case):
    compose = stacks[case].compose
    assert compose["networks"] == {"maritime_net": {"name": SIMULATION_COMPOSE_PROJECT, "driver": "bridge"}}
    for service in compose["services"].values():
        assert service["networks"] == ["maritime_net"]


def test_embedded_stack_uses_an_unnamed_network():
    from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, mqtt_connection
    from tests.scenegems_tool.vessel_stack.stack_cases import _instance

    _, compose = build_simulation_docker_stack_artifacts(_instance("ardupilot_sim_lockstep"), encounter_trajectories("head_on", 10), mqtt_connection(), GEOFENCE, embedded_in_subsystem=True)
    assert compose["networks"] == {"maritime_net": {"driver": "bridge"}}


def test_unavailable_stack_is_rejected_before_anything_is_generated():
    from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, SimulationLayerId
    from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError
    from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, mqtt_connection, stack_instance

    instance = stack_instance(SimulationLayerId.GAZEBO, [0, 1], control_layer=ControlLayerId.NONE)
    with pytest.raises(StackUnavailableError, match="Gazebo needs actuator commands"):
        build_simulation_docker_stack_artifacts(instance, encounter_trajectories("head_on", 10), mqtt_connection(), GEOFENCE)


def test_an_unsupported_environment_is_rejected_before_anything_is_generated():
    import numpy as np

    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
    from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError
    from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, mqtt_connection, stack_instance

    environment = EnvironmentConfig.calm()
    environment.wind_vector = np.array([0.0, 5.0, 0.0])  # SITL's boat measured no effect of wind
    with pytest.raises(StackUnavailableError, match="does not support wind"):
        build_simulation_docker_stack_artifacts(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0], environment=environment), encounter_trajectories("head_on", 10), mqtt_connection(), GEOFENCE)


SESSION_PREFIX = "scenegems/m1/workbench/live-ab12cd34/"


def _arduagent_environments(instance, connection):
    _, compose = build_simulation_docker_stack_artifacts(instance, encounter_trajectories("head_on", 20), connection, GEOFENCE, embedded_in_subsystem=True)
    return {key: dict(item.split("=", 1) for item in service["environment"]) for key, service in compose["services"].items() if key.endswith("_arduagent")}


def test_arduagent_containers_of_simulated_vessels_get_the_session_prefix():
    instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"])
    environments = _arduagent_environments(instance, mqtt_connection().with_topic_prefix(SESSION_PREFIX))
    assert {key: environment.get("MQTT_TOPIC_PREFIX") for key, environment in environments.items()} == {"agent_0_arduagent": SESSION_PREFIX, "agent_1_arduagent": SESSION_PREFIX}
    assert all("MQTT_TOPIC_PREFIX" not in environment for environment in _arduagent_environments(instance, mqtt_connection()).values()), "unscoped without a prefix"


def test_arduagent_containers_next_to_a_real_vessel_stay_unscoped():
    instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"])
    instance.vessels["1"].context = AgentContext.REAL
    instance.vessels["1"].stack = VesselStackConfig(AsvSystemId.REPLAY, ControlLayerId.REAL_VESSEL, SimulationLayerId.REAL_VESSEL)
    instance.vessels["1"].adapter_ids = ("replay_arduagent_real_vessel",)
    environments = _arduagent_environments(instance, mqtt_connection().with_topic_prefix(SESSION_PREFIX))
    assert list(environments) == ["agent_0_arduagent"], "the real vessel runs its own ArduAgent"
    assert "MQTT_TOPIC_PREFIX" not in environments["agent_0_arduagent"]


def test_gazebo_has_no_fixed_container_name_and_no_host_port(stacks):
    gazebo = stacks["gazebo_lockstep_wind"].compose["services"]["gazebo"]
    assert gazebo["hostname"] == "gazebo", "SITL and the lockstep runners reach it by that name on the stack network"
    assert "container_name" not in gazebo and "ports" not in gazebo
