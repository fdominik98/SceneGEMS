"""The roles' chart values agree with the chart's values.yaml, and a values file built from them by the rules of roles.py has the chart's shape."""

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterator, Tuple

import pytest
import yaml

from scenegems_tool.cluster.release.manifest import Release, ReleaseImage
from scenegems_tool.cluster.release.roles import (
    DEFAULT_WORKER_NODE_COMPONENTS,
    PARAMETER_KEY,
    POSTGRES_IMAGE,
    WORKER_NODE_IMAGES_VALUES_PATH,
    role_images,
    scenegems_chart,
    scenegems_roles,
    worker_node_image_variables,
)
from tests.scenegems_tool.cluster.release.chart_values_builder import CHART_VALUES_PLACEHOLDERS, Member, ValuesError, build_values, member_entry, needed_images, placeholders

REPO_ROOT = Path(__file__).resolve().parents[6]
CHART = REPO_ROOT / "deploy" / "kubernetes" / "chart"
REVISION = "abc123"
# A count "many" role's list and the object that holds the fields of its entries with their defaults
ENTRY_DEFAULTS = {"workerNodes": "workerNodeDefaults"}


def _defaults() -> Dict[str, Any]:
    return yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))


def _release_json() -> Dict[str, Any]:
    """release.json of a release built at REVISION, as the deployment tool reads it."""
    roles = scenegems_roles(REVISION)
    images = {image: ReleaseImage(f"sha256:{image}", None if image == POSTGRES_IMAGE else f"fp-{image}") for image in role_images(roles)}
    release = Release(name="scenegems", revision=REVISION, dirty=False, created_at="2026-11-16T12:00:00+00:00", images=images, roles=roles, chart=scenegems_chart(REVISION))
    return json.loads(json.dumps(release.to_json()))


def _pushed(image: str) -> str:
    """The reference the deployment tool pushed an image as."""
    repository = image.split(":", 1)[0]
    return f"registry.lab:5000/{repository}@sha256:{hashlib.sha256(image.encode()).hexdigest()}"


def _leaf_paths(values: Any, prefix: str = "") -> Iterator[Tuple[str, Any]]:
    """Every path to a value that is not an object, with its value; a $parameter object is a leaf."""
    if isinstance(values, dict) and PARAMETER_KEY not in values:
        for key, value in values.items():
            yield from _leaf_paths(value, f"{prefix}.{key}" if prefix else key)
    else:
        yield prefix, values


def _get(values: Dict[str, Any], path: str) -> Any:
    for key in path.split("."):
        if not isinstance(values, dict) or key not in values:
            raise KeyError(path)
        values = values[key]
    return values


def _defaults_of(path: str) -> Any:
    return _get(_defaults(), ENTRY_DEFAULTS.get(path, path))


# Lab cluster: a control node, a kinematic worker node with the defaults and a Gazebo worker node with ArduPilot
CLUSTER = "lab"
GAZEBO_COMPONENTS = "asv_system/replay, control_layer/ardupilot, simulation_layer/gazebo"
MEMBERS = (
    Member("control-node", "control-node", node="pc-1", machine="lab-pc-1", parameters={"SCENEGEMS_ARTIFACT_SWEEP_GRACE_S": "1800.5"}),
    Member("worker-node", "worker-a", node="pc-2", machine="lab-pc-2"),
    Member(
        "worker-node",
        "gazebo-1",
        node="pc-3",
        machine="lab-pc-3",
        parameters={
            "SCENEGEMS_WORKER_NODE_COMPONENTS": GAZEBO_COMPONENTS,
            "SCENEGEMS_WORKER_NODE_SLOTS": "simulation:1",
            "SCENEGEMS_WORKER_NODE_LABELS": "gpu=yes, site=lab",
            "SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES": "0",
        },
    ),
)


def _sample_values() -> Dict[str, Any]:
    release = _release_json()
    pushed = {image: _pushed(image) for image in needed_images(release, CLUSTER, MEMBERS)}
    return build_values(release, CLUSTER, MEMBERS, pushed)


def test_the_chart_is_named_and_versioned():
    chart = yaml.safe_load((CHART / "Chart.yaml").read_text(encoding="utf-8"))
    assert chart["apiVersion"] == "v2" and chart["name"] == "scenegems" and chart["type"] == "application" and chart["version"]


def test_every_value_a_role_or_the_release_names_is_in_values_yaml():
    defaults = _defaults()
    for path, _ in _leaf_paths(scenegems_chart(REVISION).values):
        _get(defaults, path)
    for name, role in scenegems_roles(REVISION).items():
        path = role["values"]["path"]
        target = _defaults_of(path)
        assert isinstance(target, dict), f"{name}: {path} holds an object, or names one of the entry fields"
        if role["count"] == "many":
            assert isinstance(_get(defaults, path), list) and _get(defaults, path) == [], f"{name}: {path} is a list, empty by default"
            assert set(role["values"]["entry"]) == set(target), f"{name}: an entry has the fields of {ENTRY_DEFAULTS[path]}"
        for entry_path, _ in _leaf_paths(role["values"]["entry"]):
            _get(target, entry_path)
        for image, image_path in role["image_values"].items():
            assert isinstance(_get(defaults, image_path), str), f"{name}: {image} goes to {image_path}"


def test_no_key_of_the_values_holds_a_dot():
    for path, _ in _leaf_paths(_defaults()):
        assert all(key and "." not in key for key in path.split(".")), path


def test_the_worker_node_images_are_the_variables_the_code_reads():
    variables = worker_node_image_variables()
    assert set(_defaults()[WORKER_NODE_IMAGES_VALUES_PATH]) == set(variables.values())
    assert all(value == "" for value in _defaults()[WORKER_NODE_IMAGES_VALUES_PATH].values()), "empty: the code's default with imageTag"


def test_the_defaults_of_values_yaml_are_those_of_the_role_parameters():
    """A member that changes nothing gives the chart's defaults, so a hand-written values file and the tool agree."""
    release = _release_json()
    defaults = _defaults()
    control_node = member_entry(release, CLUSTER, Member("control-node", "control-node", node="", machine=""))
    assert control_node == {**{key: defaults["controlNode"][key] for key in control_node}, "enabled": True}
    worker_node = member_entry(release, CLUSTER, Member("worker-node", "", node="", machine=""))
    assert worker_node == defaults["workerNodeDefaults"]
    assert defaults["workerNodeDefaults"]["components"] == DEFAULT_WORKER_NODE_COMPONENTS.split(",")
    assert defaults["images"]["postgres"] == POSTGRES_IMAGE and defaults["controlNode"]["enabled"] is False and defaults["workerNodes"] == []


def test_the_chart_values_of_the_release_use_only_their_placeholders():
    assert set(placeholders(scenegems_chart(REVISION).values)) <= CHART_VALUES_PLACEHOLDERS
    assert scenegems_chart(REVISION).values["imageTag"] == REVISION


def test_a_sample_cluster_gives_one_entry_per_worker_node_and_the_pushed_images():
    values = _sample_values()
    assert values["controlNodeId"] == CLUSTER and values["revision"] == REVISION and values["imageTag"] == REVISION
    assert values["controlNode"] == {
        "enabled": True,
        "node": "pc-1",
        "operatorAllowedOrigins": "http://localhost:5173,http://127.0.0.1:5173",
        "artifactMaxBytes": 268435456,
        "artifactSweepIntervalS": 600,
        "artifactSweepGraceS": 1800.5,
    }
    assert values["workerNodes"] == [
        {
            "name": "gazebo-1",
            "node": "pc-3",
            "machine": "lab-pc-3",
            "components": ["asv_system/replay", "control_layer/ardupilot", "simulation_layer/gazebo"],
            "slots": {"simulation": 1},
            "labels": {"gpu": "yes", "site": "lab"},
            "artifactCacheMaxBytes": 0,
        },
        {
            "name": "worker-a",
            "node": "pc-2",
            "machine": "lab-pc-2",
            "components": DEFAULT_WORKER_NODE_COMPONENTS.split(","),
            "slots": {"simulation": 2, "design_space_exploration": 1, "scene_generation": 1, "trajectory_generation": 1, "monitoring.post_hoc": 1, "calibration.deviation": 1},
            "labels": {},
            "artifactCacheMaxBytes": 2147483648,
        },
    ], "ordered by name"
    assert values["images"] == {
        "controlNodeApi": _pushed(f"scenegems-control-node-api:{REVISION}"),
        "broker": _pushed(f"scenegems-mqtt-broker:{REVISION}"),
        "postgres": _pushed(POSTGRES_IMAGE),
        "workerNode": _pushed(f"scenegems-worker-node:{REVISION}"),
    }
    simulator_images = {"SIMULATION_IMAGE": "scenegems-simulation-subsystem", "SITL_IMAGE": "scenegems-ardupilot-sitl", "GAZEBO_IMAGE": "scenegems-gazebo-harmonic"}
    subsystem_images = {
        "USV_NAVIGATION_IMAGE": "scenegems-usv-navigation",
        "DESIGN_SPACE_EXPLORATION_IMAGE": "scenegems-design-space-exploration-subsystem",
        "SCENE_GENERATION_IMAGE": "scenegems-scene-generation-subsystem",
        "TRAJECTORY_GENERATION_IMAGE": "scenegems-trajectory-generation-subsystem",
        "MONITORING_IMAGE": "scenegems-monitoring-subsystem",
    }
    expected = {variable: _pushed(f"{repository}:{REVISION}") for variable, repository in {**simulator_images, **subsystem_images}.items()}
    assert values[WORKER_NODE_IMAGES_VALUES_PATH] == expected, "only the images the worker nodes' components need"
    assert set(values) == {"controlNodeId", "revision", "imageTag", "controlNode", "workerNodes", "images", WORKER_NODE_IMAGES_VALUES_PATH}


def test_the_sample_values_lay_over_values_yaml():
    """Every value the tool writes is one of the chart's; the images it did not push keep their defaults."""
    values, defaults = _sample_values(), _defaults()
    for path, _ in _leaf_paths({key: value for key, value in values.items() if key != "workerNodes"}):
        _get(defaults, path)
    for entry in values["workerNodes"]:
        assert set(entry) == set(defaults["workerNodeDefaults"])
    merged = copy.deepcopy(defaults)
    for key, value in values.items():
        merged[key] = {**merged[key], **value} if isinstance(value, dict) else value
    assert merged[WORKER_NODE_IMAGES_VALUES_PATH]["MOOS_IVP_IMAGE"] == "" and merged[WORKER_NODE_IMAGES_VALUES_PATH]["ARDUAGENT_IMAGE"] == ""
    assert merged["controlNode"]["storage"] == defaults["controlNode"]["storage"]


def test_a_cluster_of_worker_nodes_only_writes_no_control_node():
    release = _release_json()
    members = [MEMBERS[1]]
    values = build_values(release, CLUSTER, members, {image: _pushed(image) for image in needed_images(release, CLUSTER, members)})
    assert "controlNode" not in values and [entry["name"] for entry in values["workerNodes"]] == ["worker-a"]
    assert set(values["images"]) == {"workerNode"}, "the control node's images are not pushed"


def test_without_worker_nodes_the_list_is_written_empty():
    release = _release_json()
    members = [MEMBERS[0]]
    values = build_values(release, CLUSTER, members, {image: _pushed(image) for image in needed_images(release, CLUSTER, members)})
    assert values["workerNodes"] == [] and WORKER_NODE_IMAGES_VALUES_PATH not in values


@pytest.mark.parametrize(
    "parameters, message",
    [
        ({"SCENEGEMS_WORKER_NODE_SLOTS": "simulation:two"}, "not of type integer"),
        ({"SCENEGEMS_WORKER_NODE_SLOTS": "simulation"}, "must read <key>:<value>"),
        ({"SCENEGEMS_WORKER_NODE_SLOTS": "simulation:1,simulation:2"}, "listed twice"),
        ({"SCENEGEMS_WORKER_NODE_LABELS": "gpu"}, "must read <key>=<value>"),
        ({"SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES": "2 GB"}, "not of type integer"),
        ({"SCENEGEMS_WORKER_NODE_COMPONENTS": "simulation_layer/warp"}, "unknown item"),
        ({"SCENEGEMS_NO_SUCH_PARAMETER": "1"}, "no parameter"),
    ],
)
def test_a_bad_parameter_value_fails_naming_the_member(parameters, message):
    release = _release_json()
    member = Member("worker-node", "worker-b", node="pc-2", machine="lab-pc-2", parameters=parameters)
    with pytest.raises(ValuesError, match=message) as error:
        build_values(release, CLUSTER, [member], {image: _pushed(image) for image in role_images(scenegems_roles(REVISION))})
    assert "worker-b" in str(error.value)


def test_an_image_that_was_not_pushed_fails():
    release = _release_json()
    with pytest.raises(ValuesError, match="was not pushed"):
        build_values(release, CLUSTER, MEMBERS, {})


def test_two_control_nodes_fail():
    release = _release_json()
    with pytest.raises(ValuesError, match="one control-node"):
        build_values(release, CLUSTER, [MEMBERS[0], Member("control-node", "second", node="pc-2", machine="lab-pc-2")], {})
