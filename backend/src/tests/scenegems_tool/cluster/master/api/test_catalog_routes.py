"""The catalog routes: the classes a campaign draws from and the stacks, monitors and generators a run may use. No database needed."""

import json

import pytest
from starlette.testclient import TestClient

from scenegems_tool.assurance.campaign import ClassCatalog
from scenegems_tool.assurance.campaign.campaign_config import (
    ARDUPILOT_LAYERS,
    SEARCH_PARAM_KEYS,
    ArdupilotStackConfig,
    CustomStackConfig,
    GeofenceSettings,
    KinematicStackConfig,
    RunConfig,
    TrajectoriesConfig,
    parse_campaign_config,
)
from scenegems_tool.assurance.campaign.config_validation import validate_campaign_config
from scenegems_tool.cluster.master.api.master_apps import create_operator_app
from scenegems_tool.cluster.node.jobs.simulation_runners.kinematic_runner import KinematicMode, UsvNavigationPayload
from scenegems_tool.cluster.protocol.routes import CATALOG_PATH
from scenegems_tool.persistence.schema import MonitorImplementation, TrajectoryGeneratorImplementation
from scenegems_tool.vessel_stack.registry.catalog import default_resolver

CLASSES = f"{CATALOG_PATH}/fecs"
STACKS = f"{CATALOG_PATH}/stacks"


@pytest.fixture
def operator(memory_plane):
    with TestClient(create_operator_app(memory_plane)) as client:  # no campaign stores: the catalog needs none
        yield client


@pytest.fixture
def small_catalog(tmp_path, monkeypatch):
    """Four classes in two folders, in a folder of their own."""
    problems = {
        "2vessel_0obstacle_scenarios/fec1": "OS(os1).\nTS(ts1).\n",
        "2vessel_0obstacle_scenarios/fec2": "OS(os1).\nTS(ts1).\n\nr(os1, ts1).\n",
        "2vessel_0obstacle_scenarios/fec10": "OS(os1).\nTS(ts1).\n",
        "3vessel_1obstacle_scenarios/fec1": "OS(os1).\nTS(ts1).\nTS(ts2).\nStaticObstacle(o1).\n",
    }
    for class_id, content in problems.items():
        path = tmp_path / f"{class_id}.problem"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.replace("\n", "\r\n").encode("utf-8"))  # a Windows checkout
    catalog = ClassCatalog(tmp_path)
    monkeypatch.setattr(ClassCatalog, "default", classmethod(lambda cls: catalog))
    return catalog


def test_the_classes_are_the_catalogs_with_their_counts_and_hashes(operator, small_catalog):
    response = operator.get(CLASSES)
    assert response.status_code == 200 and response.headers["x-total-count"] == "4"
    classes = response.json()
    assert [entry["fec_id"] for entry in classes] == [
        "2vessel_0obstacle_scenarios/fec1",
        "2vessel_0obstacle_scenarios/fec2",
        "2vessel_0obstacle_scenarios/fec10",  # numbers in numeric order
        "3vessel_1obstacle_scenarios/fec1",
    ]
    last = classes[-1]
    assert last == {
        "fec_id": "3vessel_1obstacle_scenarios/fec1",
        "folder": "3vessel_1obstacle_scenarios",
        "vessel_count": 3,
        "obstacle_count": 1,
        "content_hash": small_catalog.get(last["fec_id"]).content_hash,
    }
    assert len(last["content_hash"]) == 64 and classes[0]["content_hash"] == classes[2]["content_hash"]  # the same content, the same hash, whatever the line endings


def test_the_classes_can_be_filtered_by_folder_and_pattern(operator, small_catalog):
    def ids(**params):
        response = operator.get(CLASSES, params=params)
        return [entry["fec_id"] for entry in response.json()], int(response.headers["x-total-count"])

    assert ids(folder="3vessel_1obstacle_scenarios") == (["3vessel_1obstacle_scenarios/fec1"], 1)
    assert ids(folder="nothing")[1] == 0
    assert ids(pattern="3vessel_*")[1] == 1  # a pattern without a slash matches folders
    assert ids(pattern="*/fec1")[0] == ["2vessel_0obstacle_scenarios/fec1", "3vessel_1obstacle_scenarios/fec1"]  # one with a slash, class ids
    assert ids(pattern="2vessel_*/fec1*")[1] == 2
    assert ids(pattern="*/fec1", folder="2vessel_0obstacle_scenarios") == (["2vessel_0obstacle_scenarios/fec1"], 1)  # both narrow
    assert ids(pattern="9vessel_*")[1] == 0


def test_the_classes_are_paged_and_the_total_stays(operator, small_catalog):
    second = operator.get(CLASSES, params={"limit": 2, "offset": 1})
    assert [entry["fec_id"] for entry in second.json()] == ["2vessel_0obstacle_scenarios/fec2", "2vessel_0obstacle_scenarios/fec10"]
    assert second.headers["x-total-count"] == "4"
    assert operator.get(CLASSES, params={"offset": 10}).json() == []
    assert len(operator.get(CLASSES, params={"limit": 0}).json()) == 1  # at least one, like the other lists


def test_a_master_without_the_catalog_folder_answers_503(operator, tmp_path, monkeypatch):
    missing = ClassCatalog(tmp_path / "nowhere")
    monkeypatch.setattr(ClassCatalog, "default", classmethod(lambda cls: missing))
    response = operator.get(CLASSES)
    assert response.status_code == 503 and "nowhere" in response.json()["detail"]


def test_the_real_catalog_is_served_in_full(operator):
    catalog = ClassCatalog.default()
    response = operator.get(CLASSES, params={"limit": 1000})
    assert int(response.headers["x-total-count"]) == len(catalog) == len(response.json())
    first = response.json()[0]
    scenario_class = catalog.classes()[0]
    assert (first["fec_id"], first["content_hash"], first["vessel_count"]) == (scenario_class.class_id, scenario_class.content_hash, scenario_class.vessel_count)
    assert {entry["folder"] for entry in response.json()} == set(catalog.folders())


# Stacks


@pytest.fixture
def stacks(operator) -> dict:
    response = operator.get(STACKS)
    assert response.status_code == 200
    return response.json()


def by_id(entries, key="id"):
    return {entry[key]: entry for entry in entries}


def test_the_stack_options_are_the_ones_the_campaign_config_accepts(stacks):
    options = by_id(stacks["stacks"])
    assert set(options) == {f"{layer}.{mode.value}" for layer in ("kinematic", *ARDUPILOT_LAYERS, "gazebo_custom") for mode in KinematicMode}
    for mode in KinematicMode:
        option = options[f"kinematic.{mode.value}"]
        assert option["simulation_layer"] == "kinematic" and option["control_layer"] == "none" and option["mode"] == mode.value
        assert option["stack_section"] == {"simulation_layer": "kinematic", "mode": mode.value}
        assert option["available"] is True and option["reasons"] == []
        assert option["repeatability_tier"] == "exact"
        assert option["supports_early_stop"] is True
        assert {parameter["key"] for parameter in option["parameters"]} == {"dt", "steps"} <= set(KinematicStackConfig.model_fields)
        assert option["environment"] == {"wind": "unsupported", "waves": "unsupported", "interactive_only": False}


@pytest.mark.parametrize("mode", KinematicMode)
def test_the_ardupilot_stacks_are_offered_with_the_parameters_of_the_config_model(stacks, mode):
    options = by_id(stacks["stacks"])
    for layer in ARDUPILOT_LAYERS:
        option = options[f"{layer}.{mode.value}"]
        assert option["simulation_layer"] == layer and option["mode"] == mode.value and option["available"] is True and option["reasons"] == []
        assert option["control_layer"] == "ardupilot" and option["stack_section"] == {"simulation_layer": layer, "mode": mode.value}, "the implied control layer is not written"
        assert option["repeatability_tier"] == "bounded"
        assert option["supports_early_stop"] is False  # the lockstep run always finishes
        replay = {"asv_software": "replay", "control_layer": "ardupilot", "simulation_layer": layer}
        own_ship = {**replay, "asv_software": mode.value}
        assert option["vessels"] == {"own_ship": own_ship, "target_ship": replay}
        assert [group["key"] for group in option["groups"]] == (["usv_navigation"] if mode == KinematicMode.USV_NAVIGATION else []) + ["geofence"]
        parameters = by_id(option["parameters"], "key")
        assert set(parameters) == {"speedup", "dt", "steps"} <= set(ArdupilotStackConfig.model_fields)
        assert parameters["speedup"]["default"] == ArdupilotStackConfig.model_fields["speedup"].default == 1 and parameters["speedup"]["minimum"] == 1
        assert parameters["dt"]["default"] is None and parameters["steps"]["type"] == "integer"
        group = option["groups"][-1]
        assert group["key"] == "geofence" and group["optional"] is True and "workbench" in group["derived_when_absent"]
        fields = by_id(group["parameters"], "key")
        assert set(fields) == set(GeofenceSettings.model_fields) and {key: field["default"] for key, field in fields.items()} == {
            key: field.default for key, field in GeofenceSettings.model_fields.items()
        }
        assert fields["radius_meters"]["unit"] == "m" and fields["latitude"]["maximum"] == 90.0
        assert set(ArdupilotStackConfig.model_fields) == {"simulation_layer", "mode", "usv_navigation", *parameters, group["key"]}


@pytest.mark.parametrize("mode", KinematicMode)
def test_the_custom_controller_is_offered_with_wind_and_waves(stacks, mode):
    option = by_id(stacks["stacks"])[f"gazebo_custom.{mode.value}"]
    assert (option["simulation_layer"], option["control_layer"], option["mode"]) == ("gazebo", "custom", mode.value)
    assert option["stack_section"] == {"simulation_layer": "gazebo", "control_layer": "custom", "mode": mode.value}
    assert option["available"] is True and option["repeatability_tier"] == "bounded" and option["supports_early_stop"] is False
    replay = {"asv_software": "replay", "control_layer": "custom", "simulation_layer": "gazebo"}
    assert option["vessels"] == {"own_ship": {**replay, "asv_software": mode.value}, "target_ship": replay}
    assert option["environment"] == {"wind": "supported", "waves": "supported", "interactive_only": False}
    parameters = by_id(option["parameters"], "key")
    assert set(parameters) == {"dt", "steps"}
    groups = [group["key"] for group in option["groups"]]
    assert groups == (["usv_navigation"] if mode == KinematicMode.USV_NAVIGATION else [])
    assert set(CustomStackConfig.model_fields) == {"simulation_layer", "control_layer", "mode", "usv_navigation", *parameters}


def test_the_ids_are_their_stack_sections(stacks):
    sections = [tuple(sorted(option["stack_section"].items())) for option in stacks["stacks"]]
    assert len(set(sections)) == len(sections)


def test_the_ardupilot_stacks_report_the_environment_the_job_applies(stacks):
    resolver = default_resolver()
    from scenegems_tool.cluster.master.api.catalog_views import _environment_support
    from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig

    for layer in ARDUPILOT_LAYERS:
        replay = VesselStackConfig(AsvSoftwareId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId(layer))
        support = _environment_support(resolver, {"own_ship": replay})
        assert support["waves"] == "supported", "the resolver's stack could carry waves; the ArduPilot simulation jobs run calm water and a campaign refuses them"
        assert by_id(stacks["stacks"])[f"{layer}.replay"]["environment"] == {"wind": "unsupported", "waves": "unsupported", "interactive_only": False}


def test_the_vessel_triples_of_a_stack_are_the_resolvers(stacks):
    options = by_id(stacks["stacks"])
    replay = {"asv_software": "replay", "control_layer": "none", "simulation_layer": "kinematic"}
    assert options["kinematic.replay"]["vessels"] == {"own_ship": replay, "target_ship": replay}
    assert options["kinematic.usv_navigation"]["vessels"] == {"own_ship": {**replay, "asv_software": "usv_navigation"}, "target_ship": replay}


def test_usv_navigation_has_its_parameters_with_their_defaults(stacks):
    option = by_id(stacks["stacks"])["kinematic.usv_navigation"]
    assert by_id(by_id(stacks["stacks"])["kinematic.replay"]["groups"], "key") == {}
    (group,) = option["groups"]
    assert group["key"] == "usv_navigation" and group["optional"] is True and "derived_when_absent" in group
    parameters = by_id(group["parameters"], "key")
    assert set(parameters) == set(UsvNavigationPayload.model_fields)
    assert parameters["prescribed_time"]["default"] == UsvNavigationPayload.model_fields["prescribed_time"].default == 3.0
    assert parameters["runtime_options"]["default"] == {}
    assert {key for key, parameter in parameters.items() if parameter["required"]} == {"goal", "speed", "safety_radius", "control_horizon"}
    assert parameters["speed"]["unit"] == "m/s" and parameters["speed"]["exclusive_minimum"] == 0.0 and parameters["goal"]["type"] == "number_pair"
    assert (parameters["horizon"]["default"], parameters["horizon"]["unit"], parameters["horizon"]["exclusive_minimum"]) == (None, "m", 0.0)
    assert "visibility" in group["derived_when_absent"]


def test_the_monitors_are_the_ones_a_run_names(stacks):
    monitors = by_id(stacks["monitors"])
    assert set(monitors) == {monitor.value for monitor in MonitorImplementation}
    assert {name for name, monitor in monitors.items() if monitor["supports_early_stop"]} == {"live"}
    assert monitors["post_hoc"]["job_types"] == ["monitoring.post_hoc"] and monitors["empty"]["job_types"] == []
    assert monitors["live"]["job_types"] == ["simulation"]  # every runner of the simulation job judges a run in process
    assert all(monitor["label"] and monitor["description"] for monitor in monitors.values())


def test_the_trajectory_generators_list_their_parameters_by_wire_key_with_the_search_defaults(stacks):
    generators = by_id(stacks["trajectory_generators"])
    assert set(generators) == {generator.value for generator in TrajectoryGeneratorImplementation}
    planner = generators["monitor_driven_rrt"]
    parameters = by_id(planner["parameters"], "key")
    assert set(parameters) == set(SEARCH_PARAM_KEYS) and planner["params_field"] == "params"
    assert planner["label"] == "Monitor-guided planner"
    from concrete_level.trajectory_generation.monitor_guided_planner import MonitorGuidedPlanner

    assert parameters["bestRandomNodesK"]["default"] == MonitorGuidedPlanner.BEST_RANDOM_NODES_K == 20
    assert parameters["directionThreshold"]["default"] == MonitorGuidedPlanner.DIRECTION_THRESHOLD
    assert not {"goalSampleRate", "bestLeafSampleRate", "maxLeafs"} & set(parameters)  # the old search's keys the planner never read
    assert parameters["timeStep"]["default"] == 15 and parameters["includeMonitorResults"]["default"] is True
    assert parameters["timeout"]["default"] is None and parameters["maxIterations"]["default"] is None
    straight = generators["straight"]
    assert [(parameter["key"], parameter["required"], parameter["unit"]) for parameter in straight["parameters"]] == [("timespan_s", True, "s")]
    assert straight["params_field"] is None
    for generator in generators.values():
        assert {parameter["key"]: parameter["default"] for parameter in generator["common_parameters"]} == {"timeout_s": TrajectoriesConfig.model_fields["timeout_s"].default}


def test_the_run_fields_name_the_defaults_of_the_run_config(stacks):
    fields = by_id(stacks["run_parameters"], "key")
    assert fields["repeats"]["default"] == RunConfig.model_fields["repeats"].default == 1
    assert fields["early_stop"]["default"] is False
    assert {"name", "seed", "repeats", "early_stop", "environment.wind_vector", "environment.waves"} == set(fields)


def test_every_other_stack_of_the_resolver_is_listed_as_unavailable_with_its_reasons(stacks):
    resolver = default_resolver()
    matrix = resolver.availability_matrix()
    unavailable = stacks["unavailable_stacks"]
    offered = {
        (software, control, layer)
        for software in ("replay", "usv_navigation")
        for control, layer in (("none", "kinematic"), ("ardupilot", "ardupilot_sim"), ("ardupilot", "gazebo"), ("custom", "gazebo"))
    }
    listed = {(entry["asv_software"], entry["control_layer"], entry["simulation_layer"]) for entry in unavailable}
    assert len(unavailable) == len(listed) == len(matrix) - len(offered)
    assert not listed & offered
    assert all(entry["reasons"] and all(isinstance(reason, str) and reason for reason in entry["reasons"]) for entry in unavailable)
    assert stacks["resolver"] == {"combinations": len(matrix), "available": sum(1 for chain in matrix if chain.available)}


def test_the_reasons_tell_why_a_resolver_stack_is_not_a_campaign_stack(stacks):
    entries = {(entry["asv_software"], entry["control_layer"], entry["simulation_layer"]): entry for entry in stacks["unavailable_stacks"]}
    assert ("replay", "ardupilot", "gazebo") not in entries and ("replay", "ardupilot", "ardupilot_sim") not in entries  # offered since P6.6
    assert ("usv_navigation", "ardupilot", "ardupilot_sim") not in entries and ("usv_navigation", "custom", "gazebo") not in entries  # offered since P7.5
    assert not [entry for entry in entries.values() if entry["available_in_resolver"] and "workbench only" not in entry["reasons"][0]], "every available campaign stack is offered"
    impossible = entries[("replay", "ardupilot", "kinematic")]
    assert impossible["status"] == "unavailable" and impossible["design_status"] == "no" and "integrates control internally" in impossible["reasons"][0]
    interactive = entries[("mission_planner", "ardupilot", "gazebo")]
    assert interactive["available_in_resolver"] is True and "workbench only" in interactive["reasons"][0] and interactive["design_status"] == "yes, interactive only"


def test_the_stacks_view_is_plain_json(stacks):
    assert json.loads(json.dumps(stacks, allow_nan=False)) == stacks  # no infinity or NaN from the capabilities


def test_every_offered_stack_is_a_config_the_validation_accepts(stacks):
    for option in stacks["stacks"]:
        section = ", ".join(f"{key}: {value}" for key, value in option["stack_section"].items())
        text = f"name: probe\nscope:\n  - classes: [2vessel_0obstacle_scenarios/fec0]\n    quota: 1\nexecution:\n  runs:\n    - stack: {{{section}}}\n"
        validated = validate_campaign_config(parse_campaign_config(text))
        assert validated.runs[0].repeatability_tier == option["repeatability_tier"]
        (run,) = validated.config.execution.runs
        assert (run.stack.simulation_layer, run.stack.mode.value) == (option["simulation_layer"], option["mode"])
        assert isinstance(run.stack, CustomStackConfig) == (option["control_layer"] == "custom")


# Architecture

ARCHITECTURE = f"{CATALOG_PATH}/architecture"


def test_the_architecture_is_served_as_the_five_documents_in_chain_order(operator, tmp_path, monkeypatch):
    from scenegems_tool.architecture import architecture_files

    monkeypatch.setattr(architecture_files, "ARCHITECTURE_FOLDER", str(tmp_path / "architecture"))  # no files yet: built on request
    response = operator.get(ARCHITECTURE)
    assert response.status_code == 200
    body = response.json()
    assert [document["id"] for document in body["documents"]] == ["design_space_exploration", "scene_generation", "trajectory_generation", "vessel_stack", "monitoring"]
    stack = body["documents"][3]
    assert stack["combinations"] and stack["metamodel_nodes"]
    assert (stack["role"], stack["step"], stack["takes"], stack["job_types"]) == ("step", "Simulation", "trajectories", ["simulation"])
    exploration = body["documents"][0]
    assert (exploration["role"], exploration["gives"], exploration["job_types"]) == ("step", "FECs", ["design_space_exploration"])


def test_the_architecture_is_served_from_the_files_written_at_startup(operator, tmp_path, monkeypatch):
    from scenegems_tool.architecture import architecture_files

    monkeypatch.setattr(architecture_files, "ARCHITECTURE_FOLDER", str(tmp_path))
    architecture_files.write_architecture_files()
    path = tmp_path / "monitoring.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("title: Monitoring", "title: From the file", 1), encoding="utf-8")
    titles = {document["id"]: document["title"] for document in operator.get(ARCHITECTURE).json()["documents"]}
    assert titles["monitoring"] == "From the file"


def test_a_class_answers_its_functional_scenario_as_text(operator, small_catalog):
    response = operator.get(f"{CLASSES}/3vessel_1obstacle_scenarios/fec1")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/plain")
    assert response.text == "OS(os1).\nTS(ts1).\nTS(ts2).\nStaticObstacle(o1).\n"  # LF line endings from a Windows checkout
    assert operator.get(f"{CLASSES}/3vessel_1obstacle_scenarios/fec99").status_code == 404


def test_a_class_content_needs_the_catalog_folder(operator, tmp_path, monkeypatch):
    missing = ClassCatalog(tmp_path / "missing")
    monkeypatch.setattr(ClassCatalog, "default", classmethod(lambda cls: missing))
    assert operator.get(f"{CLASSES}/2vessel_0obstacle_scenarios/fec1").status_code == 503


def test_the_domain_presets_are_the_masters_files(operator):
    from scenegems_tool.assurance.campaign.domain_presets import domain_presets

    response = operator.get(f"{CATALOG_PATH}/domain-presets")
    assert response.status_code == 200
    listed = response.json()
    expected = domain_presets()
    assert set(listed) == {"colregs_constants", "vessel_types", "obstacle_types"}
    for key, presets in listed.items():
        assert presets == [{"name": preset.name, "default": preset.default, "content": preset.content} for preset in expected[key]]
    assert [preset["name"] for preset in listed["colregs_constants"] if preset["default"]] == ["general_maritime_constants"]


# Design space


def test_the_design_space_default_is_the_shipped_specification_and_scope(operator):
    from scenegems_tool.subsystems.design_space_exploration.design_space import DEFAULT_SCOPE, default_specification, parse_scope

    response = operator.get(f"{CATALOG_PATH}/design-space")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"specification", "scope"}
    assert body["specification"] == default_specification() and "\r" not in body["specification"]
    assert body["scope"] == DEFAULT_SCOPE and parse_scope(body["scope"])
