from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

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
    StepKind,
    VerdictState,
)
from scenegems_tool.persistence.stores import CampaignStateConflict, CampaignTotals, ClassSpec, NewCase, NewRunRecord, NewVerdict, UnknownCampaign
from tests.scenegems_tool.persistence.stores.builders import CONFIG_HASH, START, make_class_spec, sha256_of
from tests.scenegems_tool.persistence.stores.conftest import CLASS_A, CLASS_B

pytestmark = pytest.mark.postgres


def test_create_a_campaign_with_its_config_and_classes(stores, campaign):
    assert (campaign.name, campaign.desired_state, campaign.actual_state, campaign.config_version) == ("lab campaign", CampaignDesiredState.PAUSED, CampaignActualState.CREATED, 1)
    assert campaign.pinned_fingerprints == {"scenegems-scenario-execution": "fp-execution"}
    assert (campaign.created_at, campaign.started_at, campaign.finished_at) == (START, None, None)
    assert stores.campaigns.get_campaign(campaign.campaign_id) == campaign
    config = stores.campaigns.config_version(campaign.campaign_id)
    assert (config.version, config.config, config.config_hash) == (1, {"name": "lab campaign"}, CONFIG_HASH)
    assert stores.campaigns.config_versions(campaign.campaign_id) == [config]
    classes = stores.cases.list_classes(campaign.campaign_id)
    assert [(c.class_id, c.quota, c.failure_budget, c.vessel_count, c.obstacle_count, c.state) for c in classes] == [
        (CLASS_A, 3, 2, 2, 0, CampaignClassState.OPEN),
        (CLASS_B, 2, 1, 3, 1, CampaignClassState.OPEN),
    ]
    assert all((c.complete_count, c.dropped_count, c.in_flight_count) == (0, 0, 0) for c in classes)
    (created,) = stores.campaigns.list_events(campaign.campaign_id)
    assert created.kind == CampaignEventKind.CREATED and created.detail == {"config_hash": CONFIG_HASH, "classes": 2, "desired_state": "paused", "kind": "campaign"}


def test_a_class_with_an_unlimited_failure_budget(stores):
    created = stores.campaigns.create_campaign("unlimited", {}, CONFIG_HASH, [make_class_spec(CLASS_A, quota=2, failure_budget=None)])
    (record,) = stores.cases.list_classes(created.campaign_id)
    assert (record.quota, record.failure_budget, record.failure_budget_left) == (2, None, None)
    (coverage,) = stores.results.coverage(created.campaign_id)
    assert coverage.failure_budget is None


def test_creation_is_one_transaction(stores):
    # The second class breaks a constraint, so neither the campaign nor its first class remain
    broken = ClassSpec(class_id=CLASS_B, content_hash=sha256_of(CLASS_B), vessel_count=2, obstacle_count=0, quota=0, failure_budget=0)
    with pytest.raises(IntegrityError):
        stores.campaigns.create_campaign("broken", {}, CONFIG_HASH, [make_class_spec(CLASS_A), broken])
    assert stores.campaigns.list_campaigns() == []


@pytest.mark.parametrize(
    "classes, hash_",
    [
        ([], CONFIG_HASH),
        ([make_class_spec(CLASS_A), make_class_spec(CLASS_A)], CONFIG_HASH),
        ([make_class_spec(CLASS_A)], "ABC"),
        ([ClassSpec(CLASS_A, "f" * 63, 2, 0, 1, 0)], CONFIG_HASH),
    ],
)
def test_creation_checks_its_input(stores, classes, hash_):
    with pytest.raises(ValueError):
        stores.campaigns.create_campaign("bad", {}, hash_, classes)


def test_list_campaigns_newest_first(stores, clock):
    first = stores.campaigns.create_campaign("first", {}, CONFIG_HASH, [make_class_spec()])
    clock.advance(1)
    second = stores.campaigns.create_campaign("second", {}, CONFIG_HASH, [make_class_spec()])
    assert [c.campaign_id for c in stores.campaigns.list_campaigns()] == [second.campaign_id, first.campaign_id]
    assert [c.campaign_id for c in stores.campaigns.list_campaigns(limit=1, offset=1)] == [first.campaign_id]
    stores.campaigns.set_actual_state(first.campaign_id, CampaignActualState.RUNNING)
    assert [c.name for c in stores.campaigns.list_campaigns([CampaignActualState.RUNNING])] == ["first"]
    assert [c.name for c in stores.campaigns.unfinished_campaigns()] == ["first", "second"]


def test_count_campaigns_takes_the_filter_of_list_campaigns(stores, clock):
    first = stores.campaigns.create_campaign("first", {}, CONFIG_HASH, [make_class_spec()])
    clock.advance(1)
    stores.campaigns.create_campaign("second", {}, CONFIG_HASH, [make_class_spec()])
    stores.campaigns.set_actual_state(first.campaign_id, CampaignActualState.RUNNING)
    assert stores.campaigns.count_campaigns() == 2
    assert stores.campaigns.count_campaigns([CampaignActualState.RUNNING]) == 1
    assert stores.campaigns.count_campaigns([CampaignActualState.RUNNING, CampaignActualState.CREATED]) == 2
    assert stores.campaigns.count_campaigns([CampaignActualState.COMPLETED]) == 0
    assert len(stores.campaigns.list_campaigns(limit=1)) == 1 and stores.campaigns.count_campaigns() == 2


def test_desired_state_changes_are_recorded(stores, campaign, clock):
    clock.advance(5)
    running = stores.campaigns.set_desired_state(campaign.campaign_id, CampaignDesiredState.RUNNING)
    assert running.desired_state == CampaignDesiredState.RUNNING and running.updated_at == clock.now
    # setting it again records nothing
    stores.campaigns.set_desired_state(campaign.campaign_id, CampaignDesiredState.RUNNING)
    events = stores.campaigns.list_events(campaign.campaign_id, kinds=[CampaignEventKind.DESIRED_STATE_CHANGED])
    assert [event.detail for event in events] == [{"from": "paused", "to": "running"}]


def test_desired_state_with_an_expectation(stores, campaign):
    with pytest.raises(CampaignStateConflict):
        stores.campaigns.set_desired_state(campaign.campaign_id, CampaignDesiredState.RUNNING, expected=CampaignDesiredState.DRAINING)
    assert stores.campaigns.get_campaign(campaign.campaign_id).desired_state == CampaignDesiredState.PAUSED


def test_a_stop_is_final(stores, campaign):
    stores.campaigns.set_desired_state(campaign.campaign_id, CampaignDesiredState.STOPPED)
    with pytest.raises(CampaignStateConflict):
        stores.campaigns.set_desired_state(campaign.campaign_id, CampaignDesiredState.RUNNING)
    stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.STOPPED)
    with pytest.raises(CampaignStateConflict):
        stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.RUNNING)


def test_actual_state_sets_start_and_finish_times(stores, campaign, clock):
    clock.advance(10)
    running = stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.RUNNING)
    assert running.started_at == clock.now
    clock.advance(10)
    stalled = stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.STALLED, reason="no node runs release 6de1e06")
    assert (stalled.state_reason, stalled.started_at) == ("no node runs release 6de1e06", running.started_at)
    clock.advance(10)
    resumed = stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.RUNNING, expected=CampaignActualState.STALLED)
    assert resumed.state_reason is None and resumed.started_at == running.started_at
    with pytest.raises(CampaignStateConflict):
        stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.PAUSED, expected=CampaignActualState.STALLED)
    done = stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.COMPLETED)
    assert done.finished_at == clock.now


def test_events_in_order_with_paging(stores, campaign):
    stores.campaigns.append_event(campaign.campaign_id, CampaignEventKind.STARTED)
    stores.campaigns.append_event(campaign.campaign_id, CampaignEventKind.CLASS_COMPLETE, {"verdicts": 3}, class_id=CLASS_A)
    events = stores.campaigns.list_events(campaign.campaign_id)
    assert [event.kind for event in events] == [CampaignEventKind.CREATED, CampaignEventKind.STARTED, CampaignEventKind.CLASS_COMPLETE]
    assert (events[2].class_id, events[2].detail) == (CLASS_A, {"verdicts": 3})
    assert stores.campaigns.list_events(campaign.campaign_id, after_event_id=events[0].event_id, limit=1) == [events[1]]


def test_count_events_takes_the_filters_of_list_events(stores, campaign):
    stores.campaigns.append_event(campaign.campaign_id, CampaignEventKind.STARTED)
    stores.campaigns.append_event(campaign.campaign_id, CampaignEventKind.CLASS_COMPLETE, class_id=CLASS_A)
    other = stores.campaigns.create_campaign("other", {}, CONFIG_HASH, [make_class_spec()])
    events = stores.campaigns.list_events(campaign.campaign_id)
    assert stores.campaigns.count_events(campaign.campaign_id) == len(events) == 3
    assert stores.campaigns.count_events(campaign.campaign_id, after_event_id=events[0].event_id) == 2
    assert stores.campaigns.count_events(campaign.campaign_id, kinds=[CampaignEventKind.CLASS_COMPLETE]) == 1
    assert stores.campaigns.count_events(campaign.campaign_id, after_event_id=events[2].event_id) == 0
    assert stores.campaigns.count_events(other.campaign_id) == 1


def test_unknown_campaign(stores):
    assert stores.campaigns.get_campaign("missing") is None
    assert stores.campaigns.config_version("missing") is None
    with pytest.raises(UnknownCampaign):
        stores.campaigns.set_desired_state("missing", CampaignDesiredState.RUNNING)
    with pytest.raises(UnknownCampaign):
        stores.campaigns.append_event("missing", CampaignEventKind.NOTE)


def test_a_change_in_the_callers_transaction_rolls_back_with_it(stores, campaign):
    with pytest.raises(RuntimeError):
        with stores.transaction() as session:
            stores.campaigns.set_desired_state(campaign.campaign_id, CampaignDesiredState.RUNNING, session=session)
            stores.campaigns.append_event(campaign.campaign_id, CampaignEventKind.NOTE, session=session)
            raise RuntimeError("engine step failed")
    assert stores.campaigns.get_campaign(campaign.campaign_id).desired_state == CampaignDesiredState.PAUSED
    assert len(stores.campaigns.list_events(campaign.campaign_id)) == 1


# Kinds and origins, list filters and totals, deletion (Phase 6)

CAMPAIGN, WORKBENCH = CampaignKind.CAMPAIGN, CampaignKind.WORKBENCH


def _make(stores, name, kind=CampaignKind.CAMPAIGN, origin=None):
    return stores.campaigns.create_campaign(name, {"name": name}, CONFIG_HASH, [make_class_spec()], kind=kind, origin=origin)


def test_kind_and_origin_come_with_the_creation(stores):
    plain = _make(stores, "plain")
    assert (plain.kind, plain.origin) == (CAMPAIGN, None)
    entry = _make(stores, "scene run", WORKBENCH, CampaignOrigin.SCENE_GENERATION)
    assert (entry.kind, entry.origin) == (WORKBENCH, CampaignOrigin.SCENE_GENERATION)
    assert stores.campaigns.get_campaign(entry.campaign_id) == entry
    (created,) = stores.campaigns.list_events(entry.campaign_id)
    assert (created.detail["kind"], created.detail["origin"]) == ("workbench", "scene_generation")


@pytest.mark.parametrize("kind, origin", [(WORKBENCH, CampaignOrigin.WIZARD), (CAMPAIGN, CampaignOrigin.LIVE_SESSION), (CAMPAIGN, CampaignOrigin.SIMULATION)])
def test_an_origin_belongs_to_one_kind(stores, kind, origin):
    with pytest.raises(ValueError, match=f"origin {origin.value} makes a"):
        _make(stores, "mismatch", kind, origin)
    assert stores.campaigns.count_campaigns() == 0


def test_list_campaigns_by_kind_origin_and_name(stores, clock):
    _make(stores, "Head-on 100% night", CAMPAIGN, CampaignOrigin.WIZARD)
    clock.advance(1)
    _make(stores, "crossing_cli", CAMPAIGN, CampaignOrigin.CLI)
    clock.advance(1)
    _make(stores, "head-on scene", WORKBENCH, CampaignOrigin.SCENE_GENERATION)
    clock.advance(1)
    live = _make(stores, "live session", WORKBENCH, CampaignOrigin.LIVE_SESSION)
    stores.campaigns.set_actual_state(live.campaign_id, CampaignActualState.RUNNING)

    def names(**filters):
        found = [campaign.name for campaign in stores.campaigns.list_campaigns(**filters)]
        assert stores.campaigns.count_campaigns(**filters) == len(found), filters
        return found

    assert names(kinds=[WORKBENCH]) == ["live session", "head-on scene"]
    assert names(kinds=[CAMPAIGN], origins=[CampaignOrigin.CLI]) == ["crossing_cli"]
    assert names(origins=[CampaignOrigin.WIZARD, CampaignOrigin.LIVE_SESSION]) == ["live session", "Head-on 100% night"]
    assert names(q="HEAD-ON") == ["head-on scene", "Head-on 100% night"]
    assert names(q="100%") == ["Head-on 100% night"]  # LIKE wildcards are taken literally
    assert names(q="g_c") == ["crossing_cli"]
    assert names(q="_") == ["crossing_cli"]
    assert names(q="") == ["live session", "head-on scene", "crossing_cli", "Head-on 100% night"]
    assert names(actual_states=[CampaignActualState.RUNNING], kinds=[WORKBENCH]) == ["live session"]
    assert [campaign.name for campaign in stores.campaigns.list_campaigns(kinds=[WORKBENCH], limit=1, offset=1)] == ["head-on scene"]


def test_campaign_totals_count_cases_by_state_and_verdicts_by_step(stores, campaign):
    other = _make(stores, "other")
    a0, a1 = stores.cases.create_cases(campaign.campaign_id, [NewCase(class_id=CLASS_A, case_index=index, seed=index) for index in range(2)])
    stores.cases.move_case(a1.case_id, a1.version, state=CaseState.DROPPED, reason="invalid scene")
    post_hoc = MonitorImplementation.POST_HOC
    stores.results.add_verdict(NewVerdict(case_id=a0.case_id, run_index=0, state=VerdictState.PASSED, monitor=post_hoc, step=StepKind.SCENE))
    stores.results.add_verdict(NewVerdict(case_id=a0.case_id, run_index=0, state=VerdictState.FAILED, monitor=post_hoc))
    stores.results.add_verdict(NewVerdict(case_id=a0.case_id, run_index=1, state=VerdictState.PASSED, monitor=post_hoc))
    totals = stores.campaigns.campaign_totals([campaign.campaign_id, other.campaign_id, "missing", campaign.campaign_id])
    assert totals[campaign.campaign_id] == CampaignTotals(
        cases={CaseState.ACTIVE: 1, CaseState.DROPPED: 1},
        verdicts={StepKind.SCENE: {VerdictState.PASSED: 1}, StepKind.SIMULATION: {VerdictState.FAILED: 1, VerdictState.PASSED: 1}},
    )
    assert totals[other.campaign_id] == CampaignTotals() == totals["missing"]
    assert stores.campaigns.campaign_totals([]) == {}


def test_current_configs_of_a_page_of_campaigns(stores, campaign):
    other = stores.campaigns.create_campaign("other", {"format": 2, "steps": ["simulation"]}, sha256_of("other"), [make_class_spec()])
    configs = stores.campaigns.current_configs([campaign.campaign_id, other.campaign_id, "missing"])
    assert set(configs) == {campaign.campaign_id, other.campaign_id}
    assert (configs[other.campaign_id].config, configs[other.campaign_id].version) == ({"format": 2, "steps": ["simulation"]}, 1)
    assert configs[campaign.campaign_id] == stores.campaigns.config_version(campaign.campaign_id)
    assert stores.campaigns.current_configs([]) == {}


def test_only_a_final_campaign_is_deleted(stores, campaign):
    with pytest.raises(CampaignStateConflict, match="only a stopped or completed campaign can be deleted"):
        stores.campaigns.delete_campaign(campaign.campaign_id)
    with pytest.raises(UnknownCampaign):
        stores.campaigns.delete_campaign("missing")
    assert stores.campaigns.get_campaign(campaign.campaign_id) is not None


def test_deleting_a_campaign_removes_its_rows_and_the_references_it_holds(stores, campaign, clock):
    other = _make(stores, "other")
    (case,) = stores.cases.create_cases(campaign.campaign_id, [NewCase(class_id=CLASS_A, case_index=0, seed=1)])
    (other_case,) = stores.cases.create_cases(other.campaign_id, [NewCase(class_id=CLASS_A, case_index=0, seed=1)])
    run = stores.results.add_run_record(NewRunRecord(case_id=case.case_id, run_index=0, trajectory_generator=None, trajectories_complete=True, stack={}, environment={}, seed=1))
    stores.results.add_verdict(NewVerdict(case_id=case.case_id, run_index=0, state=VerdictState.PASSED, monitor=MonitorImplementation.POST_HOC, run_record_id=run.run_record_id))
    stores.pipeline.add_intent(campaign.campaign_id, case.case_id, PipelineStage.GENERATE_SCENE, "campaign:x:case:1:generate_scene")
    item, scene, log, shared, upload = (sha256_of(name) for name in ("item", "scene", "log", "shared", "upload"))
    for artifact_hash in (item, scene, log, shared, upload):
        stores.artifacts.insert_if_absent(artifact_hash, "scene", 10, "application/json")
    stores.artifacts.add_reference(item, ArtifactHolderKind.CAMPAIGN, campaign.campaign_id, "input:0")
    stores.artifacts.add_reference(scene, ArtifactHolderKind.CASE, case.case_id, "scene")  # without the campaign id: found through the case
    stores.artifacts.add_reference(log, ArtifactHolderKind.RUN, run.run_record_id, "state_log")
    stores.artifacts.add_reference(shared, ArtifactHolderKind.CASE, case.case_id, "trajectory_data", campaign_id=campaign.campaign_id)
    stores.artifacts.add_reference(shared, ArtifactHolderKind.CASE, other_case.case_id, "trajectory_data", campaign_id=other.campaign_id)
    stores.artifacts.add_upload_reference(upload, START + timedelta(hours=24))
    stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.STOPPED)
    clock.advance(60)

    assert stores.campaigns.delete_campaign(campaign.campaign_id) == sorted([item, scene, log, shared])
    assert stores.campaigns.get_campaign(campaign.campaign_id) is None and stores.campaigns.config_versions(campaign.campaign_id) == []
    assert stores.cases.get_case(case.case_id) is None and stores.cases.list_classes(campaign.campaign_id) == []
    assert stores.results.get_run_record(run.run_record_id) is None and stores.results.count_verdicts(campaign.campaign_id) == 0
    assert stores.campaigns.count_events(campaign.campaign_id) == 0 and stores.pipeline.pipeline_jobs_of_case(case.case_id) == []
    remaining = {(reference.artifact_hash, reference.holder_kind) for name in (item, scene, log, shared, upload) for reference in stores.artifacts.references(name)}
    assert remaining == {(shared, ArtifactHolderKind.CASE), (upload, ArtifactHolderKind.UPLOAD)}
    assert stores.cases.get_case(other_case.case_id) is not None and stores.campaigns.get_campaign(other.campaign_id) is not None
    # freed artifacts are swept once unused for the grace period; what another holder references stays
    clock.advance(3600)
    assert sorted(record.artifact_hash for record in stores.artifacts.list_unreferenced(3600)) == sorted([item, scene, log])
