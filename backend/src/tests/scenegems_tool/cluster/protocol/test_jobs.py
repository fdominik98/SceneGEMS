import pytest
from pydantic import ValidationError

from scenegems_tool.cluster.protocol.jobs import JobRequirements, JobState, JobSubmission, JobType


def test_job_type_wire_values_are_stable():
    # stored in the database and sent on the wire: renaming one is a protocol change
    assert {job_type.value for job_type in JobType} == {
        "scene_generation",
        "trajectory_generation",
        "simulation",
        "monitoring.post_hoc",
        "calibration.deviation",
    }


@pytest.mark.parametrize("state", [JobState.SUCCEEDED, JobState.FAILED, JobState.CANCELLED])
def test_terminal_states(state):
    assert state.is_terminal


@pytest.mark.parametrize("state", [JobState.QUEUED, JobState.LEASED, JobState.RUNNING])
def test_open_states(state):
    assert not state.is_terminal


def test_submission_defaults():
    submission = JobSubmission(job_type=JobType.SCENE_GENERATION)
    assert submission.payload == {}
    assert submission.requirements == JobRequirements()
    assert submission.priority == 0
    assert submission.max_attempts == 3
    assert submission.idempotency_key is None


def test_submission_needs_at_least_one_attempt():
    with pytest.raises(ValidationError):
        JobSubmission(job_type=JobType.SCENE_GENERATION, max_attempts=0)


def test_unknown_job_type_is_rejected():
    with pytest.raises(ValidationError):
        JobSubmission(job_type="simulation.unknown")


def test_requirements_reject_negative_resources():
    with pytest.raises(ValidationError):
        JobRequirements(min_memory_mb=-1)
