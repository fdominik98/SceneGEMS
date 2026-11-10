from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from scenegems_tool.cluster.protocol.jobs import JobState, JobType
from scenegems_tool.persistence.database import transaction
from scenegems_tool.persistence.schema import (
    CampaignClassState,
    CaseState,
    JobRow,
    MonitorImplementation,
    PipelineStage,
    RunSource,
    StepKind,
    TrajectoryGeneratorImplementation,
    VerdictRow,
    VerdictState,
)
from scenegems_tool.persistence.stores import ClassFindings, NewCase, NewRunRecord, NewVerdict, RuleFindings, UnknownCase
from scenegems_tool.persistence.stores.result_store import VERDICT_SORTS, rule_findings
from tests.scenegems_tool.persistence.stores.builders import START, sha256_of
from tests.scenegems_tool.persistence.stores.conftest import CLASS_A, CLASS_B

pytestmark = pytest.mark.postgres

STACK = {"own_ship": {"asv_system": "usv_navigation", "control_layer": "none", "simulation_layer": "kinematic"}}


def _cases(stores, campaign, class_id, count):
    return stores.cases.create_cases(campaign.campaign_id, [NewCase(class_id=class_id, case_index=index, seed=index) for index in range(count)])


def _run(case, run_index=0, repeat_index=0, digest="d" * 64):
    return NewRunRecord(
        case_id=case.case_id,
        run_index=run_index,
        repeat_index=repeat_index,
        trajectory_generator=TrajectoryGeneratorImplementation.MONITOR_DRIVEN_RRT,
        trajectories_complete=True,
        stack=STACK,
        repeatability_tier="exact",
        environment={"wind_vector": None, "waves": None, "seed": 11},
        seed=11,
        dt=1.0,
        steps=600,
        state_digest=digest,
        artifacts={"trajectories": sha256_of("simulated")},
        job_id=None,
        worker_node_id="worker-node-a",
        fingerprints={"scenegems-scenario-execution": "fp-execution"},
        durations_s={"scene_generation": 2.5, "simulation": 0.4},
    )


def _verdict(case, state=VerdictState.PASSED, run_index=0, **fields):
    failed = state == VerdictState.FAILED
    defaults = dict(
        monitor=MonitorImplementation.EMPTY if state == VerdictState.UNMONITORED else MonitorImplementation.POST_HOC,
        rule_outcomes={"rule_16": {"passed": not failed, "first_failure_s": 61.0 if failed else None}},
        failed_rules=("rule_16",) if failed else (),
        first_failure_time_s=61.0 if failed else None,
    )
    defaults.update(fields)
    return NewVerdict(case_id=case.case_id, run_index=run_index, state=state, **defaults)


def test_a_run_record_holds_what_repeats_the_run(stores, campaign):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    stored = stores.results.add_run_record(_run(case))
    assert (stored.campaign_id, stored.class_id, stored.case_id, stored.run_index, stored.repeat_index) == (campaign.campaign_id, CLASS_A, case.case_id, 0, 0)
    assert (stored.stack, stored.seed, stored.steps, stored.state_digest, stored.worker_node_id) == (STACK, 11, 600, "d" * 64, "worker-node-a")
    assert stored.trajectory_generator == TrajectoryGeneratorImplementation.MONITOR_DRIVEN_RRT and stored.trajectories_complete
    assert stored.durations_s == {"scene_generation": 2.5, "simulation": 0.4}
    assert stores.results.get_run_record(stored.run_record_id) == stored


def test_a_run_record_is_written_once(stores, campaign):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    first = stores.results.add_run_record(_run(case))
    assert stores.results.add_run_record(_run(case, digest="e" * 64)) == first
    second_repeat = stores.results.add_run_record(_run(case, repeat_index=1))
    assert second_repeat.run_record_id != first.run_record_id


def test_a_run_record_needs_a_case_and_hex_artifacts(stores, campaign):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    with pytest.raises(UnknownCase):
        stores.results.add_run_record(replace(_run(case), case_id=99_999))
    with pytest.raises(ValueError):
        stores.results.add_run_record(replace(_run(case), artifacts={"trajectories": "not-a-hash"}))


def test_verdicts_by_state_class_and_case(stores, campaign):
    a0, a1, a2 = _cases(stores, campaign, CLASS_A, 3)
    (b0,) = _cases(stores, campaign, CLASS_B, 1)
    run = stores.results.add_run_record(_run(a0))
    passed = stores.results.add_verdict(_verdict(a0, run_record_id=run.run_record_id))
    failed = stores.results.add_verdict(_verdict(a1, VerdictState.FAILED, sensitive=True))
    stores.results.add_verdict(_verdict(a2, VerdictState.PASSED))
    stores.results.add_verdict(_verdict(b0, VerdictState.UNMONITORED))
    assert (passed.run_record_id, passed.class_id, passed.failed_rules) == (run.run_record_id, CLASS_A, ())
    assert (failed.failed_rules, failed.first_failure_time_s, failed.sensitive) == (("rule_16",), 61.0, True)
    listed = lambda **filters: [verdict.case_id for verdict in stores.results.list_verdicts(campaign.campaign_id, **filters)]  # noqa: E731
    assert listed() == [a0.case_id, a1.case_id, a2.case_id, b0.case_id]
    assert listed(state=VerdictState.PASSED) == [a0.case_id, a2.case_id]
    assert listed(state=VerdictState.FAILED) == [a1.case_id]
    assert listed(class_id=CLASS_B) == [b0.case_id]
    assert listed(case_id=a2.case_id) == [a2.case_id]
    assert listed(sensitive=True) == [a1.case_id]
    assert listed(limit=1, offset=1) == [a1.case_id]
    assert stores.results.count_verdicts(campaign.campaign_id) == 4
    assert stores.results.count_verdicts(campaign.campaign_id, VerdictState.FAILED) == 1


def _sort_fixture(stores, campaign):
    """Verdicts of two FECs in a mixed order of insertion: states, first failure times (three nulls), steps and runs."""
    a0, a1 = _cases(stores, campaign, CLASS_A, 2)
    (b0,) = _cases(stores, campaign, CLASS_B, 1)
    added = {
        "b0": stores.results.add_verdict(_verdict(b0, VerdictState.FAILED, first_failure_time_s=5.0)),
        "a1_run1": stores.results.add_verdict(_verdict(a1, VerdictState.FAILED, run_index=1, first_failure_time_s=20.0)),
        "a0_scene": stores.results.add_verdict(_verdict(a0, VerdictState.PASSED, step=StepKind.SCENE)),
        "a0_run0": stores.results.add_verdict(_verdict(a0, VerdictState.FAILED, first_failure_time_s=9.0)),
        "a1_run0": stores.results.add_verdict(_verdict(a1, VerdictState.PASSED)),
        "a0_run1": stores.results.add_verdict(_verdict(a0, VerdictState.UNMONITORED, run_index=1)),
    }
    return {name: verdict.verdict_id for name, verdict in added.items()}


def _listed(stores, campaign, **options):
    return [verdict.verdict_id for verdict in stores.results.list_verdicts(campaign.campaign_id, **options)]


def test_verdicts_sort_by_fec_case_step_and_run_in_either_direction(stores, campaign):
    ids = _sort_fixture(stores, campaign)
    ascending = ["a0_scene", "a0_run0", "a0_run1", "a1_run0", "a1_run1", "b0"]
    assert _listed(stores, campaign) == [ids[name] for name in ascending]
    assert _listed(stores, campaign, sort="fec_id") == _listed(stores, campaign)
    assert _listed(stores, campaign, sort="fec_id", descending=True) == [ids[name] for name in reversed(ascending)]
    assert _listed(stores, campaign, sort="fec_id", descending=True, limit=2, offset=1) == [ids["a1_run1"], ids["a1_run0"]]


def test_verdicts_sort_by_a_column_with_nulls_last_and_stable_paging(stores, campaign):
    ids = _sort_fixture(stores, campaign)
    by = lambda *names: [ids[name] for name in names]  # noqa: E731
    # first_failure_time_s: 5, 9, 20, then the three verdicts without one in the default order; descending keeps the nulls last
    assert _listed(stores, campaign, sort="first_failure_time_s") == by("b0", "a0_run0", "a1_run1", "a0_scene", "a0_run1", "a1_run0")
    assert _listed(stores, campaign, sort="first_failure_time_s", descending=True) == by("a1_run1", "a0_run0", "b0", "a0_scene", "a0_run1", "a1_run0")
    assert _listed(stores, campaign, sort="state") == by("a0_run0", "a1_run1", "b0", "a0_scene", "a1_run0", "a0_run1")  # failed, passed, unmonitored
    assert _listed(stores, campaign, sort="state", descending=True)[:1] == by("a0_run1")
    assert _listed(stores, campaign, sort="step") == by("a0_scene", "a0_run0", "a0_run1", "a1_run0", "a1_run1", "b0")  # scene before simulation
    assert _listed(stores, campaign, sort="step", descending=True)[-1] == ids["a0_scene"]
    assert _listed(stores, campaign, sort="run_index") == by("a0_scene", "a0_run0", "a1_run0", "b0", "a0_run1", "a1_run1")
    assert _listed(stores, campaign, sort="case_index", descending=True) == by("a1_run0", "a1_run1", "a0_scene", "a0_run0", "a0_run1", "b0")
    # offset paging covers every verdict exactly once in each sort and direction
    for sort in VERDICT_SORTS:
        for descending in (False, True):
            whole = _listed(stores, campaign, sort=sort, descending=descending)
            paged = [identifier for offset in range(0, 6, 2) for identifier in _listed(stores, campaign, sort=sort, descending=descending, limit=2, offset=offset)]
            assert paged == whole and sorted(paged) == sorted(ids.values())


def test_a_sort_outside_the_whitelist_is_refused(stores, campaign):
    with pytest.raises(ValueError, match="cannot sort verdicts by margin"):
        stores.results.list_verdicts(campaign.campaign_id, sort="margin")
    with pytest.raises(ValueError, match="cannot sort verdicts by"):
        stores.results.list_verdicts(campaign.campaign_id, sort="id; DROP TABLE verdict")


def test_encounters_are_stored_with_the_verdict_and_null_when_absent(stores, campaign):
    a0, a1 = _cases(stores, campaign, CLASS_A, 2)
    encounters = {"OS_0 - TS_1": ["HEAD_ON", "OTHER"], "OS_0 - TS_2": ["CROSSING_FROM_PORT"]}
    with_types = stores.results.add_verdict(_verdict(a0, encounters=encounters))
    without = stores.results.add_verdict(_verdict(a1))
    assert with_types.encounters == encounters and without.encounters is None
    assert [verdict.encounters for verdict in stores.results.list_verdicts(campaign.campaign_id)] == [encounters, None]


def test_vessel_roles_are_stored_with_the_verdict_and_null_when_absent(stores, campaign):
    a0, a1 = _cases(stores, campaign, CLASS_A, 2)
    roles = {"OS_0 - TS_1": {"CROSSING_FROM_PORT": {"give_way": ["TS_1"], "stand_on": ["OS_0"]}}}
    with_roles = stores.results.add_verdict(_verdict(a0, encounter_roles=roles))
    without = stores.results.add_verdict(_verdict(a1))
    assert with_roles.encounter_roles == roles and without.encounter_roles is None
    assert [verdict.encounter_roles for verdict in stores.results.list_verdicts(campaign.campaign_id)] == [roles, None]


def test_count_verdicts_takes_the_filters_of_list_verdicts(stores, campaign):
    a0, a1, a2 = _cases(stores, campaign, CLASS_A, 3)
    (b0,) = _cases(stores, campaign, CLASS_B, 1)
    stores.results.add_verdict(_verdict(a0))
    stores.results.add_verdict(_verdict(a0, VerdictState.FAILED, run_index=1, sensitive=True))
    stores.results.add_verdict(_verdict(a1, VerdictState.FAILED))
    stores.results.add_verdict(_verdict(a2))
    stores.results.add_verdict(_verdict(b0, VerdictState.UNMONITORED))
    filters = [
        {},
        {"class_id": CLASS_A},
        {"class_id": CLASS_B},
        {"case_id": a0.case_id},
        {"state": VerdictState.FAILED},
        {"state": VerdictState.PASSED, "class_id": CLASS_A},
        {"run_index": 1},
        {"sensitive": True},
        {"sensitive": False, "state": VerdictState.FAILED},
    ]
    for keywords in filters:
        assert stores.results.count_verdicts(campaign.campaign_id, **keywords) == len(stores.results.list_verdicts(campaign.campaign_id, **keywords)), keywords
    assert stores.results.count_verdicts(campaign.campaign_id, run_index=0, class_id=CLASS_A) == 3
    assert stores.results.count_verdicts(campaign.campaign_id, state=VerdictState.FAILED, sensitive=True) == 1
    assert len(stores.results.list_verdicts(campaign.campaign_id, limit=1)) == 1 and stores.results.count_verdicts(campaign.campaign_id) == 5


def test_verdicts_and_run_records_carry_the_index_of_their_case(stores, campaign):
    cases = _cases(stores, campaign, CLASS_A, 3)
    (b0,) = _cases(stores, campaign, CLASS_B, 1)
    for case in (cases[2], b0, cases[0]):
        run = stores.results.add_run_record(_run(case))
        stored = stores.results.add_verdict(_verdict(case, run_record_id=run.run_record_id))
        assert stored.case_index == case.case_index
        assert run.case_index == case.case_index
    assert [(verdict.class_id, verdict.case_index) for verdict in stores.results.list_verdicts(campaign.campaign_id)] == [(CLASS_A, 0), (CLASS_A, 2), (CLASS_B, 0)]
    assert [record.case_index for record in stores.results.list_run_records(campaign.campaign_id)] == [0, 2, 0]
    found = stores.results.get_run_record(stores.results.list_run_records(campaign.campaign_id)[1].run_record_id)
    assert found.case_index == 2
    # storing the same verdict again returns the stored one, with its index
    assert stores.results.add_verdict(_verdict(cases[2])).case_index == 2


def test_one_verdict_per_case_and_run(stores, campaign):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    first = stores.results.add_verdict(_verdict(case))
    assert stores.results.add_verdict(_verdict(case, VerdictState.FAILED)) == first
    assert stores.results.add_verdict(_verdict(case, run_index=1)).verdict_id != first.verdict_id


@pytest.mark.parametrize(
    "fields",
    [
        dict(state=VerdictState.UNMONITORED, monitor=MonitorImplementation.POST_HOC),
        dict(state=VerdictState.PASSED, monitor=MonitorImplementation.EMPTY),
        dict(state=VerdictState.PASSED, monitor=MonitorImplementation.POST_HOC, early_stop_time_s=40.0),
        dict(state=VerdictState.PASSED, monitor=MonitorImplementation.LIVE, first_failure_time_s=3.0),
        dict(state=VerdictState.PASSED, monitor=MonitorImplementation.POST_HOC, failed_rules=("rule_8",)),
    ],
)
def test_inconsistent_verdicts_are_refused(stores, campaign, fields):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    with pytest.raises(ValueError):
        stores.results.add_verdict(NewVerdict(case_id=case.case_id, run_index=0, **fields))


def test_the_table_refuses_what_the_store_checks(stores, campaign, session_factory):
    # The constraints hold also for writers that bypass the store's checks
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    with pytest.raises(IntegrityError):
        with transaction(session_factory) as session:
            session.execute(
                insert(VerdictRow).values(
                    case_id=case.case_id,
                    campaign_id=campaign.campaign_id,
                    class_id=CLASS_A,
                    run_index=0,
                    state="passed",
                    monitor="empty",
                    rule_outcomes={},
                    failed_rules=[],
                    sensitive=False,
                    created_at=case.created_at,
                )
            )


def test_a_live_verdict_with_an_early_stop(stores, campaign):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    verdict = stores.results.add_verdict(_verdict(case, VerdictState.FAILED, monitor=MonitorImplementation.LIVE, early_stop_time_s=75.0))
    assert (verdict.monitor, verdict.early_stop_time_s, verdict.margin) == (MonitorImplementation.LIVE, 75.0, None)


def test_run_records_by_class_and_case(stores, campaign):
    a0, a1 = _cases(stores, campaign, CLASS_A, 2)
    (b0,) = _cases(stores, campaign, CLASS_B, 1)
    for case in (b0, a1, a0):
        stores.results.add_run_record(_run(case))
    stores.results.add_run_record(_run(a0, run_index=1))
    listed = lambda **filters: [(record.case_id, record.run_index) for record in stores.results.list_run_records(campaign.campaign_id, **filters)]  # noqa: E731
    assert listed() == [(a0.case_id, 0), (a0.case_id, 1), (a1.case_id, 0), (b0.case_id, 0)]
    assert listed(class_id=CLASS_B) == [(b0.case_id, 0)]
    assert listed(case_id=a0.case_id, run_index=1) == [(a0.case_id, 1)]
    assert listed(limit=2, offset=1) == [(a0.case_id, 1), (a1.case_id, 0)]


def test_count_run_records_takes_the_filters_of_list_run_records(stores, campaign):
    a0, a1 = _cases(stores, campaign, CLASS_A, 2)
    (b0,) = _cases(stores, campaign, CLASS_B, 1)
    for case in (b0, a1, a0):
        stores.results.add_run_record(_run(case))
    stores.results.add_run_record(_run(a0, run_index=1))
    stores.results.add_run_record(_run(a0, repeat_index=1))
    for keywords in ({}, {"class_id": CLASS_A}, {"class_id": CLASS_B}, {"case_id": a0.case_id}, {"run_index": 1}, {"case_id": a0.case_id, "run_index": 0}, {"class_id": CLASS_B, "run_index": 1}):
        assert stores.results.count_run_records(campaign.campaign_id, **keywords) == len(stores.results.list_run_records(campaign.campaign_id, **keywords)), keywords
    assert stores.results.count_run_records(campaign.campaign_id) == 5


def test_coverage_per_class(stores, campaign):
    a0, a1, a2 = _cases(stores, campaign, CLASS_A, 3)
    (b0,) = _cases(stores, campaign, CLASS_B, 1)
    for case, state in ((a0, VerdictState.PASSED), (a1, VerdictState.FAILED)):
        stores.results.add_verdict(_verdict(case, state))
        stores.results.add_verdict(_verdict(case, VerdictState.UNMONITORED, run_index=1))
        current = stores.cases.get_case(case.case_id)
        stores.cases.move_case(case.case_id, current.version, stage=PipelineStage.VERDICT, state=CaseState.COMPLETE)
    stores.cases.move_case(a2.case_id, a2.version, state=CaseState.DROPPED, reason="invalid scene")
    stores.cases.set_class_state(campaign.campaign_id, CLASS_B, CampaignClassState.ABANDONED)
    coverage_a, coverage_b = stores.results.coverage(campaign.campaign_id)
    assert (coverage_a.class_id, coverage_a.state, coverage_a.quota, coverage_a.complete, coverage_a.dropped, coverage_a.in_flight) == (CLASS_A, CampaignClassState.OPEN, 3, 2, 1, 0)
    assert coverage_a.verdicts == {0: {VerdictState.PASSED: 1, VerdictState.FAILED: 1}, 1: {VerdictState.UNMONITORED: 2}}
    assert coverage_a.verdict_count(run_index=0) == 2 and coverage_a.verdict_count(VerdictState.FAILED) == 1
    assert (coverage_b.state, coverage_b.in_flight, coverage_b.verdicts, coverage_b.verdict_count()) == (CampaignClassState.ABANDONED, 1, {}, 0)
    assert b0.class_id == CLASS_B


# Step verdicts, run sources and findings (Phase 6)


def test_a_case_has_a_verdict_per_step(stores, campaign):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    scene = stores.results.add_verdict(_verdict(case, step=StepKind.SCENE))
    trajectories = stores.results.add_verdict(_verdict(case, VerdictState.FAILED, step=StepKind.TRAJECTORIES))
    simulation = stores.results.add_verdict(_verdict(case, VerdictState.UNMONITORED))
    assert (scene.step, trajectories.step, simulation.step) == (StepKind.SCENE, StepKind.TRAJECTORIES, StepKind.SIMULATION)
    # written once per case, step and run
    assert stores.results.add_verdict(_verdict(case, VerdictState.FAILED, step=StepKind.SCENE)) == scene
    assert [verdict.step for verdict in stores.results.list_verdicts(campaign.campaign_id)] == [StepKind.SCENE, StepKind.TRAJECTORIES, StepKind.SIMULATION]
    for step in StepKind:
        assert [verdict.step for verdict in stores.results.list_verdicts(campaign.campaign_id, step=step)] == [step]
        assert stores.results.count_verdicts(campaign.campaign_id, step=step) == 1
    assert stores.results.count_verdicts(campaign.campaign_id, VerdictState.FAILED, step=StepKind.SIMULATION) == 0


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"step": StepKind.SCENE, "run_index": 1}, "the scene step has one verdict per case, at run index 0"),
        ({"step": StepKind.TRAJECTORIES, "monitor": MonitorImplementation.LIVE}, "the live monitor judges simulated runs only"),
    ],
)
def test_a_generation_step_verdict_is_one_per_case_and_not_live(stores, campaign, fields, message):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    with pytest.raises(ValueError, match=message):
        stores.results.add_verdict(_verdict(case, **fields))


def test_a_run_record_from_a_live_session_without_a_generator(stores, campaign):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    stored = stores.results.add_run_record(replace(_run(case), trajectory_generator=None, source=RunSource.LIVE_SESSION, job_id=None))
    assert (stored.trajectory_generator, stored.source) == (None, RunSource.LIVE_SESSION)
    assert stores.results.get_run_record(stored.run_record_id) == stored
    assert stores.results.add_run_record(_run(case, run_index=1)).source == RunSource.JOB


def test_coverage_counts_the_simulation_verdicts_unless_told_otherwise(stores, campaign):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    stores.results.add_verdict(_verdict(case, VerdictState.FAILED, step=StepKind.SCENE))
    stores.results.add_verdict(_verdict(case))
    coverage_a = stores.results.coverage(campaign.campaign_id)[0]
    assert coverage_a.verdicts == {0: {VerdictState.PASSED: 1}}
    assert stores.results.coverage(campaign.campaign_id, StepKind.SCENE)[0].verdicts == {0: {VerdictState.FAILED: 1}}
    assert stores.results.coverage(campaign.campaign_id, None)[0].verdicts == {0: {VerdictState.PASSED: 1, VerdictState.FAILED: 1}}


def _job_of(stores, session_factory, case, stage, running_s, index):
    """A finished job of the case's stage that ran for running_s, linked to the case through a pipeline job."""
    job_id, key = f"job-{stage.value}-{index}", f"key-{stage.value}-{index}"
    submitted = START
    with transaction(session_factory) as session:
        session.add(
            JobRow(
                id=job_id,
                job_type=JobType.SCENE_GENERATION,
                payload={},
                required_labels={},
                required_fingerprints={},
                min_memory_mb=0,
                min_cpus=0,
                priority=0,
                max_attempts=1,
                idempotency_key=key,
                state=JobState.SUCCEEDED,
                attempt=1,
                failed_attempts=0,
                submitted_at=submitted,
                available_at=submitted,
                updated_at=submitted,
                started_at=submitted + timedelta(seconds=5),
                finished_at=submitted + timedelta(seconds=5 + running_s),
            )
        )
    stores.pipeline.add_intent(case.campaign_id, case.case_id, stage, key)
    stores.pipeline.link_job(key, job_id)


def test_findings_of_a_monitored_scene_step(stores, step_outputs, session_factory):
    _job_of(stores, session_factory, step_outputs.a0, PipelineStage.GENERATE_SCENE, 10.0, 0)
    _job_of(stores, session_factory, step_outputs.a1, PipelineStage.GENERATE_SCENE, 30.0, 1)
    _job_of(stores, session_factory, step_outputs.a0, PipelineStage.GENERATE_TRAJECTORIES, 99.0, 2)  # another step's
    findings = stores.results.findings(step_outputs.campaign_id, StepKind.SCENE)
    assert (findings.step, findings.monitored) == (StepKind.SCENE, True)  # it has a post_hoc verdict
    assert findings.cases == {CaseState.COMPLETE: 1, CaseState.DROPPED: 2, CaseState.ACTIVE: 1}
    assert (findings.outputs_count, findings.outputs_valid, findings.outputs_complete) == (3, 2, 2)  # a valid scene counts as complete
    assert (findings.verdicts, findings.failed_rules) == ({VerdictState.PASSED: 1}, ())
    assert findings.classes == (ClassFindings(CLASS_A, cases=3, passed=1, failed=0), ClassFindings(CLASS_B, cases=1, passed=0, failed=0))
    assert (findings.duration_median_s, findings.duration_p90_s) == (pytest.approx(20.0), pytest.approx(28.0))


def test_findings_count_the_vessel_pairs_by_their_first_encounter_type(stores, campaign):
    a0, a1, a2 = _cases(stores, campaign, CLASS_A, 3)
    stores.results.add_verdict(_verdict(a0, step=StepKind.SCENE, encounters={"OS_0 - TS_1": ["HEAD_ON", "OTHER"], "OS_0 - TS_2": ["OTHER"]}))
    stores.results.add_verdict(_verdict(a1, VerdictState.FAILED, step=StepKind.SCENE, encounters={"OS_0 - TS_1": ["HEAD_ON"]}))
    stores.results.add_verdict(_verdict(a2, step=StepKind.SCENE))  # stored before encounters existed: adds none
    stores.results.add_verdict(_verdict(a0, encounters={"OS_0 - TS_1": ["OVERTAKING_TO_PORT"]}))  # another step's
    findings = stores.results.findings(campaign.campaign_id, StepKind.SCENE)
    assert findings.encounter_types == {"HEAD_ON": 2, "OTHER": 1}  # by the first type of each pair, OTHER included, most first
    assert stores.results.findings(campaign.campaign_id, StepKind.SIMULATION).encounter_types == {"OVERTAKING_TO_PORT": 1}
    assert stores.results.findings(campaign.campaign_id, StepKind.TRAJECTORIES).encounter_types == {}
    assert stores.results.findings(campaign.campaign_id, StepKind.SCENE, monitored=False).encounter_types == {}  # an unmonitored step has statistics only


def test_findings_of_the_trajectory_step_name_the_failed_rules(stores, step_outputs):
    findings = stores.results.findings(step_outputs.campaign_id, StepKind.TRAJECTORIES)
    assert findings.cases == {CaseState.COMPLETE: 1, CaseState.DROPPED: 1}
    assert (findings.outputs_count, findings.outputs_valid, findings.outputs_complete) == (2, 1, 1)
    assert findings.verdicts == {VerdictState.FAILED: 1}
    # rule_13 failed for two relations of the one verdict: counted once, at its earliest failure
    assert findings.failed_rules == (RuleFindings("rule_13", 1, 30.0, 30.0), RuleFindings("rule_16", 1, 12.0, 12.0))
    assert findings.classes == (ClassFindings(CLASS_A, 1, 0, 1), ClassFindings(CLASS_B, 1, 0, 0))
    assert (findings.duration_median_s, findings.duration_p90_s) == (None, None)


def test_findings_of_an_unmonitored_step_are_statistics_only(stores, step_outputs):
    findings = stores.results.findings(step_outputs.campaign_id, StepKind.SIMULATION, monitored=False)
    assert (findings.monitored, findings.verdicts, findings.failed_rules) == (False, {}, ())
    assert findings.cases == {CaseState.COMPLETE: 1}
    assert (findings.outputs_count, findings.outputs_valid, findings.outputs_complete) == (2, 2, 1)
    assert findings.classes == (ClassFindings(CLASS_A, 1, 0, 0), ClassFindings(CLASS_B, 0, 0, 0))
    monitored = stores.results.findings(step_outputs.campaign_id, StepKind.SIMULATION)
    assert monitored.verdicts == {VerdictState.FAILED: 1, VerdictState.PASSED: 1} and monitored.failed_rules == (RuleFindings("rule_8", 1, None, None),)


def test_a_step_only_judged_by_the_empty_monitor_counts_as_unmonitored(stores, campaign):
    (case,) = _cases(stores, campaign, CLASS_A, 1)
    stores.results.add_verdict(_verdict(case, VerdictState.UNMONITORED, step=StepKind.SCENE))
    findings = stores.results.findings(campaign.campaign_id, StepKind.SCENE)
    assert (findings.monitored, findings.verdicts) == (False, {})


def test_rule_findings_count_rules_over_verdicts():
    outcomes = {"A - B": {"rule_13": {"failed": 10.0}}, "A - C": {"rule_13": {"failed": 4.0}, "rule_14": {"failed": 7.0}}}
    findings = rule_findings(
        [
            (["A - B: rule_13", "A - C: rule_13", "A - C: rule_14"], outcomes),
            (["A - B: rule_13"], {"A - B": {"rule_13": {"failed": 20.0}}}),
            (["rule_15"], {}),  # no relation, no time
            (["A - B: rule_13"], {}),
        ]
    )
    assert findings == (RuleFindings("rule_13", 3, 4.0, 12.0), RuleFindings("rule_14", 1, 7.0, 7.0), RuleFindings("rule_15", 1, None, None))
