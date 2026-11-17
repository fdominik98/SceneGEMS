"""The chart agrees with the roles of release.json and with the code it deploys.

The chart (deploy/kubernetes/chart) is rendered with `helm template` from the values the reference builder makes of
the roles for a sample cluster (chart_values_builder.py, the way Machine Hub builds them) and from a hand-written
values file (the local cluster's). The rendered objects must be the workloads and services the roles' `ready` and
`forwards` name, set every variable the control node's settings and the daemon's configuration require (both are
parsed from the rendered environment), name only images of the release, and give the two service accounts exactly
the rights of the design log's K4 results. The values schema must refuse what the daemon would refuse.

The rendering tests need helm (SCENEGEMS_HELM or the PATH) and carry the kubernetes marker; the checks of the schema
against the code run in the default suite.
"""

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import pytest
import yaml

from scenegems_tool.cluster.control_node.api.control_node_apps import HEALTH_PATH
from scenegems_tool.cluster.control_node.settings import ControlNodeSettings
from scenegems_tool.cluster.fingerprints.components import COMPONENTS
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.release.roles import CONTROL_NODE_API_SERVICE, POSTGRES_IMAGE, scenegems_roles, worker_node_image_variables
from scenegems_tool.cluster.scope_names import SCOPE_NAME_PATTERN, WORKER_NODE_NAME_PATTERN
from scenegems_tool.cluster.worker_node.daemon.configuration.worker_node_configuration import WorkerNodeConfiguration
from scenegems_tool.cluster.worker_node.instance_scope import INSTANCE_LABEL
from scenegems_tool.cluster.worker_node.launchers.per_job.run_pod import RUN_COMPONENT, RUN_COMPONENT_LABEL
from scenegems_tool.vessel_stack.contracts.stack_services import MAX_VESSELS, PORT_RANGES
from tests.scenegems_tool.cluster.release.chart_values_builder import build_values, member_context, needed_images, render
from tests.scenegems_tool.cluster.release.test_chart_values import CLUSTER, MEMBERS, REVISION, _pushed, _release_json
from tests.scenegems_tool.cluster.worker_node.k3d_cluster import K3dUnavailable, helm_executable

REPO_ROOT = Path(__file__).resolve().parents[6]
CHART = REPO_ROOT / "deploy" / "kubernetes" / "chart"
SCHEMA = json.loads((CHART / "values.schema.json").read_text(encoding="utf-8"))
NAMESPACE = "scenegems"

# The rights of the two service accounts, as the K4 results of the design log give them
RIGHTS = {
    "worker-node": [
        {"apiGroups": ["apps"], "resources": ["deployments"], "verbs": ["get", "list", "create", "update", "delete"]},
        {"apiGroups": [""], "resources": ["pods", "services"], "verbs": ["list", "delete"]},
    ],
    "simulation-subsystem": [
        {"apiGroups": [""], "resources": ["pods"], "verbs": ["get", "list", "create", "delete"]},
        {"apiGroups": [""], "resources": ["pods/log"], "verbs": ["get"]},
        {"apiGroups": [""], "resources": ["services"], "verbs": ["get", "list", "create", "update", "delete"]},
    ],
}


# The schema against the code (default suite)


def test_the_schema_lists_the_components_job_types_and_image_variables_of_the_code():
    definitions = SCHEMA["definitions"]
    assert definitions["component"]["enum"] == sorted(COMPONENTS)
    assert definitions["jobType"]["enum"] == [job_type.value for job_type in JobType]
    assert sorted(SCHEMA["properties"]["workerNodeImages"]["properties"]) == sorted(worker_node_image_variables().values())


def test_the_schema_bounds_names_as_the_code_does():
    assert SCHEMA["definitions"]["workerNodeName"]["pattern"] == WORKER_NODE_NAME_PATTERN.pattern
    assert SCHEMA["definitions"]["scopeName"]["pattern"] == SCOPE_NAME_PATTERN.pattern
    assert scenegems_roles()["worker-node"]["name_pattern"] == WORKER_NODE_NAME_PATTERN.pattern


def test_the_schema_knows_every_value_of_values_yaml_and_nothing_else():
    defaults = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    assert set(SCHEMA["properties"]) == set(defaults) and SCHEMA["additionalProperties"] is False
    for key in ("images", "workerNodeImages", "controlNode", "networkPolicy"):
        assert set(SCHEMA["properties"][key]["properties"]) == set(defaults[key]), key
    assert set(SCHEMA["definitions"]["workerNodeFields"]["properties"]) == set(defaults["workerNodeDefaults"])


def test_nothing_of_the_compose_deploy_is_left_in_deploy():
    deploy = REPO_ROOT / "deploy"
    assert not [path for path in deploy.rglob("*") if path.name in ("docker-compose.yml", ".env.example")]
    assert not (deploy / "control_node").exists() and not (deploy / "worker_node").exists()


# Rendering the chart (kubernetes marker: needs helm)


def _helm() -> str:
    try:
        return helm_executable()
    except K3dUnavailable as error:
        pytest.fail(str(error), pytrace=False)


def _chart_with_release(folder: Path, release: Mapping[str, Any]) -> Path:
    """The chart as a release bundle holds it: with a copy of release.json."""
    chart = folder / "chart"
    shutil.copytree(CHART, chart)
    (chart / "release.json").write_text(json.dumps(release, indent=2), encoding="utf-8")
    return chart


def _render(chart: Path, values: Mapping[str, Any], folder: Path) -> subprocess.CompletedProcess:
    values_file = folder / "values.yaml"
    values_file.write_text(yaml.safe_dump(dict(values)), encoding="utf-8")
    return subprocess.run([_helm(), "template", "scenegems", str(chart), "--namespace", NAMESPACE, "-f", str(values_file)], capture_output=True, text=True, timeout=120)


def _objects(chart: Path, values: Mapping[str, Any], folder: Path) -> List[Dict[str, Any]]:
    rendered = _render(chart, values, folder)
    assert rendered.returncode == 0, rendered.stderr
    return [document for document in yaml.safe_load_all(rendered.stdout) if document]


def _of_kind(objects: List[Dict[str, Any]], kind: str) -> Dict[str, Dict[str, Any]]:
    return {item["metadata"]["name"]: item for item in objects if item["kind"] == kind}


def _containers(workload: Mapping[str, Any]) -> List[Dict[str, Any]]:
    spec = workload["spec"]["template"]["spec"]
    return list(spec.get("initContainers", [])) + list(spec["containers"])


def _environment(container: Mapping[str, Any], namespace: str = NAMESPACE, secret: str = "generated") -> Dict[str, str]:
    """The container's variables as the kubelet sets them: a Secret's key, the pod's namespace, $(VAR) expanded."""
    values: Dict[str, str] = {}
    for variable in container.get("env", []):
        if "value" in variable:
            values[variable["name"]] = re.sub(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)", lambda match: values.get(match.group(1), match.group(0)), variable["value"])
        elif "secretKeyRef" in variable["valueFrom"]:
            values[variable["name"]] = secret
        else:
            assert variable["valueFrom"]["fieldRef"]["fieldPath"] == "metadata.namespace", variable
            values[variable["name"]] = namespace
    return values


def _images(objects: List[Dict[str, Any]]) -> List[str]:
    """Every image a pod of the chart runs, and every image a daemon is told to start."""
    images = []
    for workload in list(_of_kind(objects, "Deployment").values()) + list(_of_kind(objects, "StatefulSet").values()):
        for container in _containers(workload):
            images.append(container["image"])
            images += [value for name, value in _environment(container).items() if name.endswith("_IMAGE")]
    return images


@pytest.fixture(scope="module")
def release() -> Dict[str, Any]:
    return _release_json()


@pytest.fixture(scope="module")
def sample(tmp_path_factory, release):
    """The sample cluster of test_chart_values.py rendered: a control node and two worker nodes, every needed image pushed."""
    folder = tmp_path_factory.mktemp("chart")
    chart = _chart_with_release(folder, release)
    values = build_values(release, CLUSTER, MEMBERS, {image: _pushed(image) for image in needed_images(release, CLUSTER, MEMBERS)})
    return chart, values, _objects(chart, values, folder)


def _local_values(release: Mapping[str, Any], **entry: Any) -> Dict[str, Any]:
    """A hand-written values file like the local cluster's: the release's values, a control node and one worker node, no image named."""
    values = json.loads(render(json.dumps(release["chart"]["values"]), {"cluster": "local", "release.revision": release["revision"]}, "chart values"))
    values["controlNode"] = {"enabled": True, "node": "k3d-local-server-0"}
    values["workerNodes"] = [{"name": "local", "node": "k3d-local-server-0", **entry}]
    return values


@pytest.mark.kubernetes
def test_the_workloads_and_services_are_the_ones_the_roles_name(sample, release):
    _, _, objects = sample
    expected_deployments, expected_stateful_sets = set(), set()
    for member in MEMBERS:
        ready = release["roles"][member.role]["ready"]
        context = member_context(release, CLUSTER, member)
        expected_deployments |= {render(name, context, "ready") for name in ready["deployments"]}
        expected_stateful_sets |= {render(name, context, "ready") for name in ready.get("stateful_sets", [])}
    assert set(_of_kind(objects, "Deployment")) == expected_deployments == {"control-node-api", "cluster-broker", "worker-node-gazebo-1", "worker-node-worker-a"}
    assert set(_of_kind(objects, "StatefulSet")) == expected_stateful_sets == {"postgres"}
    services = {name: {port["port"] for port in service["spec"]["ports"]} for name, service in _of_kind(objects, "Service").items()}
    assert services == {"postgres": {5432}, "cluster-broker": {1883}, "control-node-api": {8443, 5174}}
    for forward in release["roles"]["control-node"]["forwards"]:
        assert forward["port"] in services[forward["service"]] and forward["service"] == CONTROL_NODE_API_SERVICE
    for service in _of_kind(objects, "Service").values():
        assert service["spec"].get("type", "ClusterIP") == "ClusterIP", "nothing is published outside the cluster"


@pytest.mark.kubernetes
def test_the_control_node_gets_every_setting_it_needs_from_its_values(sample):
    _, values, objects = sample
    deployment = _of_kind(objects, "Deployment")["control-node-api"]
    (container,) = deployment["spec"]["template"]["spec"]["containers"]
    environment = _environment(container)
    settings = ControlNodeSettings.from_environment(environment)
    control_node = values["controlNode"]
    assert settings.control_node_id == CLUSTER and settings.database_url == "postgresql+psycopg://scenegems:generated@postgres:5432/scenegems"
    assert (settings.worker_node_api.port, settings.operator.host, settings.operator.port) == (8443, "0.0.0.0", 5174)
    assert settings.operator_allowed_origins == tuple(control_node["operatorAllowedOrigins"].split(","))
    assert (settings.artifacts.max_bytes, settings.artifacts.sweep_interval_s, settings.artifacts.sweep_grace_s) == (
        control_node["artifactMaxBytes"],
        control_node["artifactSweepIntervalS"],
        control_node["artifactSweepGraceS"],
    )
    assert settings.broker is not None and (settings.broker.host, settings.broker.port) == ("cluster-broker", 1883)
    mounts = {mount["mountPath"]: mount for mount in container["volumeMounts"]}
    assert mounts[settings.release_manifest.as_posix()]["subPath"] == "release.json" and settings.artifacts.folder.as_posix() in mounts
    spec = deployment["spec"]["template"]["spec"]
    assert spec["nodeSelector"] == {"kubernetes.io/hostname": "pc-1"} and spec["automountServiceAccountToken"] is False
    assert container["readinessProbe"]["httpGet"] == {"path": HEALTH_PATH, "port": "operator-api"}, "available when the operator API answers"
    for name in ("cluster-broker",):
        assert _of_kind(objects, "Deployment")[name]["spec"]["template"]["spec"]["nodeSelector"] == {"kubernetes.io/hostname": "pc-1"}
    assert _of_kind(objects, "StatefulSet")["postgres"]["spec"]["template"]["spec"]["nodeSelector"] == {"kubernetes.io/hostname": "pc-1"}


@pytest.mark.kubernetes
def test_the_postgres_password_is_generated_kept_and_never_a_value(sample):
    _, values, objects = sample
    secret = _of_kind(objects, "Secret")["postgres"]
    assert secret["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"
    assert "password" in secret["data"] and "password" not in json.dumps(values).lower()
    assert _of_kind(objects, "PersistentVolumeClaim")["control-node-artifacts"]["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"


@pytest.mark.kubernetes
def test_each_worker_node_s_daemon_gets_its_configuration_from_its_entry(sample):
    _, values, objects = sample
    deployments = _of_kind(objects, "Deployment")
    for entry in values["workerNodes"]:
        deployment = deployments[f"worker-node-{entry['name']}"]
        spec = deployment["spec"]["template"]["spec"]
        (container,) = spec["containers"]
        configuration = WorkerNodeConfiguration.from_values(_environment(container))
        assert configuration.worker_node_name == entry["name"] and configuration.control_node_id == CLUSTER
        assert configuration.control_node_url == "http://control-node-api:8443" and (configuration.broker_host, configuration.broker_port) == ("cluster-broker", 1883)
        assert sorted(configuration.components) == sorted(entry["components"])
        assert {job_type.value: count for job_type, count in configuration.slots.items()} == entry["slots"]
        assert configuration.labels == {key: str(value) for key, value in entry["labels"].items()}
        assert configuration.machine == entry["machine"] and configuration.software_revision == REVISION
        assert configuration.artifact_cache_max_bytes == entry["artifactCacheMaxBytes"]
        assert (configuration.kubernetes_namespace, configuration.kubernetes_node) == (NAMESPACE, entry["node"])
        runtime = f"{values.get('workerNodeHostPath', '/var/lib/scenegems')}/{entry['name']}/runtime"
        assert configuration.runtime_host_path == runtime
        assert spec["nodeSelector"] == {"kubernetes.io/hostname": entry["node"]} and spec["serviceAccountName"] == "worker-node"
        assert INSTANCE_LABEL not in deployment["spec"]["template"]["metadata"]["labels"], "the daemon's pod is no instance of its own leftovers"
        volumes = {volume["name"]: volume for volume in spec["volumes"]}
        mounts = {mount["mountPath"]: mount["name"] for mount in container["volumeMounts"]}
        assert volumes[mounts["/app/assets/runtime_assets"]]["hostPath"]["path"] == runtime
        assert mounts[configuration.state_dir.as_posix()] == "state" and "hostPath" in volumes["state"]
        assert configuration.artifact_cache_folder.is_relative_to(configuration.state_dir)
        assert mounts[configuration.release_manifest.as_posix()] == "release-manifest"
        environment = _environment(container)
        assert {name: value for name, value in environment.items() if name.endswith("_IMAGE")} == {name: image for name, image in values["workerNodeImages"].items() if image}
        assert environment["SCENEGEMS_IMAGE_TAG"] == values["imageTag"]


@pytest.mark.kubernetes
def test_the_chart_names_only_images_of_the_release_by_their_pushed_reference(sample, release):
    _, _, objects = sample
    pushed = {_pushed(image) for image in release["images"]}
    images = _images(objects)
    assert images and set(images) <= pushed


@pytest.mark.kubernetes
def test_without_image_values_every_image_is_the_release_s_by_its_tag(tmp_path, release):
    chart = _chart_with_release(tmp_path, release)
    objects = _objects(chart, _local_values(release), tmp_path)
    images = _images(objects)
    assert {image for image in images} <= set(release["images"])
    assert f"scenegems-worker-node:{REVISION}" in images and f"scenegems-control-node-api:{REVISION}" in images and POSTGRES_IMAGE in images
    assert all(container["imagePullPolicy"] == "IfNotPresent" for workload in _of_kind(objects, "Deployment").values() for container in _containers(workload))


@pytest.mark.kubernetes
def test_a_hand_written_entry_takes_the_defaults_as_a_whole_per_field(tmp_path, release):
    chart = _chart_with_release(tmp_path, release)
    objects = _objects(chart, _local_values(release, slots={"simulation": 1}, components=["asv_system/replay", "control_layer/none", "simulation_layer/kinematic"]), tmp_path)
    (container,) = _of_kind(objects, "Deployment")["worker-node-local"]["spec"]["template"]["spec"]["containers"]
    configuration = WorkerNodeConfiguration.from_values(_environment(container))
    assert configuration.slots == {JobType.SIMULATION: 1}, "the entry's slots replace the defaults' and are not merged with them"
    assert configuration.artifact_cache_max_bytes == 2 * 1024**3 and configuration.labels == {}


@pytest.mark.kubernetes
def test_a_cluster_of_worker_nodes_only_has_no_control_node(tmp_path, release):
    chart = _chart_with_release(tmp_path, release)
    values = build_values(release, CLUSTER, [member for member in MEMBERS if member.role == "worker-node"], {image: _pushed(image) for image in release["images"]})
    objects = _objects(chart, values, tmp_path)
    assert set(_of_kind(objects, "Deployment")) == {"worker-node-gazebo-1", "worker-node-worker-a"}
    assert not _of_kind(objects, "StatefulSet") and not _of_kind(objects, "Secret") and set(_of_kind(objects, "Service")) == set()
    assert set(_of_kind(objects, "ConfigMap")) == {"release-manifest"} and set(_of_kind(objects, "ServiceAccount")) == {"worker-node", "simulation-subsystem"}


@pytest.mark.kubernetes
def test_the_service_accounts_have_exactly_the_rights_of_the_design(sample):
    _, _, objects = sample
    roles = _of_kind(objects, "Role")
    assert {name: role["rules"] for name, role in roles.items()} == RIGHTS
    for name, binding in _of_kind(objects, "RoleBinding").items():
        assert binding["roleRef"]["name"] == name and binding["subjects"] == [{"kind": "ServiceAccount", "name": name, "namespace": NAMESPACE}]
    assert set(_of_kind(objects, "ServiceAccount")) == set(RIGHTS)


@pytest.mark.kubernetes
def test_a_run_reaches_only_the_broker_dns_and_external_brokers_and_is_reached_on_its_ground_control_ports(sample):
    _, _, objects = sample
    policy = _of_kind(objects, "NetworkPolicy")["simulation-runs"]["spec"]
    assert policy["podSelector"] == {"matchLabels": {RUN_COMPONENT_LABEL: RUN_COMPONENT}} and policy["policyTypes"] == ["Ingress", "Egress"]
    ground_control = PORT_RANGES["ground_control"]
    assert policy["ingress"] == [{"ports": [{"protocol": "TCP", "port": ground_control.port(0), "endPort": ground_control.port(MAX_VESSELS - 1)}]}]
    broker, dns, external = policy["egress"]
    broker_labels = _of_kind(objects, "Deployment")["cluster-broker"]["spec"]["template"]["metadata"]["labels"]
    assert broker["to"][0]["podSelector"]["matchLabels"].items() <= broker_labels.items() and broker["ports"] == [{"protocol": "TCP", "port": 1883}]
    assert {port["port"] for port in dns["ports"]} == {53} and dns["to"][0]["podSelector"] == {"matchLabels": {"k8s-app": "kube-dns"}}
    assert external == {"to": [{"ipBlock": {"cidr": "0.0.0.0/0"}}], "ports": [{"protocol": "TCP", "port": 8883}]}


def _refusal(tmp_path: Path, release: Mapping[str, Any], values: Mapping[str, Any], chart: Optional[Path] = None) -> str:
    rendered = _render(chart or _chart_with_release(tmp_path, release), values, tmp_path)
    assert rendered.returncode != 0, "the values were taken"
    return rendered.stderr


@pytest.mark.kubernetes
@pytest.mark.parametrize(
    "change, message",
    [
        (lambda values: values["workerNodes"][0].update(name="w" * 29), "does not match pattern"),
        (lambda values: values["workerNodes"][0].update(name="Worker-1"), "does not match pattern"),
        (lambda values: values["workerNodes"][0].update(name="worker_1"), "does not match pattern"),
        (lambda values: values["workerNodes"][0].pop("node"), "node"),
        (lambda values: values["workerNodes"].append(copy.deepcopy(values["workerNodes"][0])), "given twice"),
        (lambda values: values["workerNodes"][0].update(components=["simulation_layer/warp"]), "components"),
        (lambda values: values["workerNodes"][0].update(slots={"simulation": 0}), "minimum"),
        (lambda values: values["workerNodes"][0].update(slots={"simulation.kinematic": 1}), "simulation.kinematic"),
        (lambda values: values.update(controlNodeId="Lab"), "does not match pattern"),
        (lambda values: values.update(workerNode=[]), "additional properties"),
    ],
)
def test_values_the_system_cannot_run_are_refused(tmp_path, release, change, message):
    values = _local_values(release)
    change(values)
    assert message in _refusal(tmp_path, release, values)


@pytest.mark.kubernetes
def test_a_name_of_28_characters_is_taken(tmp_path, release):
    chart = _chart_with_release(tmp_path, release)
    objects = _objects(chart, _local_values(release) | {"workerNodes": [{"name": "w" * 28, "node": "k3d-local-server-0"}]}, tmp_path)
    assert f"worker-node-{'w' * 28}" in _of_kind(objects, "Deployment")


@pytest.mark.kubernetes
def test_a_chart_without_release_json_is_refused(tmp_path, release):
    chart = tmp_path / "chart"
    shutil.copytree(CHART, chart)
    assert "release.json" in _refusal(tmp_path, release, _local_values(release), chart)
