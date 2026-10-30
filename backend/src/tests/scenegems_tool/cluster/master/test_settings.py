from pathlib import Path

import pytest

from scenegems_tool.cluster.master.settings import DEFAULT_OPERATOR_ALLOWED_ORIGINS, ArtifactSettings, BrokerClientSettings, Listener, MasterSettings, SettingMissing, parse_allowed_origins

REQUIRED = {
    "SCENEGEMS_MASTER_ID": "lab-master",
    "SCENEGEMS_DATABASE_URL": "postgresql+psycopg://scenegems:secret@postgres:5432/scenegems",
}


def test_defaults():
    settings = MasterSettings.from_environment(REQUIRED)
    assert settings.master_id == "lab-master"
    assert (settings.node_api, settings.operator) == (Listener("0.0.0.0", 8443), Listener("127.0.0.1", 5174))
    assert settings.release_manifest is None
    assert settings.artifacts == ArtifactSettings(Path("/var/lib/scenegems/artifacts"), 256 * 1024 * 1024, 600.0, 3600.0)
    assert settings.broker is None


def test_the_operator_allows_the_ui_dev_server_by_default():
    assert MasterSettings.from_environment(REQUIRED).operator_allowed_origins == ("http://localhost:5173", "http://127.0.0.1:5173") == DEFAULT_OPERATOR_ALLOWED_ORIGINS
    assert MasterSettings.from_environment(dict(REQUIRED, SCENEGEMS_OPERATOR_ALLOWED_ORIGINS="  ")).operator_allowed_origins == DEFAULT_OPERATOR_ALLOWED_ORIGINS


def test_the_allowed_origins_are_a_comma_separated_list():
    environ = dict(REQUIRED, SCENEGEMS_OPERATOR_ALLOWED_ORIGINS="https://ui.lab.example, http://10.88.0.9:8080/ ,,https://ui.lab.example")
    assert MasterSettings.from_environment(environ).operator_allowed_origins == ("https://ui.lab.example", "http://10.88.0.9:8080")
    assert parse_allowed_origins("") == DEFAULT_OPERATOR_ALLOWED_ORIGINS
    assert parse_allowed_origins("http://a, http://b") == ("http://a", "http://b")


def test_artifact_settings():
    environ = dict(REQUIRED, SCENEGEMS_ARTIFACT_DIR="/data/artifacts", SCENEGEMS_ARTIFACT_MAX_BYTES="1048576", SCENEGEMS_ARTIFACT_SWEEP_INTERVAL_S="0", SCENEGEMS_ARTIFACT_SWEEP_GRACE_S="60")
    assert MasterSettings.from_environment(environ).artifacts == ArtifactSettings(Path("/data/artifacts"), 1048576, 0.0, 60.0)
    for name, value in (("SCENEGEMS_ARTIFACT_MAX_BYTES", "lots"), ("SCENEGEMS_ARTIFACT_MAX_BYTES", "0"), ("SCENEGEMS_ARTIFACT_SWEEP_GRACE_S", "-1")):
        with pytest.raises(ValueError):
            MasterSettings.from_environment(dict(REQUIRED, **{name: value}))


def test_overrides():
    environ = dict(
        REQUIRED,
        SCENEGEMS_API_LISTEN_PORT="9443",
        SCENEGEMS_OPERATOR_LISTEN_HOST="0.0.0.0",
        SCENEGEMS_RELEASE_MANIFEST="/etc/scenegems/release.json",
    )
    settings = MasterSettings.from_environment(environ)
    assert settings.node_api == Listener("0.0.0.0", 9443) and settings.operator == Listener("0.0.0.0", 5174)
    assert settings.release_manifest == Path("/etc/scenegems/release.json")


@pytest.mark.parametrize("missing", sorted(REQUIRED))
def test_required_settings(missing):
    environ = {key: value for key, value in REQUIRED.items() if key != missing}
    with pytest.raises(SettingMissing, match=missing):
        MasterSettings.from_environment(environ)


@pytest.mark.parametrize("master_id", ["Lab Master", "lab_master", "lab/master", "-lab", "a" * 64])
def test_the_master_id_must_be_a_scope_name(master_id):
    with pytest.raises(ValueError, match="SCENEGEMS_MASTER_ID"):
        MasterSettings.from_environment(dict(REQUIRED, SCENEGEMS_MASTER_ID=master_id))


def test_secrets_stay_out_of_the_repr():
    text = repr(MasterSettings.from_environment(REQUIRED))
    assert REQUIRED["SCENEGEMS_DATABASE_URL"] not in text


def test_the_cluster_broker_needs_only_a_host():
    assert MasterSettings.from_environment(REQUIRED).broker is None
    environ = dict(REQUIRED, SCENEGEMS_BROKER_HOST="cluster-broker")
    assert MasterSettings.from_environment(environ).broker == BrokerClientSettings("cluster-broker", 1883)
    environ.update(SCENEGEMS_BROKER_PORT="11883")
    assert MasterSettings.from_environment(environ).broker.port == 11883
    with pytest.raises(ValueError, match="SCENEGEMS_BROKER_PORT"):
        MasterSettings.from_environment(dict(environ, SCENEGEMS_BROKER_PORT="plain"))


def test_live_sessions_are_on_unless_turned_off():
    assert MasterSettings.from_environment(REQUIRED).live_sessions is True
    for text, expected in (("false", False), ("0", False), ("off", False), ("TRUE", True), ("yes", True), (" ", True)):
        assert MasterSettings.from_environment(dict(REQUIRED, SCENEGEMS_LIVE_SESSIONS=text)).live_sessions is expected, text
    with pytest.raises(ValueError, match="SCENEGEMS_LIVE_SESSIONS"):
        MasterSettings.from_environment(dict(REQUIRED, SCENEGEMS_LIVE_SESSIONS="maybe"))
