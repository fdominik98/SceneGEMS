"""Partial campaigns on Postgres with a fake fleet: each first step and its input, the scene and trajectory monitors, a last trajectory step, item classes, wake, and runs recorded from live sessions."""

import asyncio
import json
from collections import Counter

import pytest

from scenegems_tool.assurance.campaign import ClassCatalog, campaign_config_from_dict, validate_campaign_config
from scenegems_tool.assurance.pipeline.case_machine import ExternalRun
from scenegems_tool.persistence.schema import (
    ArtifactHolderKind,
    CampaignActualState,
    CampaignClassState,
    CampaignDesiredState,
    CampaignEventKind,
    CampaignKind,
    CampaignOrigin,
    CaseState,
    MonitorImplementation,
    PipelineStage,
    RunSource,
    StepKind,
    VerdictState,
)
from tests.scenegems_tool.assurance.pipeline.checks import assert_consistent
from tests.scenegems_tool.assurance.pipeline.conftest import CLASS_A, config_dict, format2_dict, input_ref
from tests.scenegems_tool.assurance.pipeline.fake_executor import CaseScript
from tests.scenegems_tool.cluster.payloads import trajectories_data

pytestmark = pytest.mark.postgres

SCENE, MONITOR_SCENE, TRAJECTORIES, MONITOR_TRAJECTORIES, SIMULATE, MONITOR = (
    PipelineStage.GENERATE_SCENE,
    PipelineStage.MONITOR_SCENE,
    PipelineStage.GENERATE_TRAJECTORIES,
    PipelineStage.MONITOR_TRAJECTORIES,
    PipelineStage.SIMULATE,
    PipelineStage.MONITOR,
)
STRAIGHT = {"generator": "straight", "timespan_s": 10}
MONITORED_STRAIGHT = {**STRAIGHT, "monitor": "post_hoc"}
POST_HOC = {"monitor": "post_hoc"}


def _store(harness, document, kind: str, pointer=None, media_type: str = "application/json") -> dict:
    """Puts a document in the fake fleet's artifact store, as an upload or an earlier campaign's output would be, and returns its input reference."""
    data = document.encode("utf-8") if isinstance(document, str) else json.dumps(document, sort_keys=True).encode("utf-8")
    ref = input_ref(data, kind, pointer, media_type)
    harness.executor.artifacts.documents[ref["sha256"]] = data
    return ref


def _create(harness, config, kind: CampaignKind = CampaignKind.CAMPAIGN, origin=None, desired: CampaignDesiredState = CampaignDesiredState.RUNNING):
    documents = harness.executor.artifacts.documents
    validated = validate_campaign_config(campaign_config_from_dict(config), artifact_exists=lambda sha: sha in documents, read_artifact=lambda sha: documents[sha])
    return harness.stores.campaigns.create_campaign(validated.config.name, validated.config_json, validated.config_hash, validated.classes, desired_state=desired, kind=kind, origin=origin)


def _cases(harness, campaign, **filters):
    return harness.stores.cases.list_cases(campaign.campaign_id, **filters)


def _jobs_of(harness, case):
    return [(pipeline_job, harness.job_store.get(pipeline_job.job_id)) for pipeline_job in harness.stores.pipeline.pipeline_jobs_of_case(case.case_id)]


def _stages(harness, case):
    return Counter(pipeline_job.stage for pipeline_job, _ in _jobs_of(harness, case))


def _references(harness, kind, holder_id):
    return sorted(reference.role for reference in harness.stores.artifacts.references_of(kind, str(holder_id)))


def _verdicts(harness, campaign, step=None):
    return harness.stores.results.list_verdicts(campaign.campaign_id, step=step)


def _scene_item(harness, name: str, source: dict) -> dict:
    scene = trajectories_data()["scene_list"][0]
    return {"name": name, "ref": _store(harness, {"best_scene": scene, "random_seed": len(name)}, "scene"), "source": source}


# Scene generation first


def test_a_scene_campaign_over_catalog_classes_and_a_scenario_with_its_monitor(make_harness):
    harness = make_harness(references=True)
    text = ClassCatalog.default().get(CLASS_A).read_content()
    scenario = _store(harness, text, "functional_scenario", media_type="text/plain; charset=utf-8")
    config = format2_dict(
        ["scene_generation"],
        quota=1,
        failure_budget=0,
        scene_generation=POST_HOC,
        input={"functional_scenarios": [{"name": "mine", "ref": scenario, "quota": 1}]},
        policy={"seed": 7, "keep_frames": True},
        resources={"priority": 10},
    )
    campaign = _create(harness, config)
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 2}
    cases = {case.class_id: case for case in _cases(harness, campaign)}
    assert set(cases) == {CLASS_A, "scenario/mine"}
    assert (cases["scenario/mine"].input_artifact, cases["scenario/mine"].input_source, cases[CLASS_A].input_artifact) == (scenario["sha256"], None, None)
    for case in cases.values():
        assert _stages(harness, case) == {SCENE: 1, MONITOR_SCENE: 1}
        assert case.scene_artifact and case.trajectories_artifact is None and case.stage == PipelineStage.VERDICT
        assert _references(harness, ArtifactHolderKind.CASE, case.case_id) == ["scene", "scene_frames"]
        jobs = {pipeline_job.stage: job for pipeline_job, job in _jobs_of(harness, case)}
        assert (jobs[SCENE].priority, jobs[MONITOR_SCENE].priority) == (10, 11)
        assert jobs[MONITOR_SCENE].payload["scene"]["sha256"] == case.scene_artifact and jobs[MONITOR_SCENE].payload["include_frames"] is True
        assert jobs[MONITOR_SCENE].payload["scenario_id"] == f"{case.class_id}#{case.case_index}#scene"
    scenario_job = next(job for pipeline_job, job in _jobs_of(harness, cases["scenario/mine"]) if pipeline_job.stage == SCENE)
    assert scenario_job.payload["functional_scenario_content"]["sha256"] == scenario["sha256"]  # the node resolves it
    assert harness.executor.payloads[scenario_job.job_id]["functional_scenario_content"] == text
    verdicts = _verdicts(harness, campaign)
    assert {(verdict.step, verdict.run_index, verdict.run_record_id, verdict.state) for verdict in verdicts} == {(StepKind.SCENE, 0, None, VerdictState.PASSED)}
    assert len(verdicts) == 2 and harness.stores.results.list_run_records(campaign.campaign_id) == []


def test_an_invalid_scene_drops_without_its_monitor(make_harness):
    harness = make_harness(scripts={(CLASS_A, 0): CaseScript(scene_valid=False)})
    campaign = _create(harness, format2_dict(["scene_generation"], quota=1, failure_budget=1, scene_generation=POST_HOC))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 1, "dropped": 1}
    dropped, complete = sorted(_cases(harness, campaign), key=lambda case: case.case_index)
    assert dropped.state == CaseState.DROPPED and _stages(harness, dropped) == {SCENE: 1}
    assert complete.state == CaseState.COMPLETE and _stages(harness, complete) == {SCENE: 1, MONITOR_SCENE: 1}


def test_an_unmonitored_scene_campaign_completes_without_verdicts(harness):
    campaign = _create(harness, format2_dict(["scene_generation"], quota=2, failure_budget=0))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 2}
    assert all(_stages(harness, case) == {SCENE: 1} for case in _cases(harness, campaign))
    assert _verdicts(harness, campaign) == []


def test_scene_and_trajectory_steps_with_both_monitors(make_harness):
    harness = make_harness(scripts={(CLASS_A, 0): CaseScript(monitor_passed={MONITOR_SCENE: False})})
    config = format2_dict(["scene_generation", "trajectory_generation"], quota=2, failure_budget=0, scene_generation=POST_HOC, trajectories=MONITORED_STRAIGHT, resources={"priority": 10})
    campaign = _create(harness, config)
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 2}
    for case in _cases(harness, campaign):
        assert _stages(harness, case) == {SCENE: 1, MONITOR_SCENE: 1, TRAJECTORIES: 1, MONITOR_TRAJECTORIES: 1}
        assert case.trajectories_complete is True
        jobs = {pipeline_job.stage: job for pipeline_job, job in _jobs_of(harness, case)}
        assert [jobs[stage].priority for stage in (SCENE, MONITOR_SCENE, TRAJECTORIES, MONITOR_TRAJECTORIES)] == [10, 11, 12, 13]
        assert harness.executor.payloads[jobs[MONITOR_TRAJECTORIES].job_id]["trajectories"] == json.loads(json.dumps(trajectories_data()))  # the planned trajectories, as stored
    states = {(verdict.case_index, verdict.step): verdict.state for verdict in _verdicts(harness, campaign)}
    assert states == {
        (0, StepKind.SCENE): VerdictState.FAILED,
        (0, StepKind.TRAJECTORIES): VerdictState.PASSED,
        (1, StepKind.SCENE): VerdictState.PASSED,
        (1, StepKind.TRAJECTORIES): VerdictState.PASSED,
    }
    assert [verdict.state for verdict in _verdicts(harness, campaign, StepKind.SCENE)] == [VerdictState.FAILED, VerdictState.PASSED]
    assert harness.stores.results.list_run_records(campaign.campaign_id) == []


def test_a_last_trajectory_step_keeps_a_partial_path_and_drops_no_path(make_harness):
    scripts = {(CLASS_A, 0): CaseScript(trajectories="partial"), (CLASS_A, 1): CaseScript(trajectories="none")}
    harness = make_harness(references=True, scripts=scripts)
    config = format2_dict(["scene_generation", "trajectory_generation"], quota=2, failure_budget=1, trajectories=STRAIGHT, policy={"seed": 7, "retention": "verdicts_only"})
    campaign = _create(harness, config)
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 2, "dropped": 1}
    by_index = {case.case_index: case for case in _cases(harness, campaign)}
    partial, none, complete = by_index[0], by_index[1], by_index[2]
    assert (partial.state, partial.trajectories_complete, partial.reason) == (CaseState.COMPLETE, False, None)
    assert (none.state, none.trajectories_complete) == (CaseState.DROPPED, False) and "no trajectories" in none.reason
    assert (complete.state, complete.trajectories_complete) == (CaseState.COMPLETE, True)
    # the trajectories are the campaign's output: verdicts_only keeps them
    assert _references(harness, ArtifactHolderKind.CASE, partial.case_id) == ["scene", "trajectory_data"]


def test_the_full_chain_still_drops_a_partial_path(make_harness):
    harness = make_harness(scripts={(CLASS_A, 0): CaseScript(trajectories="partial")})
    config = format2_dict(["scene_generation", "trajectory_generation", "simulation"], quota=1, failure_budget=1, trajectories=STRAIGHT)
    campaign = _create(harness, config)
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    first = next(case for case in _cases(harness, campaign) if case.case_index == 0)
    assert first.state == CaseState.DROPPED and "only the best partial path" in first.reason


# Later starts: item classes


def test_a_trajectory_campaign_over_scene_items(make_harness):
    harness = make_harness(references=True)
    source = {"campaign_id": "earlier", "case_id": 12, "step": "scene_generation"}
    items = [_scene_item(harness, "case 12 scene", source), _scene_item(harness, "uploaded", {"file": "head_on.json"})]
    campaign = _create(harness, format2_dict(["trajectory_generation"], trajectories=MONITORED_STRAIGHT, input={"items": items}), CampaignKind.WORKBENCH, CampaignOrigin.TRAJECTORY_GENERATION)
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 2}
    cases = {case.class_id: case for case in _cases(harness, campaign)}
    assert set(cases) == {"item/0", "item/1"} and all(case.case_index == 0 for case in cases.values())  # one case per item, no spare
    assert (cases["item/0"].input_artifact, cases["item/0"].input_source) == (items[0]["ref"]["sha256"], source)
    assert cases["item/1"].input_source == {"file": "head_on.json"}
    for class_id, case in cases.items():
        assert _stages(harness, case) == {TRAJECTORIES: 1, MONITOR_TRAJECTORIES: 1} and case.scene_artifact is None
        job = next(job for pipeline_job, job in _jobs_of(harness, case) if pipeline_job.stage == TRAJECTORIES)
        assert job.payload["scenario_content"]["sha256"] == case.input_artifact
        assert _references(harness, ArtifactHolderKind.CASE, case.case_id) == ["trajectory_data"]
    assert {verdict.step for verdict in _verdicts(harness, campaign)} == {StepKind.TRAJECTORIES}


def test_a_simulation_campaign_over_trajectory_items(make_harness):
    harness = make_harness(references=True, scripts={("item/2", 0): CaseScript(fail=SIMULATE)})
    trajectory_data = _store(harness, {"trajectories": trajectories_data(), "algorithm_desc": "straight"}, "trajectory_data")
    items = [
        {"name": "planned", "ref": trajectory_data, "source": {"campaign_id": "earlier", "case_id": 3, "step": "trajectory_generation"}},
        {"name": "uploaded", "ref": _store(harness, trajectories_data(), "trajectories"), "source": {"file": "log.json"}},
        {"name": "failing", "ref": _store(harness, {"trajectories": trajectories_data(), "n": 2}, "trajectory_data", "/trajectories"), "source": {"file": "x.json"}},
    ]
    config = format2_dict(["simulation"], failure_budget=0, runs=[{"monitor": "post_hoc"}], input={"items": items})
    campaign = _create(harness, config)
    finished = harness.drive(campaign.campaign_id)
    assert finished.actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 2, "failed": 1}
    classes = {record.class_id: record.state for record in harness.stores.cases.list_classes(campaign.campaign_id)}
    assert classes == {"item/0": CampaignClassState.COMPLETE, "item/1": CampaignClassState.COMPLETE, "item/2": CampaignClassState.ABANDONED}
    assert len(_cases(harness, campaign)) == 3  # the failed item runs no spare
    cases = {case.class_id: case for case in _cases(harness, campaign)}
    first_job = next(job for pipeline_job, job in _jobs_of(harness, cases["item/0"]) if pipeline_job.stage == SIMULATE)
    assert first_job.payload["trajectories"]["pointer"] == "/trajectories" and first_job.payload["trajectories"]["sha256"] == trajectory_data["sha256"]
    for class_id in ("item/0", "item/1"):
        case = cases[class_id]
        assert case.stage == PipelineStage.VERDICT and _stages(harness, case) == {SIMULATE: 1, MONITOR: 1}
    records = harness.stores.results.list_run_records(campaign.campaign_id)
    assert len(records) == 2
    for record in records:
        case = next(case for case in cases.values() if case.case_id == record.case_id)
        assert (record.source, record.trajectory_generator, record.trajectories_complete) == (RunSource.JOB, None, True)
        assert record.artifacts["trajectories"] == case.input_artifact
    verdicts = _verdicts(harness, campaign)
    assert {(verdict.step, verdict.state) for verdict in verdicts} == {(StepKind.SIMULATION, VerdictState.PASSED)} and len(verdicts) == 2


# Format 1 and the stop conditions


def test_a_format_1_campaign_keeps_its_chain_and_shapes(harness):
    campaign = _create(harness, config_dict(quota=1, failure_budget=0))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    (case,) = _cases(harness, campaign)
    assert _stages(harness, case) == {SCENE: 1, TRAJECTORIES: 1, SIMULATE: 1, MONITOR: 1}
    assert set(case.progress) == {"steps", "runs"} and (case.input_artifact, case.input_source) == (None, None)
    (record,) = harness.stores.results.list_run_records(campaign.campaign_id)
    assert (record.source, record.trajectory_generator.value) == (RunSource.JOB, "straight")
    (verdict,) = _verdicts(harness, campaign)
    assert (verdict.step, verdict.run_record_id) == (StepKind.SIMULATION, record.run_record_id)
    assert harness.campaign(campaign.campaign_id).kind == CampaignKind.CAMPAIGN


def test_failed_scene_verdicts_count_toward_max_failed_verdicts(make_harness):
    harness = make_harness(scripts={(CLASS_A, index): CaseScript(passed=False) for index in range(6)})
    queue = {"queue_depth": {"generate_scene": 1, "monitor": 1}}  # one case at a time, so the stop comes before the quota
    config = format2_dict(["scene_generation"], quota=6, failure_budget=0, scene_generation=POST_HOC, resources=queue, policy={"seed": 7, "stop": {"max_failed_verdicts": 1}})
    campaign = _create(harness, config)
    finished = harness.drive(campaign.campaign_id)
    assert finished.desired_state == CampaignDesiredState.DRAINING and finished.actual_state == CampaignActualState.PAUSED
    events = harness.stores.campaigns.list_events(campaign.campaign_id, limit=None)
    assert any(event.kind == CampaignEventKind.NOTE and "max_failed_verdicts" in event.detail.get("stop_condition", "") for event in events)
    assert {verdict.state for verdict in _verdicts(harness, campaign, StepKind.SCENE)} == {VerdictState.FAILED}


# wake


def test_wake_runs_a_tick_at_once(harness):
    engine = harness.engine
    ticks = []
    tick = engine.tick

    async def counted():
        report = await tick()
        ticks.append(report)
        return report

    engine.tick = counted
    harness.plane.wake_pipeline()  # no engine attached: nothing to wake

    async def until(condition, timeout_s: float = 30.0):
        for _ in range(int(timeout_s / 0.05)):
            if condition():
                return
            await asyncio.sleep(0.05)
        raise AssertionError("the engine did not tick")

    async def scenario():
        runner = asyncio.create_task(engine.run(3600.0))  # without a wake, only the first tick runs within the test
        try:
            await until(lambda: len(ticks) >= 1)
            first = _create(harness, config_dict(quota=1, failure_budget=0))
            harness.plane.pipeline = engine
            harness.plane.wake_pipeline()
            await until(lambda: harness.campaign(first.campaign_id).actual_state == CampaignActualState.RUNNING)
            second = _create(harness, config_dict(quota=1, failure_budget=0))
            await asyncio.to_thread(engine.wake)  # from another thread, as a route in a worker thread would
            await until(lambda: harness.campaign(second.campaign_id).actual_state == CampaignActualState.RUNNING)
            return first, second
        finally:
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    first, second = harness.run(scenario())
    assert len(ticks) >= 2  # the first tick and the first wake; the runner may be cancelled before the last one reports
    assert all(len(_cases(harness, campaign)) >= 1 for campaign in (first, second))


# Runs recorded from live sessions


def _live_entry(harness, monitor: str = "post_hoc"):
    item = {"name": "loaded trajectories", "ref": _store(harness, trajectories_data(), "trajectories"), "source": {"file": "live_session"}}
    config = format2_dict(["simulation"], runs=[{"monitor": monitor}], input={"items": [item]}, policy={"seed": 11, "keep_frames": True})
    return _create(harness, config, CampaignKind.WORKBENCH, CampaignOrigin.LIVE_SESSION), item


def _state_log(harness) -> dict:
    data = json.dumps(trajectories_data(), sort_keys=True).encode("utf-8")
    ref = input_ref(data, "trajectories")
    harness.executor.artifacts.documents[ref["sha256"]] = data
    return ref


def _external_run(harness, **fields) -> ExternalRun:
    return ExternalRun(
        state_log=_state_log(harness),
        stack={"vessels": {"0": {"stack": "mission_planner"}, "1": {"stack": "kinematic"}}},
        environment={"wind_vector": [1.0, 0.0, 0.0]},
        dt=0.5,
        steps=20,
        repeatability_tier="bounded",
        durations_s={"running_s": 10.0},
        **fields,
    )


def test_a_live_session_run_is_recorded_and_judged_post_hoc(make_harness):
    harness = make_harness(references=True)
    campaign, item = _live_entry(harness)
    harness.settle()
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.RUNNING
    assert _cases(harness, campaign) == []  # the engine starts no case of a live session entry
    run = _external_run(harness)
    recorded = harness.run(harness.engine.record_external_run(campaign.campaign_id, run))
    (case,) = _cases(harness, campaign)
    assert (recorded.case_id, case.class_id, case.stage, case.input_artifact, case.input_source) == (case.case_id, "item/0", MONITOR, item["ref"]["sha256"], {"file": "live_session"})
    assert recorded.monitor_key == f"campaign:{campaign.campaign_id}:case:{case.case_id}:monitor:0"
    (record,) = harness.stores.results.list_run_records(campaign.campaign_id)
    assert (record.run_record_id, record.source, record.job_id, record.trajectory_generator) == (recorded.run_record_id, RunSource.LIVE_SESSION, None, None)
    assert (record.dt, record.steps, record.repeatability_tier, record.environment) == (0.5, 20, "bounded", {"wind_vector": [1.0, 0.0, 0.0]})
    assert record.artifacts == {"trajectories": item["ref"]["sha256"], "state_log": run.state_log["sha256"]}
    assert record.stack["config"] == run.stack and record.durations_s == {"running_s": 10.0}
    (monitor_job,) = [job for pipeline_job, job in _jobs_of(harness, case)]
    assert monitor_job.idempotency_key == recorded.monitor_key and monitor_job.payload["trajectories"]["sha256"] == run.state_log["sha256"]
    assert monitor_job.payload["include_frames"] is True
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    (verdict,) = _verdicts(harness, campaign)
    assert (verdict.step, verdict.state, verdict.monitor, verdict.run_record_id) == (StepKind.SIMULATION, VerdictState.PASSED, MonitorImplementation.POST_HOC, record.run_record_id)
    assert _references(harness, ArtifactHolderKind.RUN, record.run_record_id) == ["frames", "state_log"]
    assert any(event.kind == CampaignEventKind.NOTE and "recorded_run" in event.detail for event in harness.stores.campaigns.list_events(campaign.campaign_id, limit=None))
    with pytest.raises(ValueError, match="not running"):
        harness.run(harness.engine.record_external_run(campaign.campaign_id, _external_run(harness)))


def test_an_unmonitored_recorded_run_completes_without_a_job(harness):
    campaign, _ = _live_entry(harness, monitor="empty")
    harness.settle()
    recorded = harness.run(harness.engine.record_external_run(campaign.campaign_id, _external_run(harness, seed=99)))
    assert recorded.monitor_key is None
    harness.settle()
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    (case,) = _cases(harness, campaign)
    assert case.state == CaseState.COMPLETE and _jobs_of(harness, case) == []
    (verdict,) = _verdicts(harness, campaign)
    assert verdict.state == VerdictState.UNMONITORED and harness.stores.results.list_run_records(campaign.campaign_id)[0].seed == 99


def test_a_recorded_run_is_refused_where_it_does_not_fit(harness):
    campaign, _ = _live_entry(harness)
    recorded = harness.run(harness.engine.record_external_run(campaign.campaign_id, _external_run(harness)))  # before the engine started it
    assert recorded.monitor_key is not None and harness.campaign(campaign.campaign_id).pinned_fingerprints  # pinned for the monitor job
    with pytest.raises(ValueError, match="has its case already"):
        harness.run(harness.engine.record_external_run(campaign.campaign_id, _external_run(harness)))
    with pytest.raises(ValueError, match="no open FEC item/5"):
        harness.run(harness.engine.record_external_run(campaign.campaign_id, _external_run(harness), class_id="item/5"))
    inline = ExternalRun(state_log=trajectories_data(), stack={})
    with pytest.raises(ValueError, match="stored as an artifact"):
        harness.run(harness.engine.record_external_run(campaign.campaign_id, inline, class_id="item/0"))
    scenes = _create(harness, format2_dict(["scene_generation"], quota=1))
    with pytest.raises(ValueError, match="simulation step only"):
        harness.run(harness.engine.record_external_run(scenes.campaign_id, _external_run(harness)))
    assert _cases(harness, scenes) == []  # nothing written
