"""Campaign runs on the ArduPilot stacks on Postgres with a fake fleet: the components per run, the images, run records, verdicts, calibration and the stall check."""

import json

import pytest

from scenegems_tool.assurance.campaign import campaign_config_from_dict, validate_campaign_config
from scenegems_tool.assurance.pipeline.pipeline_engine import WorkerNodeAvailability
from scenegems_tool.cluster.fingerprints.comparison import by_repository, repositories
from scenegems_tool.cluster.fingerprints.components import SIMULATION_IMAGE
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.persistence.schema import CampaignActualState, CampaignDesiredState, CampaignEventKind, MonitorImplementation, PipelineStage, VerdictState
from tests.scenegems_tool.assurance.pipeline.checks import assert_consistent
from tests.scenegems_tool.assurance.pipeline.conftest import CLASS_A, config_dict, create_campaign, format2_dict, input_ref
from tests.scenegems_tool.assurance.pipeline.fake_executor import EXPECTED, CaseScript
from tests.scenegems_tool.cluster.payloads import trajectories_data
from tests.scenegems_tool.cluster.stack_images import GAZEBO_IMAGE, SITL_IMAGE

pytestmark = pytest.mark.postgres

SIMULATE, MONITOR, CALIBRATE = PipelineStage.SIMULATE, PipelineStage.MONITOR, PipelineStage.CALIBRATE
SITL_RUN = {"name": "sitl", "stack": {"simulation_layer": "ardupilot_sim"}, "monitor": "post_hoc"}
GAZEBO_RUN = {"name": "world", "stack": {"simulation_layer": "gazebo", "speedup": 2}, "monitor": "live"}
ON_SITL = ["asv_system/replay", "control_layer/ardupilot", "simulation_layer/ardupilot_sim"]
ON_GAZEBO = ["asv_system/replay", "control_layer/ardupilot", "simulation_layer/gazebo"]
NO_ARDUPILOT = ("asv_system/replay", "asv_system/usv_navigation", "control_layer/none", "simulation_layer/kinematic", "scene_generation", "trajectory_generation", "monitoring", "calibration")


def _cases(harness, campaign):
    return harness.stores.cases.list_cases(campaign.campaign_id)


def _jobs(harness, case):
    return {(job.stage, job.run_index, job.repeat_index): harness.job_store.get(job.job_id) for job in harness.stores.pipeline.pipeline_jobs_of_case(case.case_id)}


def test_each_run_is_simulated_by_a_job_needing_its_stacks_components_with_their_images(make_harness):
    harness = make_harness(scripts={(CLASS_A, 0): CaseScript(tier="exact")})
    runs = [{"name": "kinematic", "monitor": "post_hoc"}, SITL_RUN, GAZEBO_RUN]
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=0, runs=runs, resources={"priority": 5}))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 1}
    (case,) = _cases(harness, campaign)
    jobs = _jobs(harness, case)
    kinematic, sitl, world = (jobs[(SIMULATE, run, 0)] for run in range(3))
    assert [job.job_type for job in (kinematic, sitl, world)] == [JobType.SIMULATION] * 3
    assert [job.requirements.components for job in (kinematic, sitl, world)] == [["asv_system/replay", "control_layer/none", "simulation_layer/kinematic"], ON_SITL, ON_GAZEBO]
    assert (kinematic.payload["runner"], sitl.payload["runner"], world.payload["runner"]) == ("kinematic", "ardupilot", "ardupilot")
    assert set(kinematic.requirements.fingerprints) == set(repositories([SIMULATION_IMAGE]))
    assert set(sitl.requirements.fingerprints) == set(repositories([SIMULATION_IMAGE, SITL_IMAGE]))
    assert set(world.requirements.fingerprints) == set(repositories([SIMULATION_IMAGE, SITL_IMAGE, GAZEBO_IMAGE]))
    assert (sitl.payload["simulation_layer"], sitl.payload["include_trajectories"], "monitor" not in sitl.payload) == ("ardupilot_sim", True, True)
    assert (world.payload["monitor"], world.payload["speedup"], world.payload["seed"]) == ("live", 2, harness.stores.results.list_run_records(campaign.campaign_id)[2].seed)
    assert {job.priority for job in (kinematic, sitl, world)} == {7}
    assert [jobs[(MONITOR, run, None)].job_type for run in (0, 1)] == [JobType.MONITORING_POST_HOC] * 2 and (MONITOR, 2, None) not in jobs, "the live run is judged in its job"


def test_run_records_and_verdicts_of_an_ardupilot_run(make_harness):
    harness = make_harness(references=True, scripts={(CLASS_A, 0): CaseScript(passed=False)})
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=0, runs=[SITL_RUN, GAZEBO_RUN], policy={"seed": 7, "keep_frames": True}))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    (case,) = _cases(harness, campaign)
    jobs = _jobs(harness, case)
    sitl_record, world_record = harness.stores.results.list_run_records(campaign.campaign_id)
    for record, run, layer in ((sitl_record, 0, "ardupilot_sim"), (world_record, 1, "gazebo")):
        job = jobs[(SIMULATE, run, 0)]
        assert (record.repeatability_tier, record.job_id, record.worker_node_id, record.dt, record.steps) == ("bounded", job.job_id, "fake-worker-node", 1.0, 10)
        assert record.state_digest == job.result["state_digest"] and len(record.state_digest) == 64
        assert (record.stack["config"]["simulation_layer"], record.stack["config"]["mode"], record.stack["config"]["geofence"]["radius_meters"]) == (layer, "replay", 20.0)
        assert record.stack["run_record"]["speedup"] == record.stack["config"]["speedup"] and record.seed == job.payload["seed"]
        assert record.fingerprints == job.requirements.fingerprints
        assert set(record.artifacts) == {"trajectories", "state_log"}, "the trajectories in, the observed run out; no second state log"
        observed = json.loads(harness.executor.artifacts.documents[record.artifacts["state_log"]])
        assert observed["scene_list"]
    verdicts = {verdict.run_index: verdict for verdict in harness.stores.results.list_verdicts(campaign.campaign_id)}
    assert (verdicts[0].monitor, verdicts[0].state) == (MonitorImplementation.POST_HOC, VerdictState.FAILED)
    assert (verdicts[1].monitor, verdicts[1].state, verdicts[1].early_stop_time_s) == (MonitorImplementation.LIVE, VerdictState.FAILED, None)
    assert verdicts[1].failed_rules == ("OS_0 - TS_1: Rule 14",)
    assert verdicts[0].sensitive and verdicts[1].sensitive, "a bounded stack is sensitive until it is calibrated"
    assert case.progress["runs"]["0"]["tier"] == case.progress["runs"]["1"]["tier"] == "bounded"


def test_a_result_without_a_tier_is_bounded_on_ardupilot_and_unknown_on_the_kinematic_layer(make_harness):
    harness = make_harness(scripts={(CLASS_A, 0): CaseScript(omit_tier=True)})
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=0, runs=[{"monitor": "post_hoc"}, SITL_RUN]))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    kinematic, sitl = harness.stores.results.list_run_records(campaign.campaign_id)
    assert (kinematic.repeatability_tier, sitl.repeatability_tier) == (None, "bounded")


def test_repeats_of_an_ardupilot_run_are_calibrated_against_the_images_it_ran_on(make_harness):
    harness = make_harness()
    run = {**SITL_RUN, "repeats": 3}
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=0, runs=[run]))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert_consistent(harness.stores, campaign.campaign_id)
    (case,) = _cases(harness, campaign)
    jobs = _jobs(harness, case)
    assert [jobs[(SIMULATE, 0, repeat)].requirements.components for repeat in range(3)] == [ON_SITL] * 3
    calibrate = jobs[(CALIBRATE, 0, None)]
    assert len(calibrate.payload["trajectories"]) == 3 and calibrate.payload["stack"]["simulation_layer"] == "ardupilot_sim"
    (calibration,) = harness.stores.calibrations.list_results()
    assert (calibration.exact, calibration.deviation_bound_m, calibration.repeats) == (False, 0.8, 3)
    assert calibration.fingerprints == by_repository({SIMULATION_IMAGE: EXPECTED[SIMULATION_IMAGE], SITL_IMAGE: EXPECTED[SITL_IMAGE]})
    (verdict,) = harness.stores.results.list_verdicts(campaign.campaign_id)
    assert verdict.sensitive is False, "the stack was calibrated on these fingerprints"
    assert {record.repeatability_tier for record in harness.stores.results.list_run_records(campaign.campaign_id)} == {"bounded"}


def test_a_simulation_campaign_over_items_runs_on_ardupilot(make_harness):
    harness = make_harness(references=True)
    data = json.dumps(trajectories_data(), sort_keys=True).encode("utf-8")
    ref = input_ref(data, "trajectories")
    harness.executor.artifacts.documents[ref["sha256"]] = data
    config = format2_dict(["simulation"], runs=[GAZEBO_RUN], input={"items": [{"name": "uploaded", "ref": ref, "source": {"file": "log.json"}}]})
    documents = harness.executor.artifacts.documents
    validated = validate_campaign_config(campaign_config_from_dict(config), artifact_exists=lambda sha: sha in documents, read_artifact=lambda sha: documents[sha])
    campaign = harness.stores.campaigns.create_campaign(validated.config.name, validated.config_json, validated.config_hash, validated.classes, desired_state=CampaignDesiredState.RUNNING)
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    (case,) = _cases(harness, campaign)
    job = _jobs(harness, case)[(SIMULATE, 0, 0)]
    assert job.requirements.components == ON_GAZEBO and job.payload["trajectories"]["sha256"] == ref["sha256"]
    (record,) = harness.stores.results.list_run_records(campaign.campaign_id)
    assert (record.repeatability_tier, record.trajectory_generator, record.artifacts["trajectories"]) == ("bounded", None, ref["sha256"])


# Stalling


def test_a_campaign_with_an_ardupilot_run_stalls_without_a_worker_node_with_its_components(make_harness):
    harness = make_harness(components=NO_ARDUPILOT)
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=0, runs=[SITL_RUN]))
    kinematic = create_campaign(harness.stores, config_dict(classes=(CLASS_A,), quota=1, failure_budget=0, runs=[{"monitor": "post_hoc"}]))
    harness.drive(campaign.campaign_id)
    harness.clock.advance(31)
    harness.settle()
    stalled = harness.campaign(campaign.campaign_id)
    assert stalled.actual_state == CampaignActualState.STALLED
    assert "simulation with asv_system/replay, control_layer/ardupilot, simulation_layer/ardupilot_sim" in stalled.state_reason
    assert harness.campaign(kinematic.campaign_id).actual_state != CampaignActualState.STALLED
    stall = next(event for event in harness.stores.campaigns.list_events(campaign.campaign_id) if event.kind == CampaignEventKind.STALLED)
    assert (stall.detail["job_types"], stall.detail["components"]) == (["simulation"], ON_SITL)
    harness.worker_nodes[:] = [WorkerNodeAvailability(harness.executor.worker_node)]


def test_a_gazebo_run_needs_the_gazebo_image_of_the_pinned_release(make_harness):
    stale_world = {**EXPECTED, GAZEBO_IMAGE: "fp-old-gazebo"}
    harness = make_harness(fingerprints=stale_world)
    sitl = create_campaign(harness.stores, config_dict(quota=1, failure_budget=0, runs=[SITL_RUN]))
    world = create_campaign(harness.stores, config_dict(quota=1, failure_budget=0, runs=[GAZEBO_RUN]))
    assert harness.drive(sitl.campaign_id).actual_state == CampaignActualState.COMPLETED, "SITL does not need Gazebo"
    harness.drive(world.campaign_id)
    harness.clock.advance(31)
    harness.settle()
    stalled = harness.campaign(world.campaign_id)
    assert stalled.actual_state == CampaignActualState.STALLED and "simulation_layer/gazebo" in stalled.state_reason
