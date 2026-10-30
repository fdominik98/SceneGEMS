"""Runs on the ArduPilot stacks in the stage graph and the payload builder: the simulate step's job type, its images, and the simulation.ardupilot_sim and simulation.gazebo payloads."""

import pytest

from scenegems_tool.assurance.campaign import campaign_config_from_dict
from scenegems_tool.assurance.pipeline.payload_builder import PayloadBuilder, PayloadError, required_fingerprints, validate_payload
from scenegems_tool.assurance.pipeline.stage_graph import STAGE_JOB_TYPES, StageGraph, Step, simulation_job_type
from scenegems_tool.cluster.fingerprints.job_images import SCENARIO_EXECUTION_IMAGE
from scenegems_tool.cluster.node.jobs.simulation_ardupilot_job import ArduPilotSimulationPayload
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.persistence.schema import PipelineStage
from tests.scenegems_tool.assurance.pipeline.conftest import CLASS_A, config_dict, format2_dict, input_ref
from tests.scenegems_tool.assurance.pipeline.fake_executor import EXPECTED
from tests.scenegems_tool.cluster.payloads import trajectories_data
from tests.scenegems_tool.cluster.stack_images import GAZEBO_IMAGE, SITL_IMAGE

SIMULATE, MONITOR, CALIBRATE = PipelineStage.SIMULATE, PipelineStage.MONITOR, PipelineStage.CALIBRATE
ON_SITL, ON_GAZEBO = JobType.SIMULATION_ARDUPILOT_SIM, JobType.SIMULATION_GAZEBO
KINEMATIC = {"monitor": "post_hoc"}
SITL = {"stack": {"simulation_layer": "ardupilot_sim"}, "monitor": "post_hoc"}
GAZEBO = {"stack": {"simulation_layer": "gazebo", "speedup": 4, "dt": 2, "steps": 20, "geofence": {"latitude": 58.5, "longitude": 15.5, "radius_meters": 40}}, "monitor": "live", "seed": 77}
TRAJECTORY_RESULT = {"valid": True, "complete": True, "trajectory_data": {"trajectories": trajectories_data()}}


def _graph(*runs) -> StageGraph:
    return StageGraph(campaign_config_from_dict(config_dict(runs=list(runs))))


def _builder(*runs, **sections) -> PayloadBuilder:
    return PayloadBuilder(campaign_config_from_dict(config_dict(runs=list(runs), **sections)))


# The stage graph


def test_the_simulate_step_takes_its_job_type_from_the_runs_stack():
    graph = _graph(KINEMATIC, SITL, GAZEBO)
    assert [graph.job_type_of(Step(SIMULATE, run, 0)) for run in range(3)] == [JobType.SIMULATION_KINEMATIC, ON_SITL, ON_GAZEBO]
    assert graph.job_type_of(Step(MONITOR, 1)) == JobType.MONITORING_POST_HOC and graph.job_type_of(Step(CALIBRATE, 2)) == JobType.CALIBRATION_DEVIATION
    assert Step(SIMULATE, 1, 0).job_type == JobType.SIMULATION_KINEMATIC, "the step alone knows only the stage's default"


def test_a_stage_lists_the_job_types_its_runs_need():
    graph = _graph(KINEMATIC, SITL, SITL, GAZEBO)
    assert graph.stage_jobs(SIMULATE) == [JobType.SIMULATION_KINEMATIC, ON_SITL, ON_GAZEBO]
    assert graph.stage_jobs(MONITOR) == [JobType.MONITORING_POST_HOC] and graph.stage_jobs(PipelineStage.VERDICT) == []
    assert StageGraph(campaign_config_from_dict(format2_dict(["scene_generation"]))).stage_jobs(SIMULATE) == [JobType.SIMULATION_KINEMATIC], "a campaign without runs keeps the default"


def test_a_run_knows_its_job_images_and_tier():
    graph = _graph(KINEMATIC, SITL, GAZEBO)
    assert [graph.run_job_type(run) for run in range(3)] == [JobType.SIMULATION_KINEMATIC, ON_SITL, ON_GAZEBO]
    assert [graph.run_tier(run) for run in range(3)] == [None, "bounded", "bounded"]
    stacks = [run.stack for run in graph.runs]
    assert [simulation_job_type(stack) for stack in stacks] == [JobType.SIMULATION_KINEMATIC, ON_SITL, ON_GAZEBO]
    assert [required_fingerprints(graph.run_job_type(run), EXPECTED) for run in range(3)] == [
        {SCENARIO_EXECUTION_IMAGE: "fp-execution"},
        {SCENARIO_EXECUTION_IMAGE: "fp-execution", SITL_IMAGE: "fp-sitl"},
        {SCENARIO_EXECUTION_IMAGE: "fp-execution", SITL_IMAGE: "fp-sitl", GAZEBO_IMAGE: "fp-gazebo"},
    ]
    assert STAGE_JOB_TYPES[SIMULATE] == JobType.SIMULATION_KINEMATIC


# The payloads


def test_a_sitl_run_gets_the_trajectories_the_geofence_and_the_observed_run_back():
    payload = _builder(SITL).simulation(5, 0, TRAJECTORY_RESULT)
    assert payload == {
        "simulation_layer": "ardupilot_sim",
        "trajectories": TRAJECTORY_RESULT["trajectory_data"]["trajectories"],
        "geofence": {"latitude": 57.76080082972655, "longitude": 16.680965995056, "radius_meters": 20.0},
        "speedup": 1,
        "seed": payload["seed"],
        "include_states": False,
        "include_trajectories": True,
    }, "a post hoc run has no monitor in the job"
    validate_payload(ON_SITL, payload)
    assert ArduPilotSimulationPayload.model_validate(payload).include_trajectories is True


def test_a_gazebo_run_with_the_live_monitor_carries_its_settings():
    builder = _builder(GAZEBO)
    payload = builder.simulation(5, 0, TRAJECTORY_RESULT)
    assert (payload["simulation_layer"], payload["speedup"], payload["dt"], payload["steps"], payload["seed"]) == ("gazebo", 4, 2.0, 20, 77)
    assert payload["geofence"] == {"latitude": 58.5, "longitude": 15.5, "radius_meters": 40.0}
    assert payload["monitor"] == "live" and payload["colregs_constraints_content"] == builder.config.domain.colregs_constants
    assert "early_stop" not in payload and payload["include_trajectories"] is True
    validate_payload(ON_GAZEBO, payload)


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
    validate_payload(ON_SITL, ardupilot)


def test_the_submission_has_the_runs_job_type_the_images_and_the_stage_priority():
    builder = _builder(KINEMATIC, SITL, GAZEBO, resources={"priority": 10})
    jobs = []
    for run in range(3):
        step = Step(SIMULATE, run, 0)
        jobs.append(builder.submission(step, builder.simulation(5, run, TRAJECTORY_RESULT), step.idempotency_key("c1", 1), EXPECTED))
    assert [job.job_type for job in jobs] == [JobType.SIMULATION_KINEMATIC, ON_SITL, ON_GAZEBO]
    assert [set(job.requirements.fingerprints) for job in jobs] == [{SCENARIO_EXECUTION_IMAGE}, {SCENARIO_EXECUTION_IMAGE, SITL_IMAGE}, {SCENARIO_EXECUTION_IMAGE, SITL_IMAGE, GAZEBO_IMAGE}]
    assert {job.priority for job in jobs} == {12} and jobs[1].idempotency_key == "campaign:c1:case:1:simulate:1:0"


def test_the_post_hoc_monitor_and_the_calibration_take_the_observed_trajectories():
    builder = _builder(SITL)
    result = {"run_record": {"repeatability_tier": "bounded"}, "trajectories": trajectories_data(), "state_digest": "d" * 64}
    monitoring = builder.post_hoc_monitoring(f"{CLASS_A}#0#run0", result)
    assert monitoring["trajectories"] == trajectories_data()
    validate_payload(JobType.MONITORING_POST_HOC, monitoring)
    calibration = builder.calibration(f"{CLASS_A}#0", {"simulation_layer": "ardupilot_sim"}, [result, result])
    validate_payload(JobType.CALIBRATION_DEVIATION, calibration)


@pytest.mark.parametrize("layer, job_type", [("ardupilot_sim", ON_SITL), ("gazebo", ON_GAZEBO)])
def test_the_payload_model_accepts_what_the_builder_sends_with_every_option(layer, job_type):
    run = {"stack": {"simulation_layer": layer, "speedup": 2, "dt": 1, "steps": 5}, "monitor": "live"}
    validate_payload(job_type, _builder(run).simulation(1, 0, TRAJECTORY_RESULT))


def test_the_payload_of_one_layer_is_refused_as_a_job_of_the_other():
    payload = _builder(GAZEBO).simulation(5, 0, TRAJECTORY_RESULT)
    with pytest.raises(PayloadError, match="simulation_layer"):
        validate_payload(ON_SITL, payload)
