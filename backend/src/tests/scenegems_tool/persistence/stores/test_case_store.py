import pytest
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from scenegems_tool.persistence.database import transaction
from scenegems_tool.persistence.schema import CampaignClassRow, CampaignClassState, CaseState, MonitorImplementation, PipelineStage, StepKind, VerdictState
from scenegems_tool.persistence.stores import CaseConflict, ClassCounts, ClassStateConflict, NewCase, NewVerdict, OutputArtifact, UnknownCase, UnknownClass
from tests.scenegems_tool.persistence.stores.builders import sha256_of
from tests.scenegems_tool.persistence.stores.conftest import CLASS_A, CLASS_B, SCENE_0, SCENE_1, STATE_LOG_0, STATE_LOG_1, TRAJECTORY_DATA_0, TRAJECTORY_DATA_1, TRAJECTORY_FAILURES

pytestmark = pytest.mark.postgres


def _counts(stores, campaign_id, class_id):
    found = stores.cases.get_class(campaign_id, class_id)
    return ClassCounts(complete=found.complete_count, dropped=found.dropped_count, in_flight=found.in_flight_count)


def _create(stores, campaign, class_id=CLASS_A, indexes=(0,)):
    return stores.cases.create_cases(campaign.campaign_id, [NewCase(class_id=class_id, case_index=index, seed=1000 + index) for index in indexes])


def test_created_cases_are_active_and_counted_in_flight(stores, campaign):
    cases = _create(stores, campaign, indexes=(0, 1, 2))
    assert [(case.case_index, case.seed, case.stage, case.state, case.version) for case in cases] == [
        (0, 1000, PipelineStage.GENERATE_SCENE, CaseState.ACTIVE, 1),
        (1, 1001, PipelineStage.GENERATE_SCENE, CaseState.ACTIVE, 1),
        (2, 1002, PipelineStage.GENERATE_SCENE, CaseState.ACTIVE, 1),
    ]
    assert _counts(stores, campaign.campaign_id, CLASS_A) == ClassCounts(in_flight=3)
    assert _counts(stores, campaign.campaign_id, CLASS_B) == ClassCounts()
    assert stores.cases.get_case(cases[1].case_id) == cases[1]
    assert stores.cases.find_case(campaign.campaign_id, CLASS_A, 2) == cases[2]
    assert stores.cases.next_case_index(campaign.campaign_id, CLASS_A) == 3
    assert stores.cases.next_case_index(campaign.campaign_id, CLASS_B) == 0


def test_an_index_is_taken_once_per_class(stores, campaign):
    _create(stores, campaign, indexes=(0,))
    _create(stores, campaign, class_id=CLASS_B, indexes=(0,))
    with pytest.raises(IntegrityError):
        _create(stores, campaign, indexes=(0,))
    assert _counts(stores, campaign.campaign_id, CLASS_A) == ClassCounts(in_flight=1)


def test_cases_only_in_open_classes_of_the_campaign(stores, campaign):
    with pytest.raises(UnknownClass):
        _create(stores, campaign, class_id="6vessel_0obstacle_scenarios/fec1")
    stores.cases.set_class_state(campaign.campaign_id, CLASS_B, CampaignClassState.ABANDONED, reason="failure budget used up")
    with pytest.raises(ClassStateConflict):
        _create(stores, campaign, class_id=CLASS_B)


def test_moving_a_case_through_its_stages(stores, campaign, clock):
    (case,) = _create(stores, campaign)
    clock.advance(3)
    scene = sha256_of("scene")
    moved = stores.cases.move_case(case.case_id, case.version, stage=PipelineStage.GENERATE_TRAJECTORIES, scene_artifact=scene, progress={"scene_job": "j1"})
    assert (moved.stage, moved.state, moved.version, moved.scene_artifact, moved.progress, moved.updated_at) == (
        PipelineStage.GENERATE_TRAJECTORIES,
        CaseState.ACTIVE,
        2,
        scene,
        {"scene_job": "j1"},
        clock.now,
    )
    trajectories = sha256_of("trajectories")
    moved = stores.cases.move_case(
        case.case_id, moved.version, stage=PipelineStage.SIMULATE, expected_stage=PipelineStage.GENERATE_TRAJECTORIES, trajectories_artifact=trajectories, trajectories_complete=True
    )
    assert (moved.stage, moved.trajectories_artifact, moved.trajectories_complete, moved.scene_artifact) == (PipelineStage.SIMULATE, trajectories, True, scene)
    done = stores.cases.move_case(case.case_id, moved.version, stage=PipelineStage.VERDICT, state=CaseState.COMPLETE)
    assert (done.state, done.finished_at) == (CaseState.COMPLETE, clock.now)
    assert _counts(stores, campaign.campaign_id, CLASS_A) == ClassCounts(complete=1)


def test_a_stale_version_or_an_unexpected_stage_is_a_conflict(stores, campaign):
    (case,) = _create(stores, campaign)
    moved = stores.cases.move_case(case.case_id, case.version, stage=PipelineStage.GENERATE_TRAJECTORIES)
    with pytest.raises(CaseConflict) as conflict:
        stores.cases.move_case(case.case_id, case.version, stage=PipelineStage.SIMULATE)
    assert conflict.value.current == moved
    with pytest.raises(CaseConflict):
        stores.cases.move_case(case.case_id, moved.version, stage=PipelineStage.SIMULATE, expected_stage=PipelineStage.GENERATE_SCENE)
    with pytest.raises(CaseConflict):
        stores.cases.move_case(case.case_id, moved.version, state=CaseState.COMPLETE, expected_state=CaseState.DROPPED)
    assert stores.cases.get_case(case.case_id) == moved
    with pytest.raises(UnknownCase):
        stores.cases.move_case(10_000, 1)


def test_a_final_case_keeps_its_state_but_may_lose_its_artifacts(stores, campaign):
    (case,) = _create(stores, campaign)
    scene = sha256_of("scene")
    dropped = stores.cases.move_case(case.case_id, case.version, state=CaseState.DROPPED, scene_artifact=scene, reason="invalid scene")
    assert dropped.reason == "invalid scene"
    with pytest.raises(CaseConflict):
        stores.cases.move_case(case.case_id, dropped.version, state=CaseState.ACTIVE)
    cleared = stores.cases.move_case(case.case_id, dropped.version, scene_artifact=None)
    assert (cleared.state, cleared.scene_artifact, cleared.reason) == (CaseState.DROPPED, None, "invalid scene")


def test_artifacts_must_be_sha256_hex(stores, campaign):
    (case,) = _create(stores, campaign)
    with pytest.raises(ValueError):
        stores.cases.move_case(case.case_id, case.version, scene_artifact="ABC")


@pytest.mark.parametrize(
    "final, counts",
    [
        (CaseState.COMPLETE, ClassCounts(complete=1, in_flight=1)),
        (CaseState.DROPPED, ClassCounts(dropped=1, in_flight=1)),
        (CaseState.FAILED, ClassCounts(dropped=1, in_flight=1)),
        (CaseState.CANCELLED, ClassCounts(in_flight=1)),
    ],
)
def test_counts_follow_the_case_states(stores, campaign, final, counts):
    first, _ = _create(stores, campaign, indexes=(0, 1))
    stores.cases.move_case(first.case_id, first.version, state=final)
    assert _counts(stores, campaign.campaign_id, CLASS_A) == counts
    assert stores.cases.class_counts_from_cases(campaign.campaign_id)[CLASS_A] == counts


def test_failure_budget_left(stores, campaign):
    first, second = _create(stores, campaign, indexes=(0, 1))
    stores.cases.move_case(first.case_id, first.version, state=CaseState.DROPPED)
    stores.cases.move_case(second.case_id, second.version, state=CaseState.FAILED, reason="out of attempts: simulator crashed")
    assert stores.cases.get_class(campaign.campaign_id, CLASS_A).failure_budget_left == 0


def test_recount_repairs_counts_that_drifted(stores, campaign, session_factory):
    _create(stores, campaign, indexes=(0, 1))
    with transaction(session_factory) as session:
        session.execute(update(CampaignClassRow).where(CampaignClassRow.class_id == CLASS_A).values(in_flight_count=7, complete_count=1))
    (corrected,) = stores.cases.recount_classes(campaign.campaign_id)
    assert (corrected.class_id, corrected.in_flight_count, corrected.complete_count) == (CLASS_A, 2, 0)
    assert stores.cases.recount_classes(campaign.campaign_id) == []


def test_list_cases_by_class_and_state(stores, campaign):
    a0, a1, a2 = _create(stores, campaign, indexes=(0, 1, 2))
    (b0,) = _create(stores, campaign, class_id=CLASS_B, indexes=(0,))
    stores.cases.move_case(a1.case_id, a1.version, state=CaseState.COMPLETE)
    stores.cases.move_case(b0.case_id, b0.version, stage=PipelineStage.SIMULATE)
    listed = lambda **filters: [(case.class_id, case.case_index) for case in stores.cases.list_cases(campaign.campaign_id, **filters)]  # noqa: E731
    assert listed() == [(CLASS_A, 0), (CLASS_A, 1), (CLASS_A, 2), (CLASS_B, 0)]
    assert listed(class_id=CLASS_A, states=[CaseState.ACTIVE]) == [(CLASS_A, 0), (CLASS_A, 2)]
    assert listed(stages=[PipelineStage.SIMULATE]) == [(CLASS_B, 0)]
    assert listed(limit=2, offset=1) == [(CLASS_A, 1), (CLASS_A, 2)]
    assert stores.cases.count_cases(campaign.campaign_id) == 4
    assert stores.cases.count_cases(campaign.campaign_id, [CaseState.COMPLETE]) == 1


def test_count_cases_takes_the_filters_of_list_cases(stores, campaign):
    a0, a1, a2 = _create(stores, campaign, indexes=(0, 1, 2))
    (b0,) = _create(stores, campaign, class_id=CLASS_B, indexes=(0,))
    stores.cases.move_case(a1.case_id, a1.version, state=CaseState.COMPLETE)
    stores.cases.move_case(b0.case_id, b0.version, stage=PipelineStage.SIMULATE)
    filters = [
        {},
        {"class_id": CLASS_A},
        {"class_id": CLASS_A, "states": [CaseState.ACTIVE]},
        {"states": [CaseState.COMPLETE, CaseState.DROPPED]},
        {"stages": [PipelineStage.SIMULATE]},
        {"class_id": CLASS_B, "stages": [PipelineStage.GENERATE_SCENE]},
        {"states": [CaseState.FAILED]},
    ]
    for keywords in filters:
        counted = stores.cases.count_cases(campaign.campaign_id, keywords.get("states"), class_id=keywords.get("class_id"), stages=keywords.get("stages"))
        assert counted == len(stores.cases.list_cases(campaign.campaign_id, **keywords)), keywords
    assert stores.cases.count_cases(campaign.campaign_id, class_id=CLASS_A) == 3
    assert stores.cases.count_cases(campaign.campaign_id, stages=[PipelineStage.SIMULATE]) == 1
    # a page does not change the count
    assert len(stores.cases.list_cases(campaign.campaign_id, limit=1)) == 1 and stores.cases.count_cases(campaign.campaign_id) == 4


def test_class_states(stores, campaign, clock):
    clock.advance(9)
    closed = stores.cases.set_class_state(campaign.campaign_id, CLASS_A, CampaignClassState.COMPLETE, expected=CampaignClassState.OPEN)
    assert (closed.state, closed.finished_at) == (CampaignClassState.COMPLETE, clock.now)
    assert stores.cases.set_class_state(campaign.campaign_id, CLASS_A, CampaignClassState.COMPLETE) == closed
    with pytest.raises(ClassStateConflict):
        stores.cases.set_class_state(campaign.campaign_id, CLASS_A, CampaignClassState.ABANDONED)
    with pytest.raises(ClassStateConflict):
        stores.cases.set_class_state(campaign.campaign_id, CLASS_B, CampaignClassState.COMPLETE, expected=CampaignClassState.ABANDONED)
    assert [c.class_id for c in stores.cases.list_classes(campaign.campaign_id, [CampaignClassState.OPEN])] == [CLASS_B]


def test_several_moves_commit_together(stores, campaign):
    first, second = _create(stores, campaign, indexes=(0, 1))
    with pytest.raises(CaseConflict):
        with stores.transaction() as session:
            stores.cases.move_case(first.case_id, first.version, state=CaseState.COMPLETE, session=session)
            stores.cases.move_case(second.case_id, second.version + 1, state=CaseState.COMPLETE, session=session)
    assert stores.cases.get_case(first.case_id).state == CaseState.ACTIVE
    assert _counts(stores, campaign.campaign_id, CLASS_A) == ClassCounts(in_flight=2)


# Case inputs and step outputs (Phase 6)


def test_a_case_keeps_the_input_of_its_first_step(stores, campaign):
    source = {"campaign_id": "c-0", "case_id": 4, "step": "scene_generation"}
    (case,) = stores.cases.create_cases(
        campaign.campaign_id, [NewCase(class_id=CLASS_A, case_index=0, seed=1, stage=PipelineStage.GENERATE_TRAJECTORIES, input_artifact=sha256_of("scene"), input_source=source)]
    )
    assert (case.stage, case.input_artifact, case.input_source) == (PipelineStage.GENERATE_TRAJECTORIES, sha256_of("scene"), source)
    assert stores.cases.get_case(case.case_id) == case
    (plain,) = _create(stores, campaign, CLASS_B)
    assert (plain.input_artifact, plain.input_source) == (None, None)
    with pytest.raises(ValueError):
        stores.cases.create_cases(campaign.campaign_id, [NewCase(class_id=CLASS_A, case_index=1, seed=1, input_artifact="not a hash")])


def _rows(outputs):
    return [(output.case_id, output.state, None if output.artifact is None else output.artifact.sha256, output.valid, output.complete, output.verdict_state) for output in outputs]


def test_scene_outputs_are_one_row_per_case_that_reached_scene_generation(stores, step_outputs):
    outputs = stores.cases.list_outputs(step_outputs.campaign_id, StepKind.SCENE)
    a0, a1, a2, b0 = step_outputs.a0, step_outputs.a1, step_outputs.a2, step_outputs.b0
    assert _rows(outputs) == [
        (a0.case_id, CaseState.COMPLETE, SCENE_0, True, None, VerdictState.PASSED),
        (a1.case_id, CaseState.DROPPED, SCENE_1, False, None, None),  # dropped at scene generation: invalid
        (a2.case_id, CaseState.ACTIVE, None, False, None, None),
        (b0.case_id, CaseState.DROPPED, SCENE_0, True, None, None),  # dropped later: its scene is valid
    ]
    first = outputs[0]
    assert first.artifact == OutputArtifact(sha256=SCENE_0, size_bytes=100, kind="scene", media_type="application/json", pointer=None)
    assert (first.step, first.case_index, first.class_id, first.run_index, first.repeat_index, first.run_record_id, first.failed_rules) == (StepKind.SCENE, 0, CLASS_A, None, None, None, ())
    assert outputs[1].artifact == OutputArtifact(sha256=SCENE_1, size_bytes=None, kind=None, media_type=None)  # no artifact record any more
    assert outputs[1].reason == "the scene generation found no valid scene"


def test_trajectory_outputs_point_at_the_trajectories(stores, step_outputs):
    outputs = stores.cases.list_outputs(step_outputs.campaign_id, StepKind.TRAJECTORIES)
    assert _rows(outputs) == [
        (step_outputs.a0.case_id, CaseState.COMPLETE, TRAJECTORY_DATA_0, True, True, VerdictState.FAILED),
        (step_outputs.b0.case_id, CaseState.DROPPED, TRAJECTORY_DATA_1, False, False, None),
    ]
    assert outputs[0].artifact.pointer == "/trajectories" and outputs[0].artifact.kind == "trajectory_data"
    assert outputs[0].failed_rules == TRAJECTORY_FAILURES


def test_simulation_outputs_are_one_row_per_run_record(stores, step_outputs):
    outputs = stores.cases.list_outputs(step_outputs.campaign_id, StepKind.SIMULATION)
    runs = step_outputs.runs
    assert [(output.run_index, output.repeat_index, output.run_record_id) for output in outputs] == [
        (0, 0, runs[(0, 0)].run_record_id),
        (0, 1, runs[(0, 1)].run_record_id),
        (1, 0, runs[(1, 0)].run_record_id),
    ]
    case_id = step_outputs.a0.case_id
    assert _rows(outputs) == [
        (case_id, CaseState.COMPLETE, STATE_LOG_0, True, True, VerdictState.FAILED),
        (case_id, CaseState.COMPLETE, STATE_LOG_1, True, False, VerdictState.FAILED),  # the repeat of run 0 shows the run's verdict
        (case_id, CaseState.COMPLETE, None, False, True, VerdictState.PASSED),
    ]
    assert outputs[0].artifact.kind == "trajectories" and outputs[0].failed_rules == ("OS_0 - TS_1: rule_8",)


def test_a_case_at_simulation_without_runs_has_a_row(stores, campaign, step_outputs):
    (waiting,) = stores.cases.create_cases(campaign.campaign_id, [NewCase(class_id=CLASS_B, case_index=1, seed=1, stage=PipelineStage.SIMULATE)])
    (row,) = stores.cases.list_outputs(campaign.campaign_id, StepKind.SIMULATION, class_id=CLASS_B)
    assert (row.case_id, row.run_record_id, row.artifact, row.valid, row.complete, row.verdict_state) == (waiting.case_id, None, None, False, None, None)
    assert (row.first_failure_time_s, row.encounters, row.encounter_roles) == (None, None, None)


def test_outputs_carry_the_monitor_summary_of_the_verdict(stores, campaign):
    (case,) = _create(stores, campaign)
    encounters = {"OS_0 - TS_1": ["CROSSING_FROM_PORT", "OTHER"]}
    roles = {"OS_0 - TS_1": {"CROSSING_FROM_PORT": {"give_way": ["TS_1"], "stand_on": ["OS_0"]}}}
    stores.results.add_verdict(
        NewVerdict(
            case_id=case.case_id,
            run_index=0,
            state=VerdictState.FAILED,
            monitor=MonitorImplementation.POST_HOC,
            failed_rules=("OS_0 - TS_1: rule_16",),
            first_failure_time_s=12.0,
            step=StepKind.SCENE,
            encounters=encounters,
            encounter_roles=roles,
        )
    )
    (row,) = stores.cases.list_outputs(campaign.campaign_id, StepKind.SCENE)
    assert (row.first_failure_time_s, row.encounters, row.encounter_roles) == (12.0, encounters, roles)


def test_outputs_carry_the_input_source(stores, campaign):
    source = {"file": "head_on.json"}
    stores.cases.create_cases(campaign.campaign_id, [NewCase(class_id=CLASS_A, case_index=0, seed=1, stage=PipelineStage.GENERATE_TRAJECTORIES, input_artifact=sha256_of("x"), input_source=source)])
    (row,) = stores.cases.list_outputs(campaign.campaign_id, StepKind.TRAJECTORIES)
    assert row.input_source == source


def test_count_outputs_takes_the_filters_of_list_outputs(stores, step_outputs):
    campaign_id = step_outputs.campaign_id
    for step in StepKind:
        for keywords in ({}, {"states": [CaseState.DROPPED]}, {"states": [CaseState.COMPLETE, CaseState.ACTIVE]}, {"class_id": CLASS_A}, {"class_id": CLASS_B, "states": [CaseState.DROPPED]}):
            assert stores.cases.count_outputs(campaign_id, step, **keywords) == len(stores.cases.list_outputs(campaign_id, step, **keywords)), (step, keywords)
    assert [stores.cases.count_outputs(campaign_id, step) for step in StepKind] == [4, 2, 3]
    assert [output.case_id for output in stores.cases.list_outputs(campaign_id, StepKind.SCENE, limit=2, offset=1)] == [step_outputs.a1.case_id, step_outputs.a2.case_id]
