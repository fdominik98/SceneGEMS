"""The exploration in the stage graph and the payload builder: its stage and job, where cases start, and the payloads of the exploration and of an explored FEC's scene."""

import pytest

from scenegems_tool.assurance.campaign import campaign_config_from_dict
from scenegems_tool.assurance.campaign.campaign_config import CampaignStep
from scenegems_tool.assurance.pipeline.coverage_controller import Backpressure
from scenegems_tool.assurance.pipeline.payload_builder import PayloadBuilder, PayloadError
from scenegems_tool.assurance.pipeline.stage_graph import EXPLORATION_STEP, JOB_STAGES, STAGE_PRIORITY_OFFSET, StageGraph, stage_priority_offsets
from scenegems_tool.cluster.node.jobs.job_types import payload_components
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.persistence.schema import PipelineStage
from scenegems_tool.persistence.stores import EXPLORATION_CLASS_ID
from tests.scenegems_tool.assurance.pipeline.conftest import CLASS_A, config_dict
from tests.scenegems_tool.assurance.pipeline.fake_executor import EXPECTED

EXPLORE = PipelineStage.EXPLORE_DESIGN_SPACE
SPECIFICATION = "class OS.\nclass TS.\n"
FEC = {"sha256": "c" * 64, "size_bytes": 120, "kind": "functional_scenario", "media_type": "text/plain; charset=utf-8"}


def exploring(*later_steps, **section):
    config = {
        "format": 3,
        "name": "explore",
        "steps": ["design_space_exploration", *later_steps],
        "design_space_exploration": {"specification": SPECIFICATION, "scope": "TS = 1..2, StaticObstacle = 0", **section},
        "trajectories": {"generator": "straight", "timespan_s": 10},
        "policy": {"seed": 7},
    }
    return campaign_config_from_dict(config)


def test_the_exploration_step_runs_the_design_space_exploration_job_at_the_campaigns_priority():
    assert (EXPLORATION_STEP.name, EXPLORATION_STEP.job_type) == ("explore_design_space", JobType.DESIGN_SPACE_EXPLORATION)
    assert EXPLORATION_STEP.idempotency_key("c1", 3) == "campaign:c1:case:3:explore_design_space"
    assert EXPLORE in JOB_STAGES
    assert STAGE_PRIORITY_OFFSET[EXPLORE] == 0 and stage_priority_offsets(True, True)[EXPLORE] == 0
    # the offsets of the other stages are what they were before the exploration existed
    assert stage_priority_offsets()[PipelineStage.GENERATE_SCENE] == 0 and stage_priority_offsets()[PipelineStage.CALIBRATE] == 4


def test_the_exploration_case_starts_at_the_exploration_and_the_other_cases_at_the_next_step():
    graph = StageGraph(exploring("scene_generation", "trajectory_generation"))
    assert graph.explores and graph.first_step == CampaignStep.DESIGN_SPACE_EXPLORATION
    assert graph.case_steps == (CampaignStep.SCENE_GENERATION, CampaignStep.TRAJECTORY_GENERATION) and graph.first_case_step == CampaignStep.SCENE_GENERATION
    assert graph.first_stage(EXPLORATION_CLASS_ID) == EXPLORE
    assert graph.first_stage("explored/00000") == graph.first_stage() == PipelineStage.GENERATE_SCENE
    assert graph.stage_needs(EXPLORE) == [(JobType.DESIGN_SPACE_EXPLORATION, ("design_space_exploration",))]
    assert graph.runs == ()  # no simulation step


def test_a_campaign_that_only_explores_starts_no_other_case():
    graph = StageGraph(exploring())
    assert graph.case_steps == () and graph.first_case_step is None
    assert graph.first_stage(EXPLORATION_CLASS_ID) == EXPLORE and graph.first_stage("explored/00000") is None


def test_a_campaign_that_does_not_explore_is_unchanged():
    graph = StageGraph(campaign_config_from_dict(config_dict()))
    assert not graph.explores and graph.case_steps == graph.steps
    assert graph.first_stage() == graph.first_stage(CLASS_A) == PipelineStage.GENERATE_SCENE
    assert graph.first_stage(EXPLORATION_CLASS_ID) == PipelineStage.GENERATE_SCENE  # a class of that name means nothing here


def test_one_exploration_fits_and_nothing_starts_while_it_is_queued():
    caps = exploring("scene_generation").resources.queue_depth
    assert Backpressure(caps, {}, EXPLORE).room_for_new_cases() == 1
    assert Backpressure(caps, {EXPLORE: 1}, EXPLORE).room_for_new_cases() == 0
    assert Backpressure(caps, {EXPLORE: 1}, PipelineStage.GENERATE_SCENE).room_for_new_cases() == 0


def test_the_exploration_payload_is_the_specification_the_scope_entries_the_limits_and_the_seed():
    builder = PayloadBuilder(exploring("scene_generation", max_fecs=25, timeout_s=90))
    payload = builder.design_space_exploration(7)
    assert payload == {"problem": SPECIFICATION, "scopes": ["TS=1..2", "StaticObstacle=0"], "random_seed": 7, "timeout_s": 90.0, "max_models": 25}
    assert payload_components(JobType.DESIGN_SPACE_EXPLORATION, payload) == ("design_space_exploration",)
    submission = builder.submission(EXPLORATION_STEP, payload, "campaign:c1:case:1:explore_design_space", EXPECTED)
    assert (submission.job_type, submission.priority, submission.requirements.components) == (JobType.DESIGN_SPACE_EXPLORATION, 0, ["design_space_exploration"])
    assert list(submission.requirements.fingerprints.values()) == ["fp-exploration"]


def test_without_a_cap_the_exploration_payload_names_none():
    assert "max_models" not in PayloadBuilder(exploring(max_fecs=None)).design_space_exploration(1)


def test_a_campaign_without_the_section_has_no_exploration_payload():
    with pytest.raises(PayloadError, match="no design_space_exploration section"):
        PayloadBuilder(campaign_config_from_dict(config_dict())).design_space_exploration(1)


def test_the_scene_of_an_explored_fec_takes_its_functional_scenario_artifact():
    builder = PayloadBuilder(exploring("scene_generation"))
    payload = builder.scene_generation("explored/00003", FEC["sha256"], 9, FEC)
    assert payload["functional_scenario_content"] == FEC and payload["seed"] == 9
    assert payload_components(JobType.SCENE_GENERATION, payload) == ("scene_generation",)
    assert payload["functional_scenario_content"] is not FEC  # the payload has its own copy


@pytest.mark.parametrize("explored", [None, {**FEC, "sha256": "d" * 64}])
def test_an_explored_fec_without_its_pinned_artifact_has_no_scene_payload(explored):
    builder = PayloadBuilder(exploring("scene_generation"))
    with pytest.raises(PayloadError, match="explored/00003 has no functional scenario artifact"):
        builder.scene_generation("explored/00003", FEC["sha256"], 9, explored)
