"""Payload validation of every job type: bad payloads fail for good before any container starts."""

import json

import pytest

from scenegems_tool.cluster.node.job_report import JobFailed
from scenegems_tool.cluster.node.jobs import simulation_job
from scenegems_tool.cluster.node.jobs.calibration_deviation_job import CalibrationDeviationPayload
from scenegems_tool.cluster.node.jobs.job_payload import parse_payload, validate_structure
from scenegems_tool.cluster.node.jobs.live_monitor import SimulationMonitor
from scenegems_tool.cluster.node.jobs.monitoring_post_hoc_job import PostHocMonitoringPayload
from scenegems_tool.cluster.node.jobs.scene_generation_job import SceneGenerationPayload
from scenegems_tool.cluster.node.jobs.simulation_runners.ardupilot_runner import ArduPilotSimulationLayer, ArduPilotSimulationPayload
from scenegems_tool.cluster.node.jobs.simulation_runners.kinematic_runner import KinematicMode, KinematicSimulationPayload, UsvNavigationPayload
from scenegems_tool.cluster.node.jobs.trajectory_generation_job import TrajectoryGenerationPayload
from scenegems_tool.cluster.protocol.artifacts import find_references, resolve_references
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import TrajectoryGenerationParams, TrajectoryGeneratorId
from utils.file_system_utils import FUNCTIONAL_MODELS_FOLDER

GEOFENCE = {"latitude": 57.7, "longitude": 11.9, "radius_meters": 2000.0}


@pytest.fixture
def trajectories(head_on_trajectories):
    return head_on_trajectories.to_dict()


def test_kinematic_payload_defaults(trajectories):
    payload = KinematicSimulationPayload.model_validate({"runner": "kinematic", "trajectories": trajectories})
    assert payload.mode == KinematicMode.REPLAY
    assert (payload.dt, payload.steps, payload.seed, payload.include_trajectories) == (None, None, 0, True)


def test_kinematic_closed_loop_payload_with_parameters(trajectories):
    payload = KinematicSimulationPayload.model_validate(
        {
            "runner": "kinematic",
            "mode": "usv_navigation",
            "trajectories": trajectories,
            "own_ship_id": 0,
            "usv_navigation": {"goal": [2000.0, 0.0], "speed": 8.0, "safety_radius": 120.0, "control_horizon": 60.0},
        }
    )
    parameters = payload.usv_navigation.to_parameters()
    assert parameters.goal == (2000.0, 0.0)
    assert parameters.prescribed_time == 3.0
    assert parameters.horizon is None


USV_NAVIGATION = {"goal": [2000.0, 0.0], "speed": 8.0, "safety_radius": 120.0, "control_horizon": 60.0}


def test_usv_navigation_horizon_reaches_the_parameters_and_the_json():
    payload = UsvNavigationPayload.model_validate({**USV_NAVIGATION, "horizon": 5000.0})
    assert payload.to_parameters().horizon == 5000.0
    assert payload.model_dump(mode="json")["horizon"] == 5000.0


def test_an_absent_usv_navigation_horizon_stays_out_of_the_json():
    payload = UsvNavigationPayload.model_validate(USV_NAVIGATION)
    assert "horizon" not in payload.model_dump(mode="json")
    assert UsvNavigationPayload.model_validate(payload.model_dump(mode="json")).horizon is None


def test_a_usv_navigation_horizon_must_be_positive():
    with pytest.raises(ValueError, match="horizon"):
        UsvNavigationPayload.model_validate({**USV_NAVIGATION, "horizon": 0.0})


@pytest.mark.parametrize(
    "change",
    [
        {"mode": "replay", "own_ship_id": 0},
        {"mode": "teleport"},
        {"dt": 0},
        {"steps": 0},
        {"unknown_field": 1},
        {"trajectories": {"time_step": 1}},
        {"trajectories": {"time_step": 1, "scene_list": []}},
    ],
)
def test_invalid_kinematic_payloads_are_rejected(trajectories, change):
    with pytest.raises(ValueError):
        KinematicSimulationPayload.model_validate({"runner": "kinematic", "trajectories": trajectories, **change})


def test_ardupilot_payload(trajectories):
    payload = ArduPilotSimulationPayload.model_validate({"runner": "ardupilot", "simulation_layer": "gazebo", "trajectories": trajectories, "geofence": GEOFENCE, "speedup": 5})
    assert payload.simulation_layer == ArduPilotSimulationLayer.GAZEBO
    assert payload.geofence.to_geofence().radius_meters == 2000.0


def test_ardupilot_payload_monitor_defaults_and_live(trajectories):
    base = {"runner": "ardupilot", "simulation_layer": "ardupilot_sim", "trajectories": trajectories, "geofence": GEOFENCE}
    payload = ArduPilotSimulationPayload.model_validate(base)
    assert (payload.monitor, payload.colregs_constraints_content, payload.include_trajectories) == (SimulationMonitor.NONE, None, False)
    live = ArduPilotSimulationPayload.model_validate({**base, "monitor": "live", "colregs_constraints_content": "rules", "include_trajectories": True, "dt": 2.0})
    assert live.monitor == SimulationMonitor.LIVE and live.colregs_constraints_content == "rules" and live.include_trajectories


@pytest.mark.parametrize(
    "change",
    [
        {"simulation_layer": "kinematic"},
        {"speedup": 0},
        {"geofence": {**GEOFENCE, "latitude": 91.0}},
        {"geofence": None},
        {"monitor": "post_hoc"},
        {"colregs_constraints_content": "rules"},  # only with the live monitor
        {"monitor": "live", "dt": 0.5},  # the monitor needs whole seconds
        {"include_trajectories": True, "dt": 0.5},  # so do trajectories
    ],
)
def test_invalid_ardupilot_payloads_are_rejected(trajectories, change):
    with pytest.raises(ValueError):
        ArduPilotSimulationPayload.model_validate({"runner": "ardupilot", "simulation_layer": "ardupilot_sim", "trajectories": trajectories, "geofence": GEOFENCE, **change})


def test_post_hoc_payload_defaults(trajectories):
    payload = PostHocMonitoringPayload.model_validate({"trajectories": trajectories})
    assert payload.colregs_constraints_content is None
    assert not payload.include_frames


def test_trajectory_generation_params_are_checked():
    base = {"scenario_content": "{}", "colregs_constraints_content": ""}
    TrajectoryGenerationPayload.model_validate({**base, "params": {"maxIterations": 100, "timeout": 30}})
    with pytest.raises(ValueError):
        TrajectoryGenerationPayload.model_validate({**base, "params": {"max_iterations": 100}})
    with pytest.raises(ValueError):
        TrajectoryGenerationPayload.model_validate({**base, "params": {"maxIterations": "many"}})


def test_trajectory_generation_drops_the_retired_search_keys():
    base = {"scenario_content": "{}", "colregs_constraints_content": ""}
    retired = {"goalSampleRate": 50, "bestLeafSampleRate": 90, "maxLeafs": 500}
    payload = TrajectoryGenerationPayload.model_validate({**base, "params": {"maxIterations": 100, **retired}})
    assert payload.params == {"maxIterations": 100}
    with pytest.raises(ValueError):
        TrajectoryGenerationPayload.model_validate({**base, "params": {**retired, "goalSampleRates": 5}})


def test_scene_generation_payload_parses_the_functional_scenario():
    with open(f"{FUNCTIONAL_MODELS_FOLDER}/all/2vessel_0obstacle_scenarios/fec0.problem", encoding="utf-8") as file:
        problem = file.read()
    contents = {"colregs_constraints_content": "", "vessel_types_content": "", "obstacle_types_content": ""}
    assert SceneGenerationPayload.model_validate({"functional_scenario_content": problem, **contents}).timeout_s == 60
    with pytest.raises(ValueError):
        SceneGenerationPayload.model_validate({"functional_scenario_content": "class {", **contents})


def test_parse_payload_turns_validation_errors_into_final_failures(make_job):
    job = make_job(JobType.SIMULATION, {"runner": "kinematic", "trajectories": {}})
    with pytest.raises(JobFailed) as failure:
        parse_payload(KinematicSimulationPayload, job)
    assert not failure.value.retryable
    assert "Invalid simulation payload" in str(failure.value)


# Artifact references and seeds (protocol version 2)

REFERENCE = {"sha256": "ab" * 32, "size_bytes": 100, "kind": "trajectories"}


@pytest.mark.parametrize(
    "model, payload",
    [
        (KinematicSimulationPayload, {"runner": "kinematic", "trajectories": REFERENCE}),
        (ArduPilotSimulationPayload, {"runner": "ardupilot", "simulation_layer": "ardupilot_sim", "trajectories": REFERENCE, "geofence": GEOFENCE}),
        (PostHocMonitoringPayload, {"trajectories": REFERENCE}),
        (TrajectoryGenerationPayload, {"scenario_content": {**REFERENCE, "kind": "scene"}, "colregs_constraints_content": ""}),
        (CalibrationDeviationPayload, {"trajectories": [REFERENCE, {**REFERENCE, "sha256": "cd" * 32}], "reference": "head_on"}),
    ],
)
def test_artifact_fields_take_a_reference_checked_for_shape_only(model, payload):
    validated = validate_structure(model, payload)
    assert find_references(validated)
    field = "scenario_content" if "scenario_content" in payload else "trajectories"
    broken = [{**REFERENCE, "sha256": "short"}, REFERENCE] if isinstance(payload[field], list) else {**REFERENCE, "sha256": "short"}
    with pytest.raises(ValueError):
        validate_structure(model, {**payload, field: broken})


def test_parse_payload_refuses_an_unresolved_reference(make_job):
    job = make_job(JobType.SIMULATION, {"runner": "kinematic", "trajectories": REFERENCE})
    with pytest.raises(JobFailed) as failure:
        parse_payload(KinematicSimulationPayload, job)
    assert not failure.value.retryable
    assert "trajectories" in str(failure.value) and "artifact references" in str(failure.value)


def test_content_is_checked_once_the_reference_is_resolved(make_job, trajectories):
    """The node resolves the declared fields, then parse_payload checks the content like inline data."""
    good = json.dumps(trajectories).encode()
    bad = json.dumps({"time_step": 1, "scene_list": []}).encode()
    for data, valid in ((good, True), (bad, False)):
        resolved = resolve_references({"runner": "kinematic", "trajectories": REFERENCE}, simulation_job.ARTIFACT_INPUT_FIELDS, lambda reference: data)
        job = make_job(JobType.SIMULATION, resolved)
        if valid:
            assert parse_payload(KinematicSimulationPayload, job).trajectories == json.loads(good)
        else:
            with pytest.raises(JobFailed, match="no scene"):
                parse_payload(KinematicSimulationPayload, job)


@pytest.mark.parametrize("model", [SceneGenerationPayload, TrajectoryGenerationPayload])
def test_generation_seeds_are_optional_and_bounded(model):
    if model is SceneGenerationPayload:
        with open(f"{FUNCTIONAL_MODELS_FOLDER}/all/1vessel_0obstacle_scenarios/fec0.problem", encoding="utf-8") as file:
            base = {"functional_scenario_content": file.read(), "colregs_constraints_content": "", "vessel_types_content": "", "obstacle_types_content": ""}
    else:
        base = {"scenario_content": "{}", "colregs_constraints_content": ""}
    assert model.model_validate(base).seed is None
    assert model.model_validate({**base, "seed": 0}).seed == 0
    assert model.model_validate({**base, "seed": 2**31 - 1}).seed == 2**31 - 1
    for seed in (-1, 2**31):
        with pytest.raises(ValueError):
            model.model_validate({**base, "seed": seed})


def test_trajectory_generator_choice_is_a_search_parameter():
    base = {"scenario_content": "{}", "colregs_constraints_content": ""}
    payload = TrajectoryGenerationPayload.model_validate({**base, "params": {"generator": "straight", "timespan": 600}})
    params = TrajectoryGenerationParams.from_wire(payload.params)
    assert params.generator_id == TrajectoryGeneratorId.STRAIGHT and params.timespan == 600.0
    assert TrajectoryGenerationParams.from_wire({}).generator_id == TrajectoryGeneratorId.MONITOR_DRIVEN_RRT
    for params in ({"generator": "teleport"}, {"generator": "straight", "timespan": 0}, {"timespan": -5}, {"maxIterations": [1]}, {"generator": ["straight"]}):
        with pytest.raises(ValueError):
            TrajectoryGenerationPayload.model_validate({**base, "params": params})


def test_kinematic_monitor_options(trajectories):
    payload = KinematicSimulationPayload.model_validate({"runner": "kinematic", "trajectories": trajectories})
    assert (payload.monitor, payload.early_stop) == (SimulationMonitor.NONE, False)
    live = KinematicSimulationPayload.model_validate({"runner": "kinematic", "trajectories": trajectories, "monitor": "live", "early_stop": True, "dt": 2.0, "colregs_constraints_content": "x: 1"})
    assert live.monitor == SimulationMonitor.LIVE and live.early_stop
    for change in ({"early_stop": True}, {"colregs_constraints_content": ""}, {"monitor": "live", "dt": 0.5}, {"monitor": "post_hoc"}):
        with pytest.raises(ValueError):
            KinematicSimulationPayload.model_validate({"runner": "kinematic", "trajectories": trajectories, **change})


def test_calibration_payload_needs_two_repeats_and_a_reference(trajectories):
    payload = CalibrationDeviationPayload.model_validate({"trajectories": [trajectories, trajectories], "stack": {"stack": "replay/none/kinematic"}, "reference": "head_on"})
    assert len(payload.trajectories) == 2 and payload.stack == {"stack": "replay/none/kinematic"}
    for change in ({"trajectories": [trajectories]}, {"reference": ""}, {"trajectories": [trajectories, {"time_step": 1, "scene_list": []}]}):
        with pytest.raises(ValueError):
            CalibrationDeviationPayload.model_validate({"trajectories": [trajectories, trajectories], "reference": "head_on", **change})
