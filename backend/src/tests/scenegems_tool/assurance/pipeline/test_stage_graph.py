"""The stage graph: steps, keys, priorities, and a case's stage and readiness from its progress, for the full chain and partial campaigns."""

import pytest

from scenegems_tool.assurance.campaign import campaign_config_from_dict
from scenegems_tool.assurance.campaign.campaign_config import DEFAULT_STEPS, CampaignStep
from scenegems_tool.assurance.pipeline.stage_graph import (
    SCENE_MONITOR_STEP,
    SCENE_STEP,
    STAGE_PRIORITY_OFFSET,
    TRAJECTORIES_MONITOR_STEP,
    TRAJECTORIES_STEP,
    CaseProgress,
    StageGraph,
    Step,
    stage_priority_offsets,
)
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.persistence.schema import PipelineStage, StepKind
from tests.scenegems_tool.assurance.pipeline.conftest import config_dict, format2_dict

SIMULATE, MONITOR, CALIBRATE = PipelineStage.SIMULATE, PipelineStage.MONITOR, PipelineStage.CALIBRATE


def _graph(*runs) -> StageGraph:
    return StageGraph(campaign_config_from_dict(config_dict(runs=list(runs))))


def test_steps_name_their_stage_run_and_repeat():
    step = Step(SIMULATE, 1, 2)
    assert step.name == "simulate:1:2" and step.job_type == JobType.SIMULATION
    assert step.idempotency_key("c1", 42) == "campaign:c1:case:42:simulate:1:2"
    assert SCENE_STEP.idempotency_key("c1", 42) == "campaign:c1:case:42:generate_scene"
    assert Step(MONITOR, 0).name == "monitor:0" and Step(CALIBRATE, 3).job_type == JobType.CALIBRATION_DEVIATION
    with pytest.raises(ValueError):
        Step(SIMULATE, 0)
    with pytest.raises(ValueError):
        Step(PipelineStage.GENERATE_SCENE, 0)
    with pytest.raises(ValueError):
        Step(PipelineStage.VERDICT)


def test_later_stages_get_higher_priorities():
    priorities = [
        Step.of(stage, run, repeat).priority(10)
        for stage, run, repeat in [(PipelineStage.GENERATE_SCENE, None, None), (PipelineStage.GENERATE_TRAJECTORIES, None, None), (SIMULATE, 0, 0), (MONITOR, 0, None), (CALIBRATE, 0, None)]
    ]
    assert priorities == sorted(priorities) and priorities[0] == 10 and len(set(priorities)) == 5


def test_a_post_hoc_run_needs_a_monitor_job_and_its_verdict():
    graph = _graph({"monitor": "post_hoc"})
    progress = CaseProgress()
    assert graph.stage_of(progress) == PipelineStage.GENERATE_SCENE
    progress.mark(SCENE_STEP, "succeeded")
    progress.mark(TRAJECTORIES_STEP, "succeeded")
    assert graph.simulate_steps() == [Step(SIMULATE, 0, 0)]
    assert graph.stage_of(progress) == SIMULATE
    progress.mark(Step(SIMULATE, 0, 0), "succeeded")
    assert graph.steps_after_simulation(progress, 0, 0) == [Step(MONITOR, 0)]
    assert graph.stage_of(progress) == MONITOR and not graph.ready(progress)
    progress.mark(Step(MONITOR, 0), "succeeded")
    progress.run(0)["verdict"] = {"state": "passed"}
    assert graph.stage_of(progress) == PipelineStage.VERDICT and graph.ready(progress)


@pytest.mark.parametrize("monitor", ["live", "empty"])
def test_live_and_empty_monitors_run_no_monitor_job(monitor):
    graph = _graph({"monitor": monitor})
    progress = CaseProgress({"steps": {"generate_scene": "succeeded", "generate_trajectories": "succeeded", "simulate:0:0": "succeeded"}})
    assert graph.steps_after_simulation(progress, 0, 0) == []
    assert graph.stage_of(progress) == PipelineStage.VERDICT


def test_repeats_simulate_each_and_calibrate_once_all_are_in():
    graph = _graph({"monitor": "empty", "repeats": 3}, {"monitor": "post_hoc"})
    assert graph.simulate_steps() == [Step(SIMULATE, 0, 0), Step(SIMULATE, 0, 1), Step(SIMULATE, 0, 2), Step(SIMULATE, 1, 0)]
    progress = CaseProgress({"steps": {"generate_scene": "succeeded", "generate_trajectories": "succeeded"}})
    progress.mark(Step(SIMULATE, 0, 2), "succeeded")
    assert graph.steps_after_simulation(progress, 0, 2) == []
    progress.mark(Step(SIMULATE, 0, 0), "succeeded")
    progress.mark(Step(SIMULATE, 0, 1), "succeeded")
    assert graph.steps_after_simulation(progress, 0, 1) == [Step(CALIBRATE, 0)]
    progress.mark(Step(SIMULATE, 1, 0), "succeeded")
    progress.run(0)["verdict"] = {"state": "unmonitored"}
    assert graph.stage_of(progress) == MONITOR  # run 1's post-hoc monitor first
    progress.mark(Step(MONITOR, 1), "succeeded")
    progress.run(1)["verdict"] = {"state": "passed"}
    assert graph.stage_of(progress) == CALIBRATE and not graph.ready(progress)
    progress.mark(Step(CALIBRATE, 0), "succeeded")
    progress.run(0)["calibrated"] = True
    assert graph.ready(progress)


def test_progress_round_trips_through_json():
    progress = CaseProgress()
    progress.mark(SCENE_STEP, "succeeded")
    progress.set_run_record(0, 1, 17)
    progress.set_run_record(0, 0, 16)
    again = CaseProgress(progress.to_json())
    assert again.handled(SCENE_STEP) and again.run_record_id(0, 1) == 17 and sorted(again.run_record_ids()) == [16, 17]
    assert again.pending_verdict(0) is None


# Partial campaigns

STRAIGHT_MONITORED = {"generator": "straight", "timespan_s": 10, "monitor": "post_hoc"}
SCENE_POST_HOC = {"monitor": "post_hoc"}


def _format2(steps, **sections) -> StageGraph:
    return StageGraph(campaign_config_from_dict(format2_dict(steps, **sections)))


def test_a_format_1_graph_runs_the_full_chain_without_generation_monitors():
    graph = _graph({"monitor": "post_hoc"})
    assert graph.steps == DEFAULT_STEPS and graph.first_stage() == PipelineStage.GENERATE_SCENE and graph.monitored_steps() == []
    assert graph.priority_offsets == STAGE_PRIORITY_OFFSET and len(graph.runs) == 1
    progress = CaseProgress()
    progress.mark(SCENE_STEP, "succeeded")
    assert graph.stage_of(progress) == PipelineStage.GENERATE_TRAJECTORIES
    assert set(progress.to_json()) == {"steps", "runs"}  # no verdicts key: a format 1 case's progress keeps its shape


def test_the_generation_monitors_get_priorities_between_their_neighbours():
    graph = _format2(["scene_generation", "trajectory_generation", "simulation"], scene_generation=SCENE_POST_HOC, trajectories=STRAIGHT_MONITORED)
    chain = [PipelineStage.GENERATE_SCENE, PipelineStage.MONITOR_SCENE, PipelineStage.GENERATE_TRAJECTORIES, PipelineStage.MONITOR_TRAJECTORIES, SIMULATE, MONITOR, CALIBRATE]
    assert [graph.priority_offsets[stage] for stage in chain] == list(range(len(chain)))
    assert SCENE_MONITOR_STEP.priority(10, graph.priority_offsets) == 11 and TRAJECTORIES_MONITOR_STEP.priority(10, graph.priority_offsets) == 13
    assert stage_priority_offsets(scene_monitored=True)[PipelineStage.GENERATE_TRAJECTORIES] == 2
    assert stage_priority_offsets(trajectories_monitored=True)[PipelineStage.MONITOR_TRAJECTORIES] == 2
    with pytest.raises(KeyError):
        SCENE_MONITOR_STEP.priority(10)  # only with its graph's offsets
    assert SCENE_MONITOR_STEP.name == "monitor_scene" and SCENE_MONITOR_STEP.job_type == JobType.MONITORING_POST_HOC
    assert TRAJECTORIES_MONITOR_STEP.idempotency_key("c1", 4) == "campaign:c1:case:4:monitor_trajectories"


def test_a_monitored_scene_step_is_ready_with_its_scene_and_its_verdict():
    graph = _format2(["scene_generation"], scene_generation=SCENE_POST_HOC)
    assert graph.runs == () and graph.monitored_steps() == [StepKind.SCENE] and graph.is_last(CampaignStep.SCENE_GENERATION)
    progress = CaseProgress()
    assert graph.stage_of(progress) == PipelineStage.GENERATE_SCENE and not graph.ready(progress)
    progress.mark(SCENE_STEP, "succeeded")
    assert graph.stage_of(progress) == PipelineStage.MONITOR_SCENE and not graph.ready(progress)
    progress.mark(SCENE_MONITOR_STEP, "succeeded")
    progress.set_step_verdict(StepKind.SCENE, {"state": "passed"})
    assert graph.stage_of(progress) == PipelineStage.VERDICT and graph.ready(progress)
    again = CaseProgress(progress.to_json())
    assert again.step_verdict(StepKind.SCENE) == {"state": "passed"} and again.step_verdict(StepKind.TRAJECTORIES) is None


def test_an_unmonitored_last_step_is_ready_with_its_output():
    graph = _format2(["scene_generation"])
    progress = CaseProgress()
    progress.mark(SCENE_STEP, "succeeded")
    assert graph.monitored_steps() == [] and graph.stage_of(progress) == PipelineStage.VERDICT and graph.ready(progress)
    graph = _format2(["scene_generation", "trajectory_generation"])
    assert graph.stage_of(progress) == PipelineStage.GENERATE_TRAJECTORIES and not graph.ready(progress)
    progress.mark(TRAJECTORIES_STEP, "succeeded")
    assert graph.ready(progress) and graph.is_last(CampaignStep.TRAJECTORY_GENERATION)


def test_each_generation_step_waits_for_its_monitor():
    graph = _format2(["scene_generation", "trajectory_generation"], scene_generation=SCENE_POST_HOC, trajectories=STRAIGHT_MONITORED)
    assert graph.monitored_steps() == [StepKind.SCENE, StepKind.TRAJECTORIES]
    progress = CaseProgress()
    progress.mark(SCENE_STEP, "succeeded")
    progress.mark(TRAJECTORIES_STEP, "succeeded")  # the trajectories ran beside the scene's monitor
    assert graph.stage_of(progress) == PipelineStage.MONITOR_SCENE and not graph.ready(progress)
    progress.mark(SCENE_MONITOR_STEP, "succeeded")
    progress.set_step_verdict(StepKind.SCENE, {"state": "failed"})
    assert graph.stage_of(progress) == PipelineStage.MONITOR_TRAJECTORIES and not graph.ready(progress)
    progress.mark(TRAJECTORIES_MONITOR_STEP, "succeeded")
    progress.set_step_verdict(StepKind.TRAJECTORIES, {"state": "passed"})
    assert graph.stage_of(progress) == PipelineStage.VERDICT and graph.ready(progress)


def test_a_monitor_of_a_step_the_campaign_does_not_run_is_ignored():
    graph = _format2(["trajectory_generation", "simulation"], scene_generation=SCENE_POST_HOC)
    assert not graph.scene_monitored and graph.monitored_steps() == []


def test_later_starts_begin_at_their_first_step():
    graph = _format2(["trajectory_generation"], trajectories=STRAIGHT_MONITORED)
    assert graph.first_stage() == PipelineStage.GENERATE_TRAJECTORIES and graph.runs == ()
    assert graph.stage_of(CaseProgress()) == PipelineStage.GENERATE_TRAJECTORIES
    graph = _format2(["simulation"], runs=[{"monitor": "post_hoc"}])
    progress = CaseProgress()
    assert graph.first_stage() == SIMULATE and graph.stage_of(progress) == SIMULATE
    progress.mark(Step(SIMULATE, 0, 0), "recorded")
    assert graph.stage_of(progress) == MONITOR and not graph.ready(progress)
