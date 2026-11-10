"""The roles of release.json agree with the stacks they install and the .env templates."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from scenegems_tool.cluster.release.bundle import STACK_COMPOSE_FILES
from scenegems_tool.cluster.release.roles import DEFAULT_CONTROL_NODE_COMPOSE_FILES, LIVE_SESSIONS_COMPOSE_FILE, POSTGRES_IMAGE, scenegems_roles

REPO_ROOT = Path(__file__).resolve().parents[6]
ENV_TEMPLATES = {"control-node": "deploy/control_node/.env.example", "worker-node": "deploy/worker_node/.env.example"}
_INTERPOLATION = re.compile(r"(?<!\$)\$\{([A-Z_][A-Z0-9_]*)(:?[-?][^}]*)?\}")


def _compose_text(role: str) -> str:
    """Every compose file of the role's stack, one after the other."""
    return "\n".join((REPO_ROOT / compose_file).read_text(encoding="utf-8") for compose_file in STACK_COMPOSE_FILES[role])


def _compose_file(path: str) -> dict:
    return yaml.safe_load((REPO_ROOT / path).read_text(encoding="utf-8"))


def _compose(role: str) -> dict:
    """The role's compose files merged as compose merges them: maps updated, volume and host lists appended."""
    merged: dict = {"services": {}, "volumes": {}}
    for compose_file in STACK_COMPOSE_FILES[role]:
        compose = _compose_file(compose_file)
        merged["volumes"].update(compose.get("volumes") or {})
        for name, service in compose["services"].items():
            target = merged["services"].setdefault(name, {})
            for key, value in service.items():
                if isinstance(value, dict):
                    target[key] = {**target.get(key, {}), **value}
                elif isinstance(value, list) and key != "command":
                    target[key] = target.get(key, []) + value
                else:
                    target[key] = value
    return merged


def _role_keys(role: dict) -> set:
    return set(role["env"]) | set(role["parameters"]) | set(role["secrets"]) | set(role.get("requires", {}).get("keys", []))


def _template_keys(role: str) -> set:
    lines = (REPO_ROOT / ENV_TEMPLATES[role]).read_text(encoding="utf-8").splitlines()
    return {line.split("=", 1)[0] for line in lines if re.match(r"^[A-Z_][A-Z0-9_]*=", line)}


def _compose_variables(role: str):
    """(name, has_default) for every ${...} the compose file interpolates."""
    for match in _INTERPOLATION.finditer(_compose_text(role)):
        yield match.group(1), bool(match.group(2)) and match.group(2).lstrip(":").startswith("-")


@pytest.mark.parametrize("role_name", sorted(STACK_COMPOSE_FILES))
def test_every_variable_without_a_default_is_written_by_the_role(role_name):
    role = scenegems_roles()[role_name]
    needed = {name for name, has_default in _compose_variables(role_name) if not has_default}
    assert needed <= _role_keys(role)


@pytest.mark.parametrize("role_name", sorted(ENV_TEMPLATES))
def test_the_env_template_lists_every_key_the_role_writes_and_nothing_unknown(role_name):
    role = scenegems_roles()[role_name]
    template = _template_keys(role_name)
    assert _role_keys(role) <= template
    known = _role_keys(role) | {name for name, _ in _compose_variables(role_name)}
    assert template <= known


@pytest.mark.parametrize("role_name", sorted(STACK_COMPOSE_FILES))
def test_ready_services_exist(role_name):
    services = _compose(role_name)["services"]
    ready = scenegems_roles()[role_name]["ready"]
    assert set(ready.get("healthy", [])) | set(ready.get("running", [])) <= set(services)
    for name in ready.get("healthy", []):
        assert "healthcheck" in services[name], name


def _settings_of(compose: dict) -> str:
    """The environment, volumes and ports of every service: what a stack is configured with, without its comments."""
    parts = []
    for service in compose["services"].values():
        parts += [str(key) for key in service.get("environment", {})] + [str(volume) for volume in service.get("volumes", [])] + [str(port) for port in service.get("ports", [])]
    return " ".join(parts).lower()


def test_the_control_node_stack_has_no_security_tool_certificates_or_tokens():
    compose = _compose("control-node")
    assert set(_compose_file(STACK_COMPOSE_FILES["control-node"][1])["services"]) == {"control-node-api"}, "the live sessions file only adds to control-node-api"
    assert set(compose["services"]) == {"postgres", "cluster-broker", "control-node-api"}
    settings = _settings_of(compose)
    for word in ("security", "pairing", "certificate", "auth_hook", "broker_control_node", "8883"):
        assert word not in settings, word
    role = scenegems_roles()["control-node"]
    assert role["setup"] == [] and role["outputs"] == {}


def test_postgres_is_the_same_image_everywhere():
    assert _compose("control-node")["services"]["postgres"]["image"] == POSTGRES_IMAGE
    build_script = (REPO_ROOT / "deploy" / "scripts" / "build.sh").read_text(encoding="utf-8")
    assert f'RELEASE_PULLED_IMAGES=("{POSTGRES_IMAGE}")' in build_script


def test_stacks_mount_no_checkout():
    for role_name in STACK_COMPOSE_FILES:
        for service in _compose(role_name)["services"].values():
            for volume in service.get("volumes", []):
                assert not str(volume).startswith(".."), volume


def _example_env(role_name: str) -> str:
    role = scenegems_roles()[role_name]
    values = {key: "value" for key in _role_keys(role)}
    values.update({key: parameter["default"] for key, parameter in role["parameters"].items()})
    values.update(
        {
            key: text.replace("{cluster}", "lab")
            .replace("{name}", "worker-1")
            .replace("{machine.vpn_ip}", "10.88.0.2")
            .replace("{release.revision}", "abc")
            .replace("{control-node.vpn_ip}", "10.88.0.2")
            .replace("{control-node.SCENEGEMS_API_PORT}", "8443")
            .replace("{control-node.SCENEGEMS_BROKER_PORT}", "1883")
            for key, text in role["env"].items()
        }
    )
    return "".join(f"{key}={value}\n" for key, value in sorted(values.items()))


@pytest.mark.docker
@pytest.mark.parametrize("role_name", sorted(STACK_COMPOSE_FILES))
def test_docker_compose_accepts_the_stack_with_the_role_env(role_name, tmp_path):
    if shutil.which("docker") is None:
        pytest.skip("needs the docker CLI")
    for compose_file in STACK_COMPOSE_FILES[role_name]:
        shutil.copyfile(REPO_ROOT / compose_file, tmp_path / Path(compose_file).name)
    (tmp_path / ".env").write_text(_example_env(role_name), encoding="utf-8")
    (tmp_path / "release.json").write_text("{}", encoding="utf-8")
    completed = subprocess.run(["docker", "compose", "--profile", "tools", "config", "-q"], cwd=tmp_path, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_the_control_node_keeps_artifacts_on_their_own_volume():
    compose = _compose("control-node")
    service = compose["services"]["control-node-api"]
    folder = service["environment"]["SCENEGEMS_ARTIFACT_DIR"]
    assert f"artifacts:{folder}" in service["volumes"]
    assert compose["volumes"]["artifacts"]["name"] == "scenegems-${SCENEGEMS_CONTROL_NODE_ID}-artifacts"
    for key in ("SCENEGEMS_ARTIFACT_MAX_BYTES", "SCENEGEMS_ARTIFACT_SWEEP_INTERVAL_S", "SCENEGEMS_ARTIFACT_SWEEP_GRACE_S"):
        assert service["environment"][key] == f"${{{key}:-{scenegems_roles()['control-node']['parameters'][key]['default']}}}"


def test_the_control_node_passes_the_allowed_origins_to_control_node_api_with_the_roles_default():
    service = _compose("control-node")["services"]["control-node-api"]
    default = scenegems_roles()["control-node"]["parameters"]["SCENEGEMS_OPERATOR_ALLOWED_ORIGINS"]["default"]
    assert service["environment"]["SCENEGEMS_OPERATOR_ALLOWED_ORIGINS"] == f"${{SCENEGEMS_OPERATOR_ALLOWED_ORIGINS:-{default}}}"
    assert f"SCENEGEMS_OPERATOR_ALLOWED_ORIGINS={default}" in (REPO_ROOT / ENV_TEMPLATES["control-node"]).read_text(encoding="utf-8").splitlines()


def test_the_worker_node_passes_its_machine_on_and_lists_it_in_its_env_template():
    service = _compose("worker-node")["services"]["worker-node"]
    assert service["environment"]["SCENEGEMS_WORKER_NODE_MACHINE"] == "${SCENEGEMS_WORKER_NODE_MACHINE:-}"  # optional for a hand-written .env
    assert "SCENEGEMS_WORKER_NODE_MACHINE" in _template_keys("worker-node") and "SCENEGEMS_WORKER_NODE_MACHINE" in scenegems_roles()["worker-node"]["env"]


def test_the_worker_node_caches_artifacts_in_its_state_volume():
    service = _compose("worker-node")["services"]["worker-node"]
    state = service["environment"]["SCENEGEMS_WORKER_NODE_STATE_DIR"]
    assert f"state:{state}" in service["volumes"]
    assert service["environment"]["SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_DIR"].startswith(state + "/")
    default = scenegems_roles()["worker-node"]["parameters"]["SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES"]["default"]
    assert service["environment"]["SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES"] == f"${{SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES:-{default}}}"


def test_the_control_node_observes_the_plain_cluster_broker_on_the_compose_network():
    compose = _compose("control-node")
    environment = compose["services"]["control-node-api"]["environment"]
    assert (environment["SCENEGEMS_BROKER_HOST"], environment["SCENEGEMS_BROKER_PORT"]) == ("cluster-broker", "1883")
    default = scenegems_roles()["control-node"]["parameters"]["SCENEGEMS_BROKER_PORT"]["default"]
    assert default == "1883"
    ports = compose["services"]["cluster-broker"]["ports"]
    assert ports == ["${SCENEGEMS_BROKER_BIND_ADDRESS:-0.0.0.0}:${SCENEGEMS_BROKER_PORT:-" + default + "}:1883"]


def test_the_worker_node_stack_has_no_pairing_token_ca_or_trust_volume_and_dials_the_control_node_url():
    compose = _compose("worker-node")
    service = compose["services"]["worker-node"]
    assert "SCENEGEMS_CONTROL_NODE_URL" in service["environment"] and "SCENEGEMS_BROKER_PORT" in service["environment"]
    settings = _settings_of(compose)
    for word in ("pairing", "ca_sha256", "trust", "token"):
        assert word not in settings, word
    assert set(compose["volumes"]) == {"runtime", "state"}


def test_only_the_live_sessions_file_gives_control_node_api_the_docker_socket():
    base, live = (_compose_file(path)["services"]["control-node-api"] for path in STACK_COMPOSE_FILES["control-node"])
    assert Path(STACK_COMPOSE_FILES["control-node"][1]).name == LIVE_SESSIONS_COMPOSE_FILE
    assert not any("docker.sock" in str(volume) for volume in base["volumes"])
    assert "/var/run/docker.sock:/var/run/docker.sock" in live["volumes"]
    assert base["environment"]["SCENEGEMS_LIVE_SESSIONS"] == "false" and live["environment"]["SCENEGEMS_LIVE_SESSIONS"] == "true"
    for key in ("SCENEGEMS_RUNTIME_VOLUME", "SCENEGEMS_DOCKER_NETWORK"):
        assert key not in base["environment"] and key in live["environment"]


def test_compose_reads_both_control_node_files_by_default_through_compose_file():
    role = scenegems_roles()["control-node"]
    default = role["parameters"]["COMPOSE_FILE"]["default"]
    assert default == DEFAULT_CONTROL_NODE_COMPOSE_FILES
    assert default.split(role["env"]["COMPOSE_PATH_SEPARATOR"]) == [Path(path).name for path in STACK_COMPOSE_FILES["control-node"]]
    template = (REPO_ROOT / ENV_TEMPLATES["control-node"]).read_text(encoding="utf-8").splitlines()
    assert f"COMPOSE_FILE={default}" in template and "COMPOSE_PATH_SEPARATOR=:" in template


def test_every_image_scenegems_builds_carries_the_release_tag():
    tag = "${SCENEGEMS_IMAGE_TAG:-latest}"
    control_node, worker_node = _compose("control-node")["services"], _compose("worker-node")["services"]
    assert control_node["control-node-api"]["image"] == f"scenegems-control-node-api:{tag}" and control_node["cluster-broker"]["image"] == f"scenegems-mqtt-broker:{tag}"
    assert worker_node["worker-node"]["image"] == f"scenegems-worker-node:{tag}"
    assert worker_node["worker-node"]["environment"]["SCENEGEMS_IMAGE_TAG"] == tag, "the worker node names its jobs' images with it"
    roles = scenegems_roles("abc123")
    assert roles["control-node"]["env"]["SCENEGEMS_IMAGE_TAG"] == roles["worker-node"]["env"]["SCENEGEMS_IMAGE_TAG"] == "abc123"
