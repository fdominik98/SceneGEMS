"""Runs on the ArduPilot stacks and the custom controller in the stage graph and the payload builder: the simulate step's components, its images, and the ardupilot and gazebo_custom runners' payloads."""

import pytest

from scenegems_tool.assurance.campaign import campaign_config_from_dict
from scenegems_tool.assurance.pipeline.payload_builder import PayloadBuilder, PayloadError, required_fingerprints, validate_payload
from scenegems_tool.assurance.pipeline.stage_graph import STAGE_JOB_TYPES, StageGraph, Step
from scenegems_tool.cluster.fingerprints.comparison import by_repository, repositories
from scenegems_tool.cluster.fingerprints.components import SCENARIO_EXECUTION_IMAGE
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.jobs.job_types import payload_components
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.ardupilot_runner import ArduPilotSimulationPayload
from scenegems_tool.persistence.schema import PipelineStage
from tests.scenegems_tool.assurance.pipeline.conftest import CLASS_A, config_dict, format2_dict, input_ref
from tests.scenegems_tool.assurance.pipeline.fake_executor import EXPECTED
from tests.scenegems_tool.cluster.payloads import trajectories_data
from tests.scenegems_tool.cluster.stack_images import GAZEBO_IMAGE, SITL_IMAGE

SIMULATE, MONITOR, CALIBRATE = PipelineStage.SIMULATE, PipelineStage.MONITOR, PipelineStage.CALIBRATE
SIMULATION = JobType.SIMULATION
ON_KINEMATIC = ("asv_software/replay", "control_layer/none", "simulation_layer/kinematic")
ON_SITL = ("asv_software/replay", "control_layer/ardupilot", "simulation_layer/ardupilot_sim")
ON_GAZEBO = ("asv_software/replay", "control_layer/ardupilot", "simulation_layer/gazebo")
KINEMATIC = {"monitor": "post_hoc"}
SITL = {"stack": {"simulation_layer": "ardupilot_sim"}, "monitor": "post_hoc"}
GAZEBO = {"stack": {"simulation_layer": "gazebo", "speedup": 4, "dt": 2, "steps": 20, "geofence": {"latitude": 58.5, "longitude": 15.5, "radius_meters": 40}}, "monitor": "live", "seed": 77}
TRAJECTORY_RESULT = {"valid": True, "complete": True, "trajectory_data": {"trajectories": trajectories_data()}}


def _graph(*runs) -> StageGraph:
    return StageGraph(campaign_config_from_dict(config_dict(runs=list(runs))))


def _builder(*runs, **sections) -> PayloadBuilder:
    return PayloadBuilder(campaign_config_from_dict(config_dict(runs=list(runs), **sections)))


# The stage graph


def test_every_simulate_step_is_a_simulation_job_needing_its_runs_components():
    graph = _graph(KINEMATIC, SITL, GAZEBO)
    assert [graph.job_type_of(Step(SIMULATE, run, 0)) for run in range(3)] == [SIMULATION] * 3
    assert [graph.run_components(run) for run in range(3)] == [ON_KINEMATIC, ON_SITL, ON_GAZEBO]
    assert graph.job_type_of(Step(MONITOR, 1)) == JobType.MONITORING_POST_HOC and graph.job_type_of(Step(CALIBRATE, 2)) == JobType.CALIBRATION_DEVIATION
    assert Step(SIMULATE, 1, 0).job_type == SIMULATION


def test_a_stage_lists_the_components_its_runs_need():
    graph = _graph(KINEMATIC, SITL, SITL, GAZEBO)
    assert graph.stage_needs(SIMULATE) == [(SIMULATION, ON_KINEMATIC), (SIMULATION, ON_SITL), (SIMULATION, ON_GAZEBO)]
    assert graph.stage_needs(MONITOR) == [(JobType.MONITORING_POST_HOC, ("monitoring",))] and graph.stage_needs(PipelineStage.VERDICT) == []
    assert graph.stage_needs(CALIBRATE) == [(JobType.CALIBRATION_DEVIATION, ("calibration",))]
    assert StageGraph(campaign_config_from_dict(format2_dict(["scene_generation"]))).stage_needs(SIMULATE) == [], "a campaign without runs simulates nothing"


def test_usv_navigation_on_the_kinematic_layer_needs_replay_too_for_the_targets():
    graph = _graph({"stack": {"simulation_layer": "kinematic", "mode": "usv_navigation"}})
    assert graph.run_components(0) == ("asv_software/replay", "asv_software/usv_navigation", "control_layer/none", "simulation_layer/kinematic")


@pytest.mark.parametrize("run", [KINEMATIC, {"stack": {"simulation_layer": "kinematic", "mode": "usv_navigation"}}, SITL, GAZEBO])
def test_a_runs_components_are_the_ones_the_control_node_computes_from_its_payload(run):
    graph = _graph(run)
    assert graph.run_components(0) == payload_components(SIMULATION, _builder(run).simulation(5, 0, TRAJECTORY_RESULT))


def test_a_run_knows_its_images_and_tier():
    graph = _graph(KINEMATIC, SITL, GAZEBO)
    assert [graph.run_tier(run) for run in range(3)] == [None, "bounded", "bounded"]
    assert [required_fingerprints(graph.run_components(run), EXPECTED) for run in range(3)] == [
        by_repository({SCENARIO_EXECUTION_IMAGE: "fp-execution"}),
        by_repository({SCENARIO_EXECUTION_IMAGE: "fp-execution", SITL_IMAGE: "fp-sitl"}),
        by_repository({SCENARIO_EXECUTION_IMAGE: "fp-execution", SITL_IMAGE: "fp-sitl", GAZEBO_IMAGE: "fp-gazebo"}),
    ]
    assert STAGE_JOB_TYPES[SIMULATE] == JobType.SIMULATION


# The payloads


def test_a_sitl_run_gets_the_trajectories_the_geofence_and_the_observed_run_back():
    payload = _builder(SITL).simulation(5, 0, TRAJECTORY_RESULT)
    assert payload == {
        "runner": "ardupilot",
        "simulation_layer": "ardupilot_sim",
        "mode": "replay",
        "trajectories": TRAJECTORY_RESULT["trajectory_data"]["trajectories"],
        "geofence": {"latitude": 57.76080082972655, "longitude": 16.680965995056, "radius_meters": 20.0},
        "speedup": 1,
        "seed": payload["seed"],
        "include_states": False,
        "include_trajectories": True,
    }, "a post hoc run has no monitor in the job"
    assert validate_payload(SIMULATION, payload) == ON_SITL
    assert ArduPilotSimulationPayload.model_validate(payload).include_trajectories is True


def test_a_gazebo_run_with_the_live_monitor_carries_its_settings():
    builder = _builder(GAZEBO)
    payload = builder.simulation(5, 0, TRAJECTORY_RESULT)
    assert (payload["simulation_layer"], payload["speedup"], payload["dt"], payload["steps"], payload["seed"]) == ("gazebo", 4, 2.0, 20, 77)
    assert payload["geofence"] == {"latitude": 58.5, "longitude": 15.5, "radius_meters": 40.0}
    assert payload["monitor"] == "live" and payload["colregs_constraints_content"] == builder.config.domain.colregs_constants
    assert "early_stop" not in payload and payload["include_trajectories"] is True
    assert validate_payload(SIMULATION, payload) == ON_GAZEBO


def test_a_run_that_names_no_seed_takes_the_case_seed():
    builder = _builder(SITL, {**SITL, "seed": None})
    assert builder.simulation(5, 0, TRAJECTORY_RESULT)["seed"] == 5
    assert builder.simulation(6, 0, TRAJECTORY_RESULT)["seed"] == 6


def test_an_empty_monitor_run_gets_no_monitor_either():
    payload = _builder({"stack": {"simulation_layer": "ardupilot_sim"}, "monitor": "empty"}).simulation(5, 0, TRAJECTORY_RESULT)
    assert "monitor" not in payload and payload["include_trajectories"] is True


def test_an_item_reference_reaches_the_ardupilot_payload_as_it_does_the_kinematic_one():
    data = b'{"trajectories": 1}'
    ref = input_ref(data, "trajectory_data")
    config = campaign_config_from_dict(format2_dict(["simulation"], runs=[KINEMATIC, SITL], input={"items": [{"name": "planned", "ref": ref, "source": {"file": "a.json"}}]}))
    builder = PayloadBuilder(config)
    item = config.input.items[0]
    kinematic, ardupilot = builder.simulation_of_item(3, 0, item), builder.simulation_of_item(3, 1, item)
    assert kinematic["trajectories"] == ardupilot["trajectories"] and ardupilot["trajectories"]["pointer"] == "/trajectories"
    assert validate_payload(SIMULATION, ardupilot) == ON_SITL


def test_the_submission_has_the_runs_components_the_images_and_the_stage_priority():
    builder = _builder(KINEMATIC, SITL, GAZEBO, resources={"priority": 10})
    jobs = []
    for run in range(3):
        step = Step(SIMULATE, run, 0)
        jobs.append(builder.submission(step, builder.simulation(5, run, TRAJECTORY_RESULT), step.idempotency_key("c1", 1), EXPECTED))
    assert [job.job_type for job in jobs] == [SIMULATION] * 3
    assert [tuple(job.requirements.components) for job in jobs] == [ON_KINEMATIC, ON_SITL, ON_GAZEBO]
    assert [set(job.requirements.fingerprints) for job in jobs] == [
        set(repositories(images)) for images in ([SCENARIO_EXECUTION_IMAGE], [SCENARIO_EXECUTION_IMAGE, SITL_IMAGE], [SCENARIO_EXECUTION_IMAGE, SITL_IMAGE, GAZEBO_IMAGE])
    ]
    assert {job.priority for job in jobs} == {12} and jobs[1].idempotency_key == "campaign:c1:case:1:simulate:1:0"


def test_the_post_hoc_monitor_and_the_calibration_take_the_observed_trajectories():
    builder = _builder(SITL)
    result = {"run_record": {"repeatability_tier": "bounded"}, "trajectories": trajectories_data(), "state_digest": "d" * 64}
    monitoring = builder.post_hoc_monitoring(f"{CLASS_A}#0#run0", result)
    assert monitoring["trajectories"] == trajectories_data()
    validate_payload(JobType.MONITORING_POST_HOC, monitoring)
    calibration = builder.calibration(f"{CLASS_A}#0", {"simulation_layer": "ardupilot_sim"}, [result, result])
    validate_payload(JobType.CALIBRATION_DEVIATION, calibration)


@pytest.mark.parametrize("layer, components", [("ardupilot_sim", ON_SITL), ("gazebo", ON_GAZEBO)])
def test_the_payload_model_accepts_what_the_builder_sends_with_every_option(layer, components):
    run = {"stack": {"simulation_layer": layer, "speedup": 2, "dt": 1, "steps": 5}, "monitor": "live"}
    assert validate_payload(SIMULATION, _builder(run).simulation(1, 0, TRAJECTORY_RESULT)) == components


def test_an_ardupilot_payload_needs_its_layer_and_the_kinematic_runner_refuses_its_fields():
    payload = _builder(GAZEBO).simulation(5, 0, TRAJECTORY_RESULT)
    with pytest.raises(PayloadError, match="simulation_layer"):
        validate_payload(SIMULATION, {key: value for key, value in payload.items() if key != "simulation_layer"})
    with pytest.raises(PayloadError, match="geofence"):
        validate_payload(SIMULATION, {**payload, "runner": "kinematic"})


# USV Navigation on ArduPilot and the custom controller on Gazebo

USV_NAVIGATION = {"goal": [3000.0, 0.0], "speed": 8.0, "safety_radius": 120.0, "control_horizon": 60.0}
SITL_USV_NAVIGATION = {"stack": {"simulation_layer": "ardupilot_sim", "mode": "usv_navigation", "usv_navigation": USV_NAVIGATION}, "monitor": "live"}
CUSTOM = {"stack": {"simulation_layer": "gazebo", "control_layer": "custom"}, "environment": {"wind_vector": [0.0, 3.0, 0.0]}, "monitor": "post_hoc"}
CUSTOM_USV_NAVIGATION = {"stack": {"simulation_layer": "gazebo", "control_layer": "custom", "mode": "usv_navigation", "dt": 2, "steps": 20}, "monitor": "live", "seed": 9}
ON_CUSTOM = ("asv_software/replay", "control_layer/custom", "simulation_layer/gazebo")


@pytest.mark.parametrize("run", [SITL_USV_NAVIGATION, CUSTOM, CUSTOM_USV_NAVIGATION])
def test_the_new_stacks_components_are_the_ones_the_control_node_computes_from_their_payloads(run):
    assert _graph(run).run_components(0) == validate_payload(SIMULATION, _builder(run).simulation(5, 0, TRAJECTORY_RESULT))


def test_the_new_stacks_need_their_layers_images_and_are_bounded():
    graph = _graph(SITL_USV_NAVIGATION, CUSTOM, CUSTOM_USV_NAVIGATION)
    assert graph.run_components(0) == ("asv_software/replay", "asv_software/usv_navigation", "control_layer/ardupilot", "simulation_layer/ardupilot_sim")
    assert graph.run_components(1) == ON_CUSTOM
    assert graph.run_components(2) == ("asv_software/replay", "asv_software/usv_navigation", "control_layer/custom", "simulation_layer/gazebo")
    assert [graph.run_tier(run) for run in range(3)] == ["bounded"] * 3
    assert required_fingerprints(graph.run_components(1), EXPECTED) == by_repository({SCENARIO_EXECUTION_IMAGE: "fp-execution", GAZEBO_IMAGE: "fp-gazebo"}), "no SITL"
    assert graph.stage_needs(SIMULATE) == [(SIMULATION, graph.run_components(run)) for run in range(3)]


def test_usv_navigation_on_ardupilot_carries_its_mode_and_parameters():
    payload = _builder(SITL_USV_NAVIGATION).simulation(5, 0, TRAJECTORY_RESULT)
    assert (payload["runner"], payload["mode"], payload["usv_navigation"]["goal"], payload["monitor"]) == ("ardupilot", "usv_navigation", [3000.0, 0.0], "live")
    assert "own_ship_id" not in payload, "the scene's own ship"


def test_a_custom_run_carries_its_environment_and_no_ardupilot_fields():
    payload = _builder(CUSTOM).simulation(5, 0, TRAJECTORY_RESULT)
    assert payload == {
        "runner": "gazebo_custom",
        "mode": "replay",
        "trajectories": TRAJECTORY_RESULT["trajectory_data"]["trajectories"],
        "environment": {"wind_vector": [0.0, 3.0, 0.0], "waves": None},
        "seed": payload["seed"],
        "include_trajectories": True,
    }


def test_a_custom_usv_navigation_run_with_the_live_monitor_carries_its_settings():
    payload = _builder(CUSTOM_USV_NAVIGATION).simulation(5, 0, TRAJECTORY_RESULT)
    assert (payload["mode"], payload["dt"], payload["steps"], payload["seed"], payload["monitor"]) == ("usv_navigation", 2.0, 20, 9, "live")
    assert payload["colregs_constraints_content"]
