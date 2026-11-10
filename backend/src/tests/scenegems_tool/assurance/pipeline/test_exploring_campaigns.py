"""Campaigns that start with the design space exploration, on Postgres with a fake fleet: the FECs the exploration finds become the campaign's classes."""

from collections import Counter

import pytest

from scenegems_tool.assurance.campaign import campaign_config_from_dict, validate_campaign_config
from scenegems_tool.assurance.pipeline.case_machine import NO_LATER_STEP
from scenegems_tool.assurance.pipeline.pipeline_engine import WorkerNodeAvailability
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.persistence.schema import ArtifactHolderKind, CampaignActualState, CampaignClassState, CampaignEventKind, CampaignKind, CampaignOrigin, CaseState, PipelineStage
from scenegems_tool.persistence.stores import EXPLORATION_CLASS_ID
from scenegems_tool.subsystems.design_space_exploration.design_space import exploration_hash
from tests.scenegems_tool.assurance.pipeline.checks import assert_consistent
from tests.scenegems_tool.assurance.pipeline.fake_executor import DEFAULT_EXPLORED, CaseScript, fec_text

pytestmark = pytest.mark.postgres

EXPLORE, SCENE, TRAJECTORIES, SIMULATE, MONITOR = (
    PipelineStage.EXPLORE_DESIGN_SPACE,
    PipelineStage.GENERATE_SCENE,
    PipelineStage.GENERATE_TRAJECTORIES,
    PipelineStage.SIMULATE,
    PipelineStage.MONITOR,
)
SPECIFICATION = "class Vessel.\nclass OS extends Vessel.\nclass TS extends Vessel.\ndeclare os.\nOS(os).\n"
SCOPE = "TS = 1..2, StaticObstacle = 0..1"
FULL_CHAIN = ["design_space_exploration", "scene_generation", "trajectory_generation", "simulation"]
EXPLORED = ["explored/00000", "explored/00001", "explored/00002"]
EXPLORATION = (EXPLORATION_CLASS_ID, 0)


def exploring_dict(steps, **section):
    return {
        "format": 3,
        "name": "exploring campaign",
        "steps": list(steps),
        "design_space_exploration": {"specification": SPECIFICATION, "scope": SCOPE, **section},
        "trajectories": {"generator": "straight", "timespan_s": 10},
        "execution": {"runs": [{"monitor": "post_hoc"}]},
        "policy": {"seed": 7},
    }


def _create(harness, config, kind: CampaignKind = CampaignKind.CAMPAIGN, origin=None):
    validated = validate_campaign_config(campaign_config_from_dict(config))
    return harness.stores.campaigns.create_campaign(validated.config.name, validated.config_json, validated.config_hash, validated.classes, kind=kind, origin=origin, desired_state=_running())


def _running():
    from scenegems_tool.persistence.schema import CampaignDesiredState

    return CampaignDesiredState.RUNNING


def _classes(harness, campaign):
    return {record.class_id: record for record in harness.stores.cases.list_classes(campaign.campaign_id)}


def _cases(harness, campaign, class_id=None):
    return harness.stores.cases.list_cases(campaign.campaign_id, class_id)


def _stages(harness, case):
    return Counter(pipeline_job.stage for pipeline_job in harness.stores.pipeline.pipeline_jobs_of_case(case.case_id))


def _explored_note(harness, campaign):
    notes = [event.detail["explored"] for event in harness.stores.campaigns.list_events(campaign.campaign_id) if event.kind == CampaignEventKind.NOTE and "explored" in (event.detail or {})]
    assert len(notes) == 1
    return notes[0]


def test_a_new_exploring_campaign_has_the_exploration_class_alone(make_harness):
    harness = make_harness(references=True)
    campaign = _create(harness, exploring_dict(FULL_CHAIN))
    (record,) = _classes(harness, campaign).values()
    assert (record.class_id, record.quota, record.failure_budget, record.vessel_count, record.obstacle_count) == (EXPLORATION_CLASS_ID, 1, 0, 0, 0)
    assert record.content_hash == exploration_hash(SPECIFICATION, SCOPE)


def test_the_fecs_an_exploration_finds_run_through_the_rest_of_the_chain(make_harness):
    harness = make_harness(references=True)
    campaign = _create(harness, exploring_dict(FULL_CHAIN, quota=2, failure_budget=1, max_fecs=50, timeout_s=120))
    campaign_id = campaign.campaign_id

    # The first tick starts the exploration case and nothing else
    harness.settle()
    (exploration,) = _cases(harness, campaign)
    assert (exploration.class_id, exploration.case_index, exploration.stage, exploration.seed) == (EXPLORATION_CLASS_ID, 0, EXPLORE, 7)
    (job,) = [harness.job_store.get(pipeline_job.job_id) for pipeline_job in harness.stores.pipeline.pipeline_jobs_of_case(exploration.case_id)]
    assert job.job_type == JobType.DESIGN_SPACE_EXPLORATION
    assert job.payload == {"problem": SPECIFICATION, "scopes": ["TS=1..2", "StaticObstacle=0..1"], "random_seed": 7, "timeout_s": 120.0, "max_models": 50}
    assert job.requirements.components == ["design_space_exploration"]

    assert harness.drive(campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign_id) == {"complete": 1 + 3 * 2}
    classes = _classes(harness, campaign)
    assert sorted(classes) == [EXPLORATION_CLASS_ID, *EXPLORED]
    assert all(record.state == CampaignClassState.COMPLETE for record in classes.values())
    assert [(classes[class_id].vessel_count, classes[class_id].obstacle_count, classes[class_id].quota, classes[class_id].failure_budget) for class_id in EXPLORED] == [
        (2, 0, 2, 1),
        (2, 0, 2, 1),
        (3, 1, 2, 1),
    ]

    # Every explored FEC is pinned by its functional scenario artifact, which the exploration case holds
    documents = harness.executor.artifacts.documents
    assert [documents[classes[class_id].content_hash].decode("utf-8") for class_id in EXPLORED] == DEFAULT_EXPLORED
    exploration = harness.stores.cases.get_case(exploration.case_id)
    assert (exploration.state, exploration.stage) == (CaseState.COMPLETE, PipelineStage.VERDICT)
    held = sorted(reference.role for reference in harness.stores.artifacts.references_of(ArtifactHolderKind.CASE, str(exploration.case_id)))
    assert held == ["functional_scenarios:0", "functional_scenarios:1", "functional_scenarios:2"]
    assert harness.stores.artifacts.references_of(ArtifactHolderKind.JOB, job.job_id) == []

    # The cases of an explored FEC start at scene generation from that artifact and name the exploration as their source
    for class_id in EXPLORED:
        cases = _cases(harness, campaign, class_id)
        assert [case.case_index for case in cases] == [0, 1] and [case.seed for case in cases] == [7, 8]
        for case in cases:
            assert case.input_artifact == classes[class_id].content_hash
            assert case.input_source == {"campaign_id": campaign_id, "case_id": exploration.case_id, "step": "design_space_exploration"}
            assert _stages(harness, case) == {SCENE: 1, TRAJECTORIES: 1, SIMULATE: 1, MONITOR: 1}
            assert case.scene_artifact and case.trajectories_artifact
    assert len(harness.stores.results.list_verdicts(campaign_id, limit=None)) == 6
    assert _explored_note(harness, campaign) == {"fecs": 3, "stop_reason": "exhausted", "complete": True, "outcome": "every FEC of the design space"}

    # The exploration's outputs are the FECs it found
    outputs = harness.stores.cases.list_explored(campaign_id)
    assert harness.stores.cases.count_explored(campaign_id) == 3
    assert [(output.class_id, output.case_index, output.case_id, output.vessel_count, output.obstacle_count) for output in outputs] == [
        ("explored/00000", 0, exploration.case_id, 2, 0),
        ("explored/00001", 1, exploration.case_id, 2, 0),
        ("explored/00002", 2, exploration.case_id, 3, 1),
    ]
    assert all(output.valid and output.step is None and output.state == CaseState.COMPLETE for output in outputs)
    first = outputs[0].artifact
    assert (first.sha256, first.size_bytes, first.kind, first.media_type, first.pointer) == (
        classes["explored/00000"].content_hash,
        len(DEFAULT_EXPLORED[0]),
        "functional_scenario",
        "text/plain; charset=utf-8",
        None,
    )
    assert [output.class_id for output in harness.stores.cases.list_explored(campaign_id, limit=1, offset=1)] == ["explored/00001"]


def test_a_campaign_that_only_explores_ends_with_its_fecs_complete_and_no_case_of_them(make_harness):
    harness = make_harness(references=True, scripts={EXPLORATION: CaseScript(stop_reason="cap_reached")})
    campaign = _create(harness, exploring_dict(["design_space_exploration"], max_fecs=3), kind=CampaignKind.WORKBENCH, origin=CampaignOrigin.DESIGN_SPACE_EXPLORATION)
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 1}
    classes = _classes(harness, campaign)
    assert sorted(classes) == [EXPLORATION_CLASS_ID, *EXPLORED]
    for class_id in EXPLORED:
        assert (classes[class_id].state, classes[class_id].state_reason, classes[class_id].finished_at is not None) == (CampaignClassState.COMPLETE, NO_LATER_STEP, True)
    (exploration,) = _cases(harness, campaign)
    assert _stages(harness, exploration) == {EXPLORE: 1}
    assert harness.stores.cases.count_explored(campaign.campaign_id) == 3
    assert _explored_note(harness, campaign) == {"fecs": 3, "stop_reason": "cap_reached", "complete": False, "outcome": "the cap was reached, there may be more"}
    assert harness.stores.results.list_verdicts(campaign.campaign_id, limit=None) == []


def test_an_exploration_that_finds_no_fec_drops_its_case_and_ends_the_campaign(make_harness):
    harness = make_harness(references=True, scripts={EXPLORATION: CaseScript(explored=[], stop_reason="unsatisfiable")})
    campaign = _create(harness, exploring_dict(FULL_CHAIN))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"dropped": 1}
    (record,) = _classes(harness, campaign).values()
    assert (record.class_id, record.state) == (EXPLORATION_CLASS_ID, CampaignClassState.ABANDONED)
    (exploration,) = _cases(harness, campaign)
    assert exploration.reason == "the exploration found no FEC (the specification has no model): the partial model is inconsistent"
    assert harness.stores.cases.list_explored(campaign.campaign_id) == [] and harness.stores.cases.count_explored(campaign.campaign_id) == 0


def test_an_exploration_that_fails_ends_the_campaign_without_fecs(make_harness):
    harness = make_harness(references=True, scripts={EXPLORATION: CaseScript(fail=EXPLORE)})
    campaign = _create(harness, exploring_dict(FULL_CHAIN))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"failed": 1}
    (record,) = _classes(harness, campaign).values()
    assert record.state == CampaignClassState.ABANDONED
    (exploration,) = _cases(harness, campaign)
    assert "explore_design_space job" in exploration.reason and "scripted failure" in exploration.reason


def test_an_exploration_whose_fecs_were_not_stored_as_artifacts_fails_its_case(make_harness):
    harness = make_harness(references=False)  # a worker node without artifact transport returns the texts inline
    campaign = _create(harness, exploring_dict(FULL_CHAIN))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    (exploration,) = _cases(harness, campaign)
    assert exploration.state == CaseState.FAILED and "were not stored as artifacts" in exploration.reason
    assert sorted(_classes(harness, campaign)) == [EXPLORATION_CLASS_ID]


def test_a_fec_without_a_vessel_fails_the_exploration_case_and_adds_no_class(make_harness):
    harness = make_harness(references=True, scripts={EXPLORATION: CaseScript(explored=[fec_text(0), "// nothing declared\n"])})
    campaign = _create(harness, exploring_dict(FULL_CHAIN))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    (exploration,) = _cases(harness, campaign)
    assert exploration.state == CaseState.FAILED and "FEC 1 of the exploration declares no vessel" in exploration.reason
    assert sorted(_classes(harness, campaign)) == [EXPLORATION_CLASS_ID]


def test_a_dropped_case_of_an_explored_fec_is_replaced_within_the_configured_failure_budget(make_harness):
    scripts = {("explored/00000", 0): CaseScript(scene_valid=False), ("explored/00001", 0): CaseScript(scene_valid=False), ("explored/00001", 1): CaseScript(scene_valid=False)}
    harness = make_harness(references=True, scripts=scripts)
    campaign = _create(harness, exploring_dict(["design_space_exploration", "scene_generation"], quota=1, failure_budget=1))
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 3, "dropped": 3}
    classes = _classes(harness, campaign)
    assert (classes["explored/00000"].state, classes["explored/00001"].state, classes["explored/00002"].state) == (
        CampaignClassState.COMPLETE,
        CampaignClassState.ABANDONED,
        CampaignClassState.COMPLETE,
    )
    assert [case.state for case in _cases(harness, campaign, "explored/00000")] == [CaseState.DROPPED, CaseState.COMPLETE]


def test_an_exploring_campaign_stalls_while_no_worker_node_explores(make_harness):
    harness = make_harness(references=True)
    slots = {job_type: 1 for job_type in JobType if job_type != JobType.DESIGN_SPACE_EXPLORATION}
    other = harness.worker_node_store.register(_hello("no-explorer", slots))
    harness.worker_nodes = [WorkerNodeAvailability(other)]
    campaign = _create(harness, exploring_dict(FULL_CHAIN))
    harness.settle()
    harness.clock.advance(31)
    harness.settle()
    stalled = harness.campaign(campaign.campaign_id)
    assert stalled.actual_state == CampaignActualState.STALLED and "design_space_exploration with design_space_exploration" in stalled.state_reason
    harness.worker_nodes = [WorkerNodeAvailability(harness.executor.worker_node)]
    assert harness.drive(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED


def test_a_restarted_engine_carries_on_with_the_explored_fecs(make_harness):
    harness = make_harness(references=True)
    campaign = _create(harness, exploring_dict(["design_space_exploration", "scene_generation"]))
    harness.settle()
    assert harness.executor.run() == 1  # the exploration
    harness.settle()
    assert len(_cases(harness, campaign)) == 1 + 3
    engine = harness.replace_engine()
    assert harness.drive(campaign.campaign_id, engine=engine).actual_state == CampaignActualState.COMPLETED
    assert assert_consistent(harness.stores, campaign.campaign_id) == {"complete": 4}
    for class_id in EXPLORED:
        (case,) = _cases(harness, campaign, class_id)
        assert case.input_artifact == _classes(harness, campaign)[class_id].content_hash


def _hello(worker_node_id: str, slots):
    from tests.scenegems_tool.assurance.pipeline.fake_executor import EXPECTED
    from tests.scenegems_tool.persistence.stores.builders import make_hello

    return make_hello(worker_node_id, slots=slots, fingerprints=EXPECTED)
