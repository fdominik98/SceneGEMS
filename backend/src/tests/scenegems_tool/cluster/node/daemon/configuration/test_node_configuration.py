from pathlib import Path

import pytest

from scenegems_tool.cluster.node.daemon.configuration.node_configuration import (
    DEFAULT_REFERENCE_GEOFENCE,
    ConfigurationError,
    NodeConfiguration,
    parse_capabilities,
    parse_geofence,
    parse_labels,
    parse_master_url,
    parse_port,
)
from scenegems_tool.cluster.protocol.jobs import JobType

VALID = {
    "SCENEGEMS_MASTER_URL": "http://192.168.1.10:8443",
    "SCENEGEMS_MASTER_ID": "lab-master",
    "SCENEGEMS_NODE_NAME": "worker-1",
    "SCENEGEMS_NODE_CAPABILITIES": "simulation.kinematic:4,scene_generation:1",
    "SCENEGEMS_NODE_STATE_DIR": "/var/lib/scenegems-node",
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
    configuration = NodeConfiguration.from_values(values(SCENEGEMS_NODE_LABELS="gpu=true, site=lab"))
    assert configuration.master_url == "http://192.168.1.10:8443"
    assert configuration.master_id == "lab-master"
    assert configuration.node_id == configuration.node_name == "worker-1"
    assert (configuration.broker_host, configuration.broker_port) == ("192.168.1.10", 1883)
    assert configuration.capabilities == {JobType.SIMULATION_KINEMATIC: 4, JobType.SCENE_GENERATION: 1}
    assert configuration.labels == {"gpu": "true", "site": "lab"}
    assert configuration.state_dir == Path("/var/lib/scenegems-node")
    assert configuration.reference_geofence == DEFAULT_REFERENCE_GEOFENCE
    assert configuration.docker_name == "scenegems-node-lab-master-worker-1"


def test_the_machine_is_optional_and_trimmed():
    assert NodeConfiguration.from_values(VALID).machine is None
    assert NodeConfiguration.from_values(values(SCENEGEMS_NODE_MACHINE="")).machine is None
    assert NodeConfiguration.from_values(values(SCENEGEMS_NODE_MACHINE=" lab-pc-3 ")).machine == "lab-pc-3"


def test_a_machine_name_longer_than_the_registry_column_is_refused():
    with pytest.raises(ConfigurationError, match="SCENEGEMS_NODE_MACHINE"):
        NodeConfiguration.from_values(values(SCENEGEMS_NODE_MACHINE="m" * 257))


def test_a_node_needs_no_token_certificate_hash_or_trust_folder():
    configuration = NodeConfiguration.from_values(VALID)
    for name in ("pairing_token", "master_ca_sha256", "trust_dir", "trust_source"):
        assert not hasattr(configuration, name), name
    assert "SCENEGEMS_PAIRING_TOKEN" not in VALID and "SCENEGEMS_MASTER_CA_SHA256" not in VALID


def test_the_broker_port_is_optional_and_checked():
    assert NodeConfiguration.from_values(values(SCENEGEMS_BROKER_PORT="11883")).broker_port == 11883
    assert NodeConfiguration.from_values(values(SCENEGEMS_BROKER_PORT="")).broker_port == 1883
    with pytest.raises(ConfigurationError, match="SCENEGEMS_BROKER_PORT"):
        NodeConfiguration.from_values(values(SCENEGEMS_BROKER_PORT="mqtt"))


@pytest.mark.parametrize("text", ["0", "65536", "-1", "x"])
def test_invalid_ports_fail(text):
    with pytest.raises(ValueError):
        parse_port(text)


def test_every_problem_is_reported_at_once():
    with pytest.raises(ConfigurationError) as raised:
        NodeConfiguration.from_values(
            values(SCENEGEMS_MASTER_URL="https://master", SCENEGEMS_MASTER_ID=None, SCENEGEMS_BROKER_PORT="0", SCENEGEMS_NODE_CAPABILITIES="unknown:1", SCENEGEMS_NODE_STATE_DIR=None)
        )
    problems = raised.value.problems
    assert len(problems) == 5
    message = str(raised.value)
    for name in ("SCENEGEMS_MASTER_URL", "SCENEGEMS_MASTER_ID", "SCENEGEMS_BROKER_PORT", "SCENEGEMS_NODE_CAPABILITIES", "SCENEGEMS_NODE_STATE_DIR"):
        assert name in message


@pytest.mark.parametrize("name", ["Worker_1", "-worker", "worker.1", "w" * 64])
def test_node_names_must_be_docker_and_topic_safe(name):
    with pytest.raises(ConfigurationError, match="SCENEGEMS_NODE_NAME"):
        NodeConfiguration.from_values(values(SCENEGEMS_NODE_NAME=name))


def test_a_master_id_must_be_a_scope_name():
    with pytest.raises(ConfigurationError, match="SCENEGEMS_MASTER_ID"):
        NodeConfiguration.from_values(values(SCENEGEMS_MASTER_ID="Lab Master"))


def test_optional_values_are_read():
    configuration = NodeConfiguration.from_values(
        values(
            SCENEGEMS_DOCKER_NETWORK="scenegems-node-lab-master-worker-1",
            SCENEGEMS_NODE_REFERENCE_GEOFENCE="57.7, 11.9, 2000",
            SCENEGEMS_SOFTWARE_REVISION="abc123",
        )
    )
    assert configuration.docker_network == "scenegems-node-lab-master-worker-1"
    assert configuration.reference_geofence == (57.7, 11.9, 2000.0)
    assert configuration.software_revision == "abc123"


@pytest.mark.parametrize(
    "text, expected",
    [("http://master.lan", "http://master.lan"), ("http://Master.LAN:8443/", "http://master.lan:8443"), ("http://[::1]:8443", "http://[::1]:8443")],
)
def test_master_urls_are_normalised(text, expected):
    assert parse_master_url(text) == expected


@pytest.mark.parametrize("text", ["https://master.lan", "http://", "http://master.lan/api", "http://user@master.lan", "http://master.lan:99999", "master.lan:8443"])
def test_invalid_master_urls_fail(text):
    with pytest.raises(ValueError):
        parse_master_url(text)


@pytest.mark.parametrize(
    "text, problem",
    [
        ("", "lists no job type"),
        ("simulation.kinematic", "<job type>:<slots>"),
        ("simulation.kinematic:0", "at least 1"),
        ("simulation.kinematic:two", "whole number"),
        ("simulation.kinematic:1,simulation.kinematic:2", "listed twice"),
        ("simulation:1", "unknown job type"),
    ],
)
def test_invalid_capabilities_fail(text, problem):
    with pytest.raises(ValueError, match=problem):
        parse_capabilities(text)


def test_capabilities_cover_every_job_type():
    text = "scene_generation:1,trajectory_generation:2,simulation.kinematic:3,simulation.ardupilot_sim:1,simulation.gazebo:1,monitoring.post_hoc:5,calibration.deviation:2"
    assert parse_capabilities(text) == {
        JobType.SCENE_GENERATION: 1,
        JobType.TRAJECTORY_GENERATION: 2,
        JobType.SIMULATION_KINEMATIC: 3,
        JobType.SIMULATION_ARDUPILOT_SIM: 1,
        JobType.SIMULATION_GAZEBO: 1,
        JobType.MONITORING_POST_HOC: 5,
        JobType.CALIBRATION_DEVIATION: 2,
    }


def test_the_job_type_of_earlier_releases_names_its_replacements():
    with pytest.raises(ValueError, match="simulation.ardupilot is split into simulation.ardupilot_sim and simulation.gazebo"):
        parse_capabilities("simulation.kinematic:2,simulation.ardupilot:1")


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
    env_file.write_text("".join(f"{key}={value}\n" for key, value in VALID.items()) + "SCENEGEMS_NODE_NAME=from-file\n")
    configuration = NodeConfiguration.load({"SCENEGEMS_ENV_FILE": str(env_file), "SCENEGEMS_NODE_LABELS": "site=env", "SCENEGEMS_MASTER_ID": ""})
    assert configuration.node_name == "from-file"
    assert configuration.labels == {"site": "env"}
    assert configuration.master_id == "lab-master"  # an empty process variable does not hide the file's value


def test_load_fails_for_a_named_env_file_that_does_not_exist(tmp_path):
    with pytest.raises(ConfigurationError, match="no file"):
        NodeConfiguration.load({"SCENEGEMS_ENV_FILE": str(tmp_path / "missing.env")})


def test_load_reports_a_malformed_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SCENEGEMS_NODE_NAME worker\n")
    with pytest.raises(ConfigurationError, match="line 1"):
        NodeConfiguration.load({}, env_file=env_file)


def test_the_artifact_cache_lives_in_the_state_folder_by_default():
    configuration = NodeConfiguration.from_values(values())
    assert configuration.artifact_cache_folder == Path("/var/lib/scenegems-node") / "artifacts"
    assert configuration.artifact_cache_max_bytes == 2 * 1024 * 1024 * 1024
    configured = NodeConfiguration.from_values(values(SCENEGEMS_NODE_ARTIFACT_CACHE_DIR="/cache", SCENEGEMS_NODE_ARTIFACT_CACHE_MAX_BYTES="0"))
    assert (configured.artifact_cache_folder, configured.artifact_cache_max_bytes) == (Path("/cache"), 0)


@pytest.mark.parametrize("text", ["lots", "-1", "1.5"])
def test_an_invalid_artifact_cache_bound_fails(text):
    with pytest.raises(ConfigurationError, match="SCENEGEMS_NODE_ARTIFACT_CACHE_MAX_BYTES"):
        NodeConfiguration.from_values(values(SCENEGEMS_NODE_ARTIFACT_CACHE_MAX_BYTES=text))
