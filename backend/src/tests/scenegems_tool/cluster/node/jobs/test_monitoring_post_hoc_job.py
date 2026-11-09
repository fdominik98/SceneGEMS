"""monitoring.post_hoc in process: the result shape the pipeline reads, frames on request, and a scene judged as a one-scene log."""

import math

import pytest
from pydantic import ValidationError

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.cluster.node.job_report import JobFailed
from scenegems_tool.cluster.node.jobs import monitoring_post_hoc_job
from scenegems_tool.cluster.node.jobs.job_payload import validate_structure
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.vessel_stack.calibration.reference_scenarios import make_vessel


def _quiet(message, progress=None):
    pass


def test_the_result_summarizes_the_rules(make_job, head_on_trajectories):
    result = monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, {"trajectories": head_on_trajectories.to_dict()}), _quiet)
    assert set(result) == {"scenes", "monitored_scenes", "time_step", "rules", "failed_rules", "encounters", "encounter_roles", "passed"}
    assert (result["scenes"], result["monitored_scenes"], result["time_step"]) == (121, 121, 1)
    assert not result["passed"]
    assert {(item["rule"], item["first_failed_at"]) for item in result["failed_rules"]} == {
        ("Rule 16: Give-Way Vessel Takes Early and Substantial Action (os)", 61),
        ("Rule 16: Give-Way Vessel Takes Early and Substantial Action (ts1)", 61),
    }
    for item in result["failed_rules"]:
        assert result["rules"][item["relation"]][item["rule"]]["failed"] == item["first_failed_at"]
    assert result["encounters"] == {"os - ts1": ["HEAD_ON"]}  # keyed like rules
    assert result["encounter_roles"] == {"os - ts1": {"HEAD_ON": {"give_way": ["os", "ts1"], "stand_on": []}}}


def test_frames_are_added_on_request(make_job, head_on_trajectories):
    result = monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, {"trajectories": head_on_trajectories.to_dict(), "include_frames": True, "scenario_id": "case-1"}), _quiet)
    assert len(result["frames"]) == result["monitored_scenes"]


def test_an_unresolved_state_log_fails_for_good(make_job):
    job = make_job(JobType.MONITORING_POST_HOC, {"trajectories": {"sha256": "ab" * 32, "size_bytes": 1, "kind": "trajectories"}})
    with pytest.raises(JobFailed) as failure:
        monitoring_post_hoc_job.execute(job, _quiet)
    assert not failure.value.retryable


def _scene(head_on_trajectories):
    return head_on_trajectories.scene_list[0].to_dict()


@pytest.mark.parametrize("document", ["evaluation_data", "scene", "initial_scene"])
def test_a_scene_is_judged_as_a_one_scene_log(make_job, head_on_trajectories, document):
    scene = _scene(head_on_trajectories)
    payload = {"scene": {"best_scene": scene, "random_seed": 3} if document == "evaluation_data" else (scene if document == "scene" else {"initial_scene": scene})}
    result = monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, payload), _quiet)
    assert set(result) == {"scenes", "monitored_scenes", "time_step", "rules", "failed_rules", "encounters", "encounter_roles", "passed"}
    assert (result["scenes"], result["monitored_scenes"], result["time_step"]) == (1, 1, 1)
    # the pair is 3 km apart: the rules on the motion stay unknown and SafeDistance holds, so nothing fails
    assert result["passed"] and result["failed_rules"] == [] and isinstance(result["rules"], dict)
    assert result["encounters"] == {"os - ts1": ["HEAD_ON"]}  # the scene's type per pair
    assert result["encounter_roles"] == {"os - ts1": {"HEAD_ON": {"give_way": ["os", "ts1"], "stand_on": []}}}  # known without any decided rule


def _scene_at(distance):
    """The head-on pair of head_on_trajectories, `distance` apart (safety radius 120 m)."""
    scene = ConcreteScene({make_vessel(0, True): ActorState(0.0, 0.0, 8.0, 0.0), make_vessel(1, False): ActorState(distance, 0.0, 8.0, math.pi)})
    return scene.to_dict()


def test_a_scene_starting_inside_the_safe_distance_fails_at_0(make_job):
    result = monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, {"scene": _scene_at(80.0)}), _quiet)
    assert not result["passed"]
    assert result["failed_rules"] == [{"relation": "os - ts1", "rule": "Rule 8: Passing at a Safe Distance (os - ts1)", "first_failed_at": 0}]
    assert result["encounters"] == {"os - ts1": ["OTHER"]}  # inside its encounter's own domain a pair is OTHER
    assert result["encounter_roles"] == {}


def test_the_roles_come_from_the_encounter_not_from_the_order_of_the_relation(make_job):
    """The target ship has the own ship on its starboard bow, so it gives way, though the relation names the own ship first."""
    scene = ConcreteScene({make_vessel(0, True): ActorState(0.0, 0.0, 8.0, 0.0), make_vessel(1, False): ActorState(1500.0, 1500.0, 8.0, -math.pi / 2)}).to_dict()
    result = monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, {"scene": scene}), _quiet)
    assert result["encounters"] == {"os - ts1": ["CROSSING_FROM_PORT"]}
    assert result["encounter_roles"] == {"os - ts1": {"CROSSING_FROM_PORT": {"give_way": ["ts1"], "stand_on": ["os"]}}}


def test_a_scene_inside_the_head_on_domain_but_outside_the_circle_passes(make_job):
    """The safety domain guard: inside its encounter's domain the pair is OTHER, and SafeDistance judges the default circle."""
    result = monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, {"scene": _scene_at(200.0)}), _quiet)
    assert result["passed"] and result["failed_rules"] == []
    assert result["encounters"] == {"os - ts1": ["OTHER"]}


def test_a_scene_gets_its_frame_on_request(make_job, head_on_trajectories):
    payload = {"scene": _scene(head_on_trajectories), "include_frames": True, "scenario_id": "case-1#scene"}
    result = monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, payload), _quiet)
    assert len(result["frames"]) == result["monitored_scenes"] == 1


@pytest.mark.parametrize("payload", [{}, {"trajectories": "both", "scene": "both"}])
def test_exactly_one_of_trajectories_and_scene(head_on_trajectories, payload):
    if payload:
        payload = {"trajectories": head_on_trajectories.to_dict(), "scene": _scene(head_on_trajectories)}
    with pytest.raises(ValidationError, match="exactly one of trajectories and scene"):
        validate_structure(monitoring_post_hoc_job.PostHocMonitoringPayload, payload)


def test_a_scene_reference_is_checked_for_shape_and_must_be_resolved(make_job):
    reference = {"sha256": "cd" * 32, "size_bytes": 1, "kind": "scene"}
    validate_structure(monitoring_post_hoc_job.PostHocMonitoringPayload, {"scene": reference})
    with pytest.raises(JobFailed) as failure:
        monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, {"scene": reference}), _quiet)
    assert not failure.value.retryable


def test_a_document_without_a_scene_fails_for_good(make_job):
    with pytest.raises(JobFailed, match="holds no scene") as failure:
        monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, {"scene": {"random_seed": 3}}), _quiet)
    assert not failure.value.retryable
