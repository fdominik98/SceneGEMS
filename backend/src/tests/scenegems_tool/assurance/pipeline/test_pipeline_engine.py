"""The pipeline engine on Postgres with a fake fleet: stage graph, verdicts, controls, failures, coverage, retention."""

import random
from collections import Counter

import pytest

from scenegems_tool.assurance.campaign import campaign_config_from_dict, validate_campaign_config
from scenegems_tool.assurance.pipeline.case_machine import CaseMachine
from scenegems_tool.assurance.pipeline.pipeline_engine import WorkerNodeAvailability
from scenegems_tool.cluster.fingerprints.comparison import by_repository
from scenegems_tool.cluster.fingerprints.components import SCENARIO_EXECUTION_IMAGE, SCENE_GENERATION_IMAGE
from scenegems_tool.cluster.protocol.jobs import JobState, JobType
from scenegems_tool.persistence.schema import (
    HELD_UNTIL,
    ArtifactHolderKind,
    CampaignActualState,
    CampaignClassState,
    CampaignDesiredState,
    CampaignEventKind,
    CaseState,
    MonitorImplementation,
    PipelineStage,
    VerdictState,
)
from tests.scenegems_tool.assurance.pipeline.checks import assert_consistent
from tests.scenegems_tool.assurance.pipeline.conftest import CLASS_A, CLASS_B, config_dict, create_campaign
from tests.scenegems_tool.assurance.pipeline.fake_executor import EXPECTED, CaseScript

pytestmark = pytest.mark.postgres

SCENE, TRAJECTORIES, SIMULATE, MONITOR, CALIBRATE = (
    PipelineStage.GENERATE_SCENE,
    PipelineStage.GENERATE_TRAJECTORIES,
    PipelineStage.SIMULATE,
    PipelineStage.MONITOR,
    PipelineStage.CALIBRATE,
)


def _cases(harness, campaign, **filters):
    return harness.stores.cases.list_cases(campaign.campaign_id, **filters)


def _jobs_of(harness, case):
    return [(pipeline_job, harness.job_store.get(pipeline_job.job_id)) for pipeline_job in harness.stores.pipeline.pipeline_jobs_of_case(case.case_id)]


def _event_kinds(harness, campaign):
    return [event.kind for event in harness.stores.campaigns.list_events(campaign.campaign_id, limit=None)]


def _set_desired(harness, campaign, state):
    harness.stores.campaigns.set_desired_state(campaign.campaign_id, state)


def _references(harness, kind, holder_id):
    return sorted(reference.role for reference in harness.stores.artifacts.references_of(kind, str(holder_id)))


def _job_references(harness, campaign):
    """References the artifact store recorded for uploads that the engine has not taken over."""
    return [reference for job_id in harness.stores.pipeline.job_ids_of_campaign(campaign.campaign_id) for reference in harness.stores.artifacts.references_of(ArtifactHolderKind.JOB, job_id)]


# The stage graph


def test_a_post_hoc_campaign_completes_with_its_quota(harness):
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=2))
    finished = harness.drive(campaign.campaign_id)
    assert finished.actual_state == CampaignActualState.COMPLETED and finished.finished_at is not None
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 4}  # no case beyond the quota starts
    assert [(case.class_id, case.case_index) for case in _cases(harness, campaign, states=[CaseState.COMPLETE])] == [(CLASS_A, 0), (CLASS_A, 1), (CLASS_B, 0), (CLASS_B, 1)]
    assert {verdict.state for verdict in harness.stores.results.list_verdicts(campaign.campaign_id)} == {VerdictState.PASSED}
    assert all(record.state == CampaignClassState.COMPLETE for record in harness.stores.cases.list_classes(campaign.campaign_id))
    kinds = _event_kinds(harness, campaign)
    assert kinds[:2] == [CampaignEventKind.CREATED, CampaignEventKind.ENGINE_STARTED] and CampaignEventKind.STARTED in kinds
    assert kinds.count(CampaignEventKind.CLASS_COMPLETE) == 2 and kinds[-1] == CampaignEventKind.COMPLETED


@pytest.mark.parametrize(
    "monitor, generator, references",
    [
        ("post_hoc", "straight", False),
        ("post_hoc", "monitor_driven_rrt", True),
        ("live", "straight", True),
        ("live", "monitor_driven_rrt", False),
        ("empty", "straight", False),
        ("empty", "monitor_driven_rrt", True),
    ],
)
def test_every_monitor_with_either_generator(make_harness, monitor, generator, references):
    harness = make_harness(references=references)
    trajectories = {"generator": "straight", "timespan_s": 10} if generator == "straight" else {"generator": "monitor_driven_rrt", "params": {"maxIterations": 20}}
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=0, runs=[{"monitor": monitor}], trajectories=trajectories))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 1}
    (case,) = _cases(harness, campaign)
    jobs = _jobs_of(harness, case)
    expected_stages = {SCENE: 1, TRAJECTORIES: 1, SIMULATE: 1, **({MONITOR: 1} if monitor == "post_hoc" else {})}
    assert Counter(pipeline_job.stage for pipeline_job, _ in jobs) == expected_stages
    assert all(job.state == JobState.SUCCEEDED for _, job in jobs)
    payloads = {pipeline_job.stage: harness.executor.payloads[job.job_id] for pipeline_job, job in jobs}
    assert payloads[TRAJECTORIES]["params"]["generator"] == generator
    assert (payloads[SIMULATE].get("monitor") == "live") == (monitor == "live")
    (verdict,) = harness.stores.results.list_verdicts(campaign.campaign_id)
    assert verdict.monitor == MonitorImplementation(monitor)
    assert verdict.state == (VerdictState.UNMONITORED if monitor == "empty" else VerdictState.PASSED)
    (record,) = harness.stores.results.list_run_records(campaign.campaign_id)
    assert verdict.run_record_id == record.run_record_id and record.trajectory_generator.value == generator and record.trajectories_complete
    if references:
        assert case.scene_artifact and case.trajectories_artifact
        assert _references(harness, ArtifactHolderKind.CASE, case.case_id) == ["scene", "trajectory_data"]
        assert _references(harness, ArtifactHolderKind.RUN, record.run_record_id) == ["state_log"]
        assert set(record.artifacts) == {"trajectories", "state_log"} and record.artifacts["trajectories"] == case.trajectories_artifact
        sim_job = next(job for pipeline_job, job in jobs if pipeline_job.stage == SIMULATE)
        assert sim_job.payload["trajectories"]["pointer"] == "/trajectories"
        assert _job_references(harness, campaign) == []  # the case and the run hold the uploads now
    else:
        assert (case.scene_artifact, case.trajectories_artifact, record.artifacts) == (None, None, {})
        assert harness.stores.artifacts.references_of(ArtifactHolderKind.CASE, str(case.case_id)) == []


def test_jobs_carry_the_pinned_fingerprints_labels_seeds_and_stage_priorities(make_harness):
    harness = make_harness(labels={"site": "lab"})
    config = config_dict(quota=1, failure_budget=0, resources={"required_labels": {"site": "lab"}, "priority": 10})
    campaign = create_campaign(harness.stores, config)
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert harness.campaign(campaign.campaign_id).pinned_fingerprints == by_repository(EXPECTED)
    (case,) = _cases(harness, campaign)
    jobs = {pipeline_job.stage: job for pipeline_job, job in _jobs_of(harness, case)}
    assert jobs[SCENE].requirements.fingerprints == by_repository({SCENE_GENERATION_IMAGE: EXPECTED[SCENE_GENERATION_IMAGE]})
    assert jobs[SIMULATE].requirements.fingerprints == by_repository({SCENARIO_EXECUTION_IMAGE: EXPECTED[SCENARIO_EXECUTION_IMAGE]})
    assert all(job.requirements.labels == {"site": "lab"} for job in jobs.values())
    assert [jobs[stage].priority for stage in (SCENE, TRAJECTORIES, SIMULATE, MONITOR)] == [10, 11, 12, 13]
    assert jobs[SCENE].payload["seed"] == case.seed == campaign_config_from_dict(config).case_seed(CLASS_A, 0)
    assert jobs[SIMULATE].idempotency_key == f"campaign:{campaign.campaign_id}:case:{case.case_id}:simulate:0:0"
    (record,) = harness.stores.results.list_run_records(campaign.campaign_id)
    assert record.seed == jobs[SIMULATE].payload["seed"]


def test_repeats_get_a_run_record_each_and_one_calibration(harness):
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=0, runs=[{"monitor": "post_hoc", "repeats": 3}]))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert_consistent(harness.stores, campaign.campaign_id)
    (case,) = _cases(harness, campaign)
    jobs = _jobs_of(harness, case)
    assert Counter(pipeline_job.stage for pipeline_job, _ in jobs) == {SCENE: 1, TRAJECTORIES: 1, SIMULATE: 3, MONITOR: 1, CALIBRATE: 1}
    records = harness.stores.results.list_run_records(campaign.campaign_id)
    assert [record.repeat_index for record in records] == [0, 1, 2]
    (verdict,) = harness.stores.results.list_verdicts(campaign.campaign_id)
    assert verdict.run_record_id == records[0].run_record_id
    calibrate_job = next(job for pipeline_job, job in jobs if pipeline_job.stage == CALIBRATE)
    assert len(calibrate_job.payload["trajectories"]) == 3 and calibrate_job.payload["reference"] == f"{CLASS_A}#0"
    (calibration,) = harness.stores.calibrations.list_results()
    assert (calibration.reference_scenario, calibration.repeats, calibration.exact, calibration.campaign_id) == (f"{CLASS_A}#0", 3, True, campaign.campaign_id)
    assert calibration.fingerprints == by_repository({SCENARIO_EXECUTION_IMAGE: EXPECTED[SCENARIO_EXECUTION_IMAGE]})
    assert case.progress["runs"]["0"]["calibrated"] is True


def test_a_bounded_stack_is_sensitive_until_it_is_calibrated(make_harness):
    scripts = {(CLASS_A, 0): CaseScript(tier="bounded"), (CLASS_B, 0): CaseScript(tier="exact")}
    harness = make_harness(scripts=scripts)
    runs = [{"monitor": "post_hoc"}, {"monitor": "empty", "stack": {"mode": "usv_navigation"}, "repeats": 2}]
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=1, failure_budget=0, runs=runs))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    sensitive = {(verdict.class_id, verdict.run_index): verdict.sensitive for verdict in harness.stores.results.list_verdicts(campaign.campaign_id)}
    # run 0 (replay) has no calibration; run 1 (USV Navigation) calibrated itself with its repeats; exact stacks never are sensitive
    assert sensitive == {(CLASS_A, 0): True, (CLASS_A, 1): False, (CLASS_B, 0): False, (CLASS_B, 1): False}


def test_verdicts_and_run_records_carry_what_the_runs_reported(make_harness):
    scripts = {(CLASS_A, 0): CaseScript(passed=False), (CLASS_B, 0): CaseScript(passed=False, stopped_early_at=6)}
    harness = make_harness(scripts=scripts)
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A,), quota=1, failure_budget=0))
    live = create_campaign(harness.stores, config_dict(classes=(CLASS_B,), quota=1, failure_budget=0, runs=[{"monitor": "live", "early_stop": True}]))
    harness.drive(campaign.campaign_id)
    harness.drive(live.campaign_id)
    (verdict,) = harness.stores.results.list_verdicts(campaign.campaign_id)
    assert (verdict.state, verdict.failed_rules, verdict.first_failure_time_s, verdict.early_stop_time_s) == (VerdictState.FAILED, ("OS_0 - TS_1: Rule 14",), 4.0, None)
    assert verdict.rule_outcomes == {"OS_0 - TS_1": {"Rule 14": {"failed": 4}}}
    (live_verdict,) = harness.stores.results.list_verdicts(live.campaign_id)
    assert (live_verdict.monitor, live_verdict.state, live_verdict.early_stop_time_s) == (MonitorImplementation.LIVE, VerdictState.FAILED, 6.0)
    (case,) = _cases(harness, campaign)
    (record,) = harness.stores.results.list_run_records(campaign.campaign_id)
    sim_job = next(job for pipeline_job, job in _jobs_of(harness, case) if pipeline_job.stage == SIMULATE)
    assert (record.job_id, record.worker_node_id, record.steps, record.dt) == (sim_job.job_id, "fake-worker-node", 10, 1.0)
    assert record.state_digest == sim_job.result["state_digest"] and record.repeatability_tier == "exact"
    assert record.fingerprints == by_repository({SCENARIO_EXECUTION_IMAGE: EXPECTED[SCENARIO_EXECUTION_IMAGE]})
    assert set(record.durations_s) == {"queued_s", "running_s", "total_s"}
    assert record.stack["config"]["mode"] == "replay" and record.stack["run_record"]["run_seed"] == record.seed
    assert record.environment == {"wind_vector": [0.0, 0.0, 0.0]}


# Backpressure


def test_new_cases_wait_while_a_stage_is_at_its_cap(harness):
    caps = {"generate_scene": 2, "generate_trajectories": 1}
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=3, failure_budget=0, resources={"queue_depth": caps}))
    harness.settle()
    assert len(_cases(harness, campaign)) == 2
    assert harness.stores.pipeline.queued_jobs_by_stage(campaign.campaign_id) == {SCENE: 2}
    harness.executor.run(job_types=[JobType.SCENE_GENERATION])
    harness.settle()
    # two trajectory jobs wait against a cap of one, so no case starts though the scene queue is empty
    assert harness.stores.pipeline.queued_jobs_by_stage(campaign.campaign_id) == {TRAJECTORIES: 2}
    assert len(_cases(harness, campaign)) == 2
    for _ in range(200):
        harness.settle()
        queued = harness.stores.pipeline.queued_jobs_by_stage(campaign.campaign_id)
        assert queued.get(SCENE, 0) <= 2
        if harness.campaign(campaign.campaign_id).actual_state.is_final:
            break
        harness.executor.run(limit=1)
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 6}


# Controls


def test_pause_holds_every_job_and_resume_releases_them(harness):
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=2, failure_budget=0))
    harness.settle()
    running = harness.executor.claim_all(limit=2)  # two scene jobs run while the campaign pauses
    _set_desired(harness, campaign, CampaignDesiredState.PAUSED)
    harness.settle()
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.PAUSED
    unfinished = harness.stores.pipeline.job_ids_of_campaign(campaign.campaign_id, [JobState.QUEUED, JobState.LEASED, JobState.RUNNING])
    assert len(unfinished) == 4 and all(harness.job_store.get(job_id).available_at == HELD_UNTIL for job_id in unfinished)
    assert harness.executor.run() == 0
    for lease in running:
        harness.executor.report(lease)
    harness.settle()
    trajectory_jobs = [job for case in _cases(harness, campaign) for pipeline_job, job in _jobs_of(harness, case) if pipeline_job.stage == TRAJECTORIES]
    assert len(trajectory_jobs) == 2 and all(job.available_at == HELD_UNTIL for job in trajectory_jobs)
    assert harness.executor.run() == 0 and len(_cases(harness, campaign)) == 4
    _set_desired(harness, campaign, CampaignDesiredState.RUNNING)
    harness.settle()
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.RUNNING
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 4}
    kinds = _event_kinds(harness, campaign)
    assert kinds.index(CampaignEventKind.PAUSED) < kinds.index(CampaignEventKind.RESUMED) < kinds.index(CampaignEventKind.COMPLETED)


def test_drain_finishes_started_cases_and_pauses_until_resumed(harness):
    campaign = create_campaign(harness.stores, config_dict(quota=3, failure_budget=0, resources={"queue_depth": {"generate_scene": 2}}))
    harness.settle()
    assert len(_cases(harness, campaign)) == 2
    _set_desired(harness, campaign, CampaignDesiredState.DRAINING)
    paused = harness.drive(campaign.campaign_id)
    assert (paused.actual_state, paused.state_reason) == (CampaignActualState.PAUSED, "drained")
    assert len(_cases(harness, campaign)) == 2 and assert_consistent(harness.stores, campaign.campaign_id, finished=False) == {"complete": 2}
    harness.settle()
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.PAUSED
    _set_desired(harness, campaign, CampaignDesiredState.RUNNING)
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 3}
    assert CampaignEventKind.DRAINING in _event_kinds(harness, campaign)


def test_stop_cancels_active_cases_and_unfinished_jobs(harness):
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=3, failure_budget=1))
    harness.settle()
    harness.executor.run()
    harness.settle()
    leased = harness.executor.claim_all(limit=2)
    _set_desired(harness, campaign, CampaignDesiredState.STOPPED)
    stopped = harness.drive(campaign.campaign_id)
    assert stopped.actual_state == CampaignActualState.STOPPED
    states = assert_consistent(harness.stores, campaign.campaign_id)
    assert states == {"cancelled": 6}  # the quota of each FEC was running, nothing beyond it
    assert all(case.reason == "the campaign was stopped" for case in _cases(harness, campaign))
    assert {harness.job_store.get(lease.job.job_id).state for lease in leased} == {JobState.CANCELLED}
    assert all(record.state == CampaignClassState.ABANDONED for record in harness.stores.cases.list_classes(campaign.campaign_id))
    assert _event_kinds(harness, campaign)[-1] == CampaignEventKind.STOPPED


# Failures


def test_a_retryable_failure_comes_back_after_its_backoff(make_harness):
    harness = make_harness(scripts={(CLASS_A, 0): CaseScript(retryable_failures={SIMULATE: 2})})
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=0))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.RUNNING  # the simulation waits out its backoff
    (case,) = _cases(harness, campaign)
    sim_job = next(job for pipeline_job, job in _jobs_of(harness, case) if pipeline_job.stage == SIMULATE)
    assert (sim_job.state, sim_job.failed_attempts) == (JobState.QUEUED, 1)
    assert (sim_job.available_at - harness.clock.now).total_seconds() == 5.0
    harness.clock.advance(5)
    assert harness.executor.run() == 1
    assert harness.executor.run() == 0  # the second backoff is 10 s
    harness.clock.advance(10)
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 1}
    assert harness.job_store.get(sim_job.job_id).attempt == 3


def test_a_failed_job_quarantines_its_case_and_a_replacement_runs(make_harness):
    harness = make_harness(scripts={(CLASS_A, 0): CaseScript(fail=SIMULATE)})
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=1))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"failed": 1, "complete": 1}
    failed, complete = _cases(harness, campaign)
    assert failed.state == CaseState.FAILED and "simulate:0:0 job" in failed.reason and "scripted failure of simulate" in failed.reason
    assert complete.case_index == 1
    (record,) = harness.stores.cases.list_classes(campaign.campaign_id)
    assert (record.state, record.dropped_count, record.complete_count) == (CampaignClassState.COMPLETE, 1, 1)


def test_dropped_cases_are_replaced_with_their_reasons(make_harness):
    scripts = {(CLASS_A, 0): CaseScript(scene_valid=False), (CLASS_A, 1): CaseScript(trajectories="partial"), (CLASS_A, 2): CaseScript(trajectories="none")}
    harness = make_harness(scripts=scripts)
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=3))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"dropped": 3, "complete": 1}
    invalid, partial, none, complete = _cases(harness, campaign)
    assert invalid.reason == "the scene generation found no valid scene"
    assert "no complete trajectories" in partial.reason and partial.trajectories_complete is False
    assert none.reason == "the trajectory generator found no trajectories: no path" and none.trajectories_complete is False
    assert complete.state == CaseState.COMPLETE and complete.trajectories_complete is True


def test_a_class_is_abandoned_once_its_budget_is_used_up(make_harness):
    harness = make_harness(scripts={(CLASS_A, 0): CaseScript(scene_valid=False), (CLASS_A, 1): CaseScript(fail=TRAJECTORIES)})
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=1, failure_budget=1))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert_consistent(harness.stores, campaign.campaign_id)
    states = {record.class_id: (record.state, record.dropped_count) for record in harness.stores.cases.list_classes(campaign.campaign_id)}
    assert states == {CLASS_A: (CampaignClassState.ABANDONED, 2), CLASS_B: (CampaignClassState.COMPLETE, 0)}
    abandoned = [event for event in harness.stores.campaigns.list_events(campaign.campaign_id) if event.kind == CampaignEventKind.CLASS_ABANDONED]
    assert [event.class_id for event in abandoned] == [CLASS_A] and "exceed the failure budget of 1" in abandoned[0].detail["reason"]


def test_an_unlimited_budget_replaces_every_drop_until_the_quota_is_complete(make_harness):
    harness = make_harness(scripts={(CLASS_A, index): CaseScript(scene_valid=False) for index in range(6)})
    campaign = create_campaign(harness.stores, config_dict(quota=2, failure_budget="unlimited"))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert_consistent(harness.stores, campaign.campaign_id)
    (record,) = harness.stores.cases.list_classes(campaign.campaign_id)
    assert (record.state, record.dropped_count, record.complete_count, record.failure_budget) == (CampaignClassState.COMPLETE, 6, 2, None)
    assert [case.case_index for case in _cases(harness, campaign) if case.state == CaseState.COMPLETE] == [6, 7]


def test_a_stop_condition_ends_a_class_with_an_unlimited_budget_that_never_completes(make_harness):
    harness = make_harness(scripts={(CLASS_A, index): CaseScript(scene_valid=False) for index in range(40)})
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget="unlimited", policy={"seed": 7, "stop": {"max_cases": 5}}))
    paused = harness.drive(campaign.campaign_id)
    assert (paused.desired_state, paused.actual_state, paused.state_reason) == (CampaignDesiredState.DRAINING, CampaignActualState.PAUSED, "drained")
    assert len(_cases(harness, campaign)) == 5
    (record,) = harness.stores.cases.list_classes(campaign.campaign_id)
    assert (record.state, record.dropped_count) == (CampaignClassState.OPEN, 5)


def test_a_job_cancelled_by_someone_else_fails_its_case(harness):
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=1))
    harness.settle()
    first = _cases(harness, campaign)[0]
    ((_, scene_job),) = _jobs_of(harness, first)
    harness.run(harness.plane.cancel(scene_job.job_id, "operator"))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    failed = harness.stores.cases.get_case(first.case_id)
    assert failed.state == CaseState.FAILED and "was cancelled: operator" in failed.reason


def test_an_event_the_engine_cannot_process_quarantines_its_case(harness, monkeypatch):
    original = CaseMachine._trajectories_generated

    def broken(self, context, case, *arguments):
        if case.case_index == 0:
            raise RuntimeError("broken result handling")
        return original(self, context, case, *arguments)

    monkeypatch.setattr(CaseMachine, "_trajectories_generated", broken)
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=1))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    first = _cases(harness, campaign)[0]
    assert first.state == CaseState.FAILED and "could not process event" in first.reason and "broken result handling" in first.reason
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"failed": 1, "complete": 1}


def test_a_case_whose_verdicts_cannot_be_written_is_quarantined(harness, monkeypatch):
    original = CaseMachine.complete

    def broken(self, context, case):
        if case.case_index == 0:
            raise ValueError("no verdict store")
        return original(self, context, case)

    monkeypatch.setattr(CaseMachine, "complete", broken)
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=1))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    first, second = _cases(harness, campaign)
    assert first.state == CaseState.FAILED and "its monitor result summaries could not be written: ValueError: no verdict store" in first.reason
    assert second.state == CaseState.COMPLETE
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"failed": 1, "complete": 1}


# Coverage


def test_the_selected_cases_do_not_depend_on_the_completion_order(make_harness):
    scripts = {(CLASS_A, 1): CaseScript(scene_valid=False), (CLASS_A, 3): CaseScript(trajectories="partial"), (CLASS_B, 0): CaseScript(fail=MONITOR)}
    harness = make_harness(scripts=scripts)
    selections = set()
    for seed in range(4):
        campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=3, failure_budget=3))
        assert harness.drive(campaign.campaign_id, rng=random.Random(seed), per_round=1 + seed % 3, rounds=400).actual_state == CampaignActualState.COMPLETED
        assert_consistent(harness.stores, campaign.campaign_id)
        selections.add(tuple((case.class_id, case.case_index) for case in _cases(harness, campaign, states=[CaseState.COMPLETE])))
    assert selections == {((CLASS_A, 0), (CLASS_A, 2), (CLASS_A, 4), (CLASS_B, 1), (CLASS_B, 2), (CLASS_B, 3))}


def test_the_campaign_completes_when_every_class_is_closed(make_harness):
    harness = make_harness(scripts={(CLASS_B, 0): CaseScript(scene_valid=False)})
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=1, failure_budget=0))
    finished = harness.drive(campaign.campaign_id)
    assert finished.actual_state == CampaignActualState.COMPLETED
    assert harness.stores.campaigns.list_events(campaign.campaign_id, kinds=[CampaignEventKind.COMPLETED])[0].detail["classes"] == {"open": 0, "complete": 1, "abandoned": 1}


# Retention


@pytest.mark.parametrize("policy", ["all", "failures", "verdicts_only"])
def test_retention_keeps_what_its_policy_says(make_harness, policy):
    harness = make_harness(references=True, scripts={(CLASS_A, 1): CaseScript(passed=False)})
    campaign = create_campaign(harness.stores, config_dict(quota=2, failure_budget=0, policy={"retention": policy, "keep_frames": True}))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    passed, failed = _cases(harness, campaign)
    records = {record.case_id: record for record in harness.stores.results.list_run_records(campaign.campaign_id)}
    kept = {
        name: (_references(harness, ArtifactHolderKind.CASE, case.case_id), _references(harness, ArtifactHolderKind.RUN, records[case.case_id].run_record_id))
        for name, case in (("passed", passed), ("failed", failed))
    }
    everything = (["scene", "trajectory_data"], ["frames", "state_log"])
    expected = {
        "all": {"passed": everything, "failed": everything},
        "failures": {"passed": (["scene"], []), "failed": everything},
        "verdicts_only": {"passed": (["scene"], []), "failed": (["scene"], [])},
    }[policy]
    assert kept == expected
    assert _job_references(harness, campaign) == []
    assert all(set(record.artifacts) == {"trajectories", "state_log"} for record in records.values())  # the records keep their hashes


def test_a_cut_case_keeps_no_trajectories_under_the_failures_policy(make_harness):
    harness = make_harness(references=True, scripts={(CLASS_A, 0): CaseScript(scene_valid=False)})
    campaign = create_campaign(harness.stores, config_dict(quota=2, failure_budget=0, policy={"retention": "failures"}))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    dropped, cut = _cases(harness, campaign)
    assert (dropped.state, cut.state, cut.reason) == (CaseState.DROPPED, CaseState.CANCELLED, "its FEC was abandoned")
    assert _references(harness, ArtifactHolderKind.CASE, cut.case_id) == ["scene"]
    assert _job_references(harness, campaign) == []  # results that arrived after the cut are not kept either


# Starting and stalling


def test_a_campaign_waits_until_it_is_started_and_pins_the_expected_fingerprints(harness, monkeypatch):
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=0), desired=CampaignDesiredState.PAUSED)
    harness.settle()
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.CREATED and _cases(harness, campaign) == []
    _set_desired(harness, campaign, CampaignDesiredState.RUNNING)
    monkeypatch.setattr(harness.engine, "_expected", lambda: None)
    harness.settle()
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.CREATED  # the expected fingerprints are not loaded yet
    monkeypatch.setattr(harness.engine, "_expected", harness.plane.expected.current)
    harness.settle()
    started = harness.campaign(campaign.campaign_id)
    assert (started.actual_state, started.pinned_fingerprints) == (CampaignActualState.RUNNING, by_repository(EXPECTED)) and started.started_at is not None


def test_a_campaign_keeps_the_fingerprints_it_was_created_with(harness):
    validated_pins = {image: "fp-old" for image in EXPECTED}
    validated = validate_campaign_config(campaign_config_from_dict(config_dict(quota=1, failure_budget=0)))
    campaign = harness.stores.campaigns.create_campaign("old release", validated.config_json, validated.config_hash, validated.classes, validated_pins, CampaignDesiredState.RUNNING)
    harness.settle()
    assert harness.campaign(campaign.campaign_id).pinned_fingerprints == validated_pins
    (case,) = _cases(harness, campaign)
    ((_, scene_job),) = _jobs_of(harness, case)
    assert scene_job.requirements.fingerprints == by_repository({SCENE_GENERATION_IMAGE: "fp-old"}), "a pin by full name holds by repository"
    assert harness.executor.run() == 0  # the worker node runs the current release


def test_a_campaign_without_a_worker_node_for_a_needed_job_type_is_stalled(harness):
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=0))
    worker_node = harness.worker_nodes[0]
    harness.worker_nodes[:] = []
    harness.settle()
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.RUNNING
    harness.clock.advance(31)
    harness.settle()
    stalled = harness.campaign(campaign.campaign_id)
    assert stalled.actual_state == CampaignActualState.STALLED and "scene_generation" in stalled.state_reason
    other_release = WorkerNodeAvailability(record=type(worker_node.record)(**{**worker_node.record.__dict__, "fingerprints": {image: "fp-other" for image in EXPECTED}}))
    harness.worker_nodes[:] = [other_release]
    harness.settle()
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.STALLED
    harness.worker_nodes[:] = [worker_node]
    harness.settle()
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.RUNNING
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    kinds = _event_kinds(harness, campaign)
    assert kinds.index(CampaignEventKind.STALLED) < kinds.index(CampaignEventKind.RESUMED)


def test_a_campaign_runs_only_on_its_selected_worker_nodes(harness):
    elsewhere = create_campaign(harness.stores, config_dict(quota=1, failure_budget=0, resources={"worker_nodes": ["another-worker-node"]}))
    harness.settle()
    assert harness.executor.run() == 0  # the only worker node is not selected
    harness.clock.advance(31)
    harness.settle()
    stalled = harness.campaign(elsewhere.campaign_id)
    assert stalled.actual_state == CampaignActualState.STALLED and stalled.state_reason.endswith("among its selected worker nodes")
    worker_nodes = [harness.executor.worker_node_id, "another-worker-node"]
    selected = create_campaign(harness.stores, config_dict(quota=1, failure_budget=0, resources={"worker_nodes": worker_nodes}))
    assert harness.drive(selected.campaign_id).actual_state == CampaignActualState.COMPLETED
    (case,) = _cases(harness, selected)
    assert [job.allowed_worker_nodes for _, job in _jobs_of(harness, case)] and all(job.allowed_worker_nodes == tuple(worker_nodes) for _, job in _jobs_of(harness, case))
    assert harness.campaign(elsewhere.campaign_id).actual_state == CampaignActualState.STALLED


def test_worker_node_availability_honours_the_selected_worker_nodes(harness):
    (worker_node,) = harness.worker_nodes
    scene = ("scene_generation",)
    assert worker_node.runs(JobType.SCENE_GENERATION, scene, {}, {}) and worker_node.runs(JobType.SCENE_GENERATION, scene, {}, {}, {harness.executor.worker_node_id})
    assert not worker_node.runs(JobType.SCENE_GENERATION, scene, {}, {}, {"another-worker-node"})


def test_worker_node_availability_needs_the_components_up_to_date(harness):
    from dataclasses import replace

    (worker_node,) = harness.worker_nodes
    gazebo = ("asv_system/replay", "control_layer/ardupilot", "simulation_layer/gazebo")
    assert worker_node.runs(JobType.SIMULATION, gazebo, {}, {})
    assert not replace(worker_node, stale_components=frozenset({"simulation_layer/gazebo"})).runs(JobType.SIMULATION, gazebo, {}, {})
    assert replace(worker_node, stale_components=frozenset({"simulation_layer/gazebo"})).runs(JobType.SCENE_GENERATION, ("scene_generation",), {}, {}), "the other components still work"
    assert not replace(worker_node, record=replace(worker_node.record, components=("scene_generation",))).runs(JobType.SIMULATION, gazebo, {}, {})


def test_a_stop_condition_drains_the_campaign(harness):
    campaign = create_campaign(harness.stores, config_dict(quota=3, failure_budget=0, policy={"stop": {"max_cases": 2}}))
    paused = harness.drive(campaign.campaign_id)
    assert (paused.desired_state, paused.actual_state, paused.state_reason) == (CampaignDesiredState.DRAINING, CampaignActualState.PAUSED, "drained")
    assert len(_cases(harness, campaign)) == 2
    (note,) = harness.stores.campaigns.list_events(campaign.campaign_id, kinds=[CampaignEventKind.NOTE])
    assert "max_cases" in note.detail["stop_condition"]


def test_the_engine_tells_which_campaigns_each_committed_transaction_changed(harness):
    heard = []
    harness.engine.on_change = heard.append
    running = create_campaign(harness.stores, config_dict(classes=(CLASS_A,), quota=1))
    waiting = create_campaign(harness.stores, config_dict(classes=(CLASS_B,), quota=1), CampaignDesiredState.PAUSED)
    harness.tick()
    # The start appends engine_started to both; the tick then starts the running one and its first case
    assert heard == [{running.campaign_id, waiting.campaign_id}, {running.campaign_id}]

    heard.clear()
    harness.settle()
    assert heard == []  # nothing happened, nothing to tell
    harness.executor.run()
    harness.tick()
    assert heard and all(changed == {running.campaign_id} for changed in heard)


def test_a_failing_change_listener_does_not_stop_the_engine(harness):
    def broken(_campaign_ids):
        raise RuntimeError("the listener is broken")

    harness.engine.on_change = broken
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A,), quota=1))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
