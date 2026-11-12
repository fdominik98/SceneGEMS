from pathlib import Path

import pytest

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.daemon.configuration.worker_node_configuration import (
    DEFAULT_REFERENCE_GEOFENCE,
    ConfigurationError,
    WorkerNodeConfiguration,
    parse_components,
    parse_control_node_url,
    parse_geofence,
    parse_labels,
    parse_port,
    parse_slots,
    slots_without_components,
)

VALID = {
    "SCENEGEMS_CONTROL_NODE_URL": "http://192.168.1.10:8443",
    "SCENEGEMS_CONTROL_NODE_ID": "lab-control-node",
    "SCENEGEMS_WORKER_NODE_NAME": "worker-1",
    "SCENEGEMS_WORKER_NODE_SLOTS": "simulation:4,scene_generation:1",
    "SCENEGEMS_WORKER_NODE_COMPONENTS": "asv_system/replay,control_layer/none,simulation_layer/kinematic,scene_generation",
    "SCENEGEMS_WORKER_NODE_STATE_DIR": "/var/lib/scenegems-worker-node",
}


def values(**changes):
    result = dict(VALID)
    for key, value in changes.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = value
    return result


def test_a_complete_configuration_parses():
    configuration = WorkerNodeConfiguration.from_values(values(SCENEGEMS_WORKER_NODE_LABELS="gpu=true, site=lab"))
    assert configuration.control_node_url == "http://192.168.1.10:8443"
    assert configuration.control_node_id == "lab-control-node"
    assert configuration.worker_node_id == configuration.worker_node_name == "worker-1"
    assert (configuration.broker_host, configuration.broker_port) == ("192.168.1.10", 1883)
    assert configuration.slots == {JobType.SIMULATION: 4, JobType.SCENE_GENERATION: 1}
    assert configuration.components == {"asv_system/replay", "control_layer/none", "simulation_layer/kinematic", "scene_generation"}
    assert configuration.labels == {"gpu": "true", "site": "lab"}
    assert configuration.state_dir == Path("/var/lib/scenegems-worker-node")
    assert configuration.reference_geofence == DEFAULT_REFERENCE_GEOFENCE
    assert configuration.docker_name == "scenegems-lab-control-node-worker-1"


def test_the_machine_is_optional_and_trimmed():
    assert WorkerNodeConfiguration.from_values(VALID).machine is None
    assert WorkerNodeConfiguration.from_values(values(SCENEGEMS_WORKER_NODE_MACHINE="")).machine is None
    assert WorkerNodeConfiguration.from_values(values(SCENEGEMS_WORKER_NODE_MACHINE=" lab-pc-3 ")).machine == "lab-pc-3"


def test_a_machine_name_longer_than_the_registry_column_is_refused():
    with pytest.raises(ConfigurationError, match="SCENEGEMS_WORKER_NODE_MACHINE"):
        WorkerNodeConfiguration.from_values(values(SCENEGEMS_WORKER_NODE_MACHINE="m" * 257))


def test_a_worker_node_needs_no_token_certificate_hash_or_trust_folder():
    configuration = WorkerNodeConfiguration.from_values(VALID)
    for name in ("pairing_token", "control_node_ca_sha256", "trust_dir", "trust_source"):
        assert not hasattr(configuration, name), name
    assert "SCENEGEMS_PAIRING_TOKEN" not in VALID and "SCENEGEMS_CONTROL_NODE_CA_SHA256" not in VALID


def test_the_broker_port_is_optional_and_checked():
    assert WorkerNodeConfiguration.from_values(values(SCENEGEMS_BROKER_PORT="11883")).broker_port == 11883
    assert WorkerNodeConfiguration.from_values(values(SCENEGEMS_BROKER_PORT="")).broker_port == 1883
    with pytest.raises(ConfigurationError, match="SCENEGEMS_BROKER_PORT"):
        WorkerNodeConfiguration.from_values(values(SCENEGEMS_BROKER_PORT="mqtt"))


@pytest.mark.parametrize("text", ["0", "65536", "-1", "x"])
def test_invalid_ports_fail(text):
    with pytest.raises(ValueError):
        parse_port(text)


def test_every_problem_is_reported_at_once():
    with pytest.raises(ConfigurationError) as raised:
        WorkerNodeConfiguration.from_values(
            values(
                SCENEGEMS_CONTROL_NODE_URL="https://control-node",
                SCENEGEMS_CONTROL_NODE_ID=None,
                SCENEGEMS_BROKER_PORT="0",
                SCENEGEMS_WORKER_NODE_SLOTS="unknown:1",
                SCENEGEMS_WORKER_NODE_COMPONENTS="gpu",
                SCENEGEMS_WORKER_NODE_STATE_DIR=None,
            )
        )
    problems = raised.value.problems
    assert len(problems) == 6
    message = str(raised.value)
    for name in (
        "SCENEGEMS_CONTROL_NODE_URL",
        "SCENEGEMS_CONTROL_NODE_ID",
        "SCENEGEMS_BROKER_PORT",
        "SCENEGEMS_WORKER_NODE_SLOTS",
        "SCENEGEMS_WORKER_NODE_COMPONENTS",
        "SCENEGEMS_WORKER_NODE_STATE_DIR",
    ):
        assert name in message


@pytest.mark.parametrize("name", ["Worker_1", "-worker", "worker.1", "w" * 64])
def test_worker_node_names_must_be_docker_and_topic_safe(name):
    with pytest.raises(ConfigurationError, match="SCENEGEMS_WORKER_NODE_NAME"):
        WorkerNodeConfiguration.from_values(values(SCENEGEMS_WORKER_NODE_NAME=name))


def test_a_control_node_id_must_be_a_scope_name():
    with pytest.raises(ConfigurationError, match="SCENEGEMS_CONTROL_NODE_ID"):
        WorkerNodeConfiguration.from_values(values(SCENEGEMS_CONTROL_NODE_ID="Lab Control node"))


def test_optional_values_are_read():
    configuration = WorkerNodeConfiguration.from_values(
        values(
            SCENEGEMS_DOCKER_NETWORK="scenegems-worker-node-lab-control-node-worker-1",
            SCENEGEMS_WORKER_NODE_REFERENCE_GEOFENCE="57.7, 11.9, 2000",
            SCENEGEMS_SOFTWARE_REVISION="abc123",
        )
    )
    assert configuration.docker_network == "scenegems-worker-node-lab-control-node-worker-1"
    assert configuration.reference_geofence == (57.7, 11.9, 2000.0)
    assert configuration.software_revision == "abc123"


@pytest.mark.parametrize(
    "text, expected",
    [("http://control-node.lan", "http://control-node.lan"), ("http://Control-Node.LAN:8443/", "http://control-node.lan:8443"), ("http://[::1]:8443", "http://[::1]:8443")],
)
def test_control_node_urls_are_normalised(text, expected):
    assert parse_control_node_url(text) == expected


@pytest.mark.parametrize("text", ["https://control-node.lan", "http://", "http://control-node.lan/api", "http://user@control-node.lan", "http://control-node.lan:99999", "control_node.lan:8443"])
def test_invalid_control_node_urls_fail(text):
    with pytest.raises(ValueError):
        parse_control_node_url(text)


@pytest.mark.parametrize(
    "text, problem",
    [
        ("", "lists no job type"),
        ("simulation", "<job type>:<slots>"),
        ("simulation:0", "at least 1"),
        ("simulation:two", "whole number"),
        ("simulation:1,simulation:2", "listed twice"),
        ("rendering:1", "unknown job type"),
    ],
)
def test_invalid_slots_fail(text, problem):
    with pytest.raises(ValueError, match=problem):
        parse_slots(text)


def test_slots_cover_every_job_type():
    text = "scene_generation:1,trajectory_generation:2,simulation:3,monitoring.post_hoc:5,calibration.deviation:2"
    assert parse_slots(text) == {
        JobType.SCENE_GENERATION: 1,
        JobType.TRAJECTORY_GENERATION: 2,
        JobType.SIMULATION: 3,
        JobType.MONITORING_POST_HOC: 5,
        JobType.CALIBRATION_DEVIATION: 2,
    }


@pytest.mark.parametrize("old", ["simulation.kinematic", "simulation.ardupilot", "simulation.ardupilot_sim", "simulation.gazebo"])
def test_the_simulation_job_types_of_earlier_releases_name_their_replacement(old):
    with pytest.raises(ValueError, match=f"{old} is replaced by simulation; give it slots here and list its layers in SCENEGEMS_WORKER_NODE_COMPONENTS"):
        parse_slots(f"scene_generation:1,{old}:2")


def test_the_capabilities_variable_of_earlier_releases_is_refused_naming_its_replacements():
    with pytest.raises(ConfigurationError) as raised:
        WorkerNodeConfiguration.from_values(values(SCENEGEMS_WORKER_NODE_CAPABILITIES="simulation.kinematic:2", SCENEGEMS_WORKER_NODE_SLOTS=None, SCENEGEMS_WORKER_NODE_COMPONENTS=None))
    message = str(raised.value)
    assert "SCENEGEMS_WORKER_NODE_CAPABILITIES is replaced by SCENEGEMS_WORKER_NODE_SLOTS" in message and "SCENEGEMS_WORKER_NODE_COMPONENTS (what the worker node runs them with" in message
    with pytest.raises(ConfigurationError, match="SCENEGEMS_WORKER_NODE_CAPABILITIES is replaced"):
        WorkerNodeConfiguration.from_values(values(SCENEGEMS_WORKER_NODE_CAPABILITIES="simulation:2"))


def test_components_are_the_catalogs():
    assert parse_components(" control_layer/ardupilot , simulation_layer/gazebo,asv_system/replay ") == {"control_layer/ardupilot", "simulation_layer/gazebo", "asv_system/replay"}
    with pytest.raises(ValueError, match="unknown component 'simulation.kinematic'"):
        parse_components("simulation.kinematic")
    with pytest.raises(ValueError, match="listed twice"):
        parse_components("monitoring,monitoring")
    with pytest.raises(ValueError, match="lists no component"):
        parse_components(" , ")


def test_a_job_type_with_slots_needs_a_component_that_serves_it():
    assert slots_without_components({JobType.SIMULATION: 1, JobType.MONITORING_POST_HOC: 1}, frozenset({"simulation_layer/gazebo", "monitoring"})) == []
    problems = slots_without_components({JobType.SIMULATION: 1, JobType.CALIBRATION_DEVIATION: 1}, frozenset({"asv_system/replay", "control_layer/ardupilot"}))
    assert problems[0].startswith("simulation needs a simulation layer among SCENEGEMS_WORKER_NODE_COMPONENTS")
    assert problems[1] == "calibration.deviation needs the component calibration among SCENEGEMS_WORKER_NODE_COMPONENTS"
    with pytest.raises(ConfigurationError, match="SCENEGEMS_WORKER_NODE_SLOTS: monitoring.post_hoc needs the component monitoring"):
        WorkerNodeConfiguration.from_values(values(SCENEGEMS_WORKER_NODE_SLOTS="monitoring.post_hoc:1"))


@pytest.mark.parametrize("text", ["gpu", "gpu=", "=true", "gpu=true,gpu=false", "g pu=true"])
def test_invalid_labels_fail(text):
    with pytest.raises(ValueError):
        parse_labels(text)


@pytest.mark.parametrize("text", ["57.7,11.9", "a,b,c", "91,0,10", "57,11,0"])
def test_invalid_geofences_fail(text):
    with pytest.raises(ValueError):
        parse_geofence(text)


def test_load_reads_the_env_file_and_the_environment_wins(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("".join(f"{key}={value}\n" for key, value in VALID.items()) + "SCENEGEMS_WORKER_NODE_NAME=from-file\n")
    configuration = WorkerNodeConfiguration.load({"SCENEGEMS_ENV_FILE": str(env_file), "SCENEGEMS_WORKER_NODE_LABELS": "site=env", "SCENEGEMS_CONTROL_NODE_ID": ""})
    assert configuration.worker_node_name == "from-file"
    assert configuration.labels == {"site": "env"}
    assert configuration.control_node_id == "lab-control-node"  # an empty process variable does not hide the file's value


def test_load_fails_for_a_named_env_file_that_does_not_exist(tmp_path):
    with pytest.raises(ConfigurationError, match="no file"):
        WorkerNodeConfiguration.load({"SCENEGEMS_ENV_FILE": str(tmp_path / "missing.env")})


def test_load_reports_a_malformed_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SCENEGEMS_WORKER_NODE_NAME worker\n")
    with pytest.raises(ConfigurationError, match="line 1"):
        WorkerNodeConfiguration.load({}, env_file=env_file)


def test_the_artifact_cache_lives_in_the_state_folder_by_default():
    configuration = WorkerNodeConfiguration.from_values(values())
    assert configuration.artifact_cache_folder == Path("/var/lib/scenegems-worker-node") / "artifacts"
    assert configuration.artifact_cache_max_bytes == 2 * 1024 * 1024 * 1024
    configured = WorkerNodeConfiguration.from_values(values(SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_DIR="/cache", SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES="0"))
    assert (configured.artifact_cache_folder, configured.artifact_cache_max_bytes) == (Path("/cache"), 0)


@pytest.mark.parametrize("text", ["lots", "-1", "1.5"])
def test_an_invalid_artifact_cache_bound_fails(text):
    with pytest.raises(ConfigurationError, match="SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES"):
        WorkerNodeConfiguration.from_values(values(SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES=text))
