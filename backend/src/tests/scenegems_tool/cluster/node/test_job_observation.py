"""A job's observation on the node: the master's request, the frame buffer and its batches, on a hand-driven clock."""

import threading

import pytest

from scenegems_tool.cluster.node.job_observation import OBSERVABLE_JOB_TYPES, JobObservation, JobObservations
from scenegems_tool.cluster.protocol.jobs import JobSpec, JobType


class Clock:
    def __init__(self) -> None:
        self.now = 50.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock():
    return Clock()


def job(job_type: JobType = JobType.SIMULATION, attempt: int = 1) -> JobSpec:
    return JobSpec(job_id="j1", job_type=job_type, attempt=attempt, idempotency_key="j1/key")


def frames(count: int, size: int = 10, start: int = 0):
    return [({"timestamp": index}, size) for index in range(start, start + count)]


def test_requests_count_revisions_and_repeat_requests_change_nothing(clock):
    observation = JobObservation("j1", 1, clock=clock)
    assert observation.control.revision == 0 and not observation.active
    assert not observation.request(False, 10.0)  # off while off
    assert observation.request(True, 10.0)
    assert not observation.request(True, 10.0)  # the master repeats it after a reconnect
    assert observation.request(True, 40.0)
    assert observation.request(False, 40.0)
    assert observation.control == observation.control.__class__(active=False, speed=40.0, revision=3)


def test_frames_are_kept_only_while_observed(clock):
    observation = JobObservation("j1", 1, clock=clock)
    observation.add_frames(frames(3))
    assert observation.take_batch() is None
    observation.request(True, 10.0)
    observation.add_frames(frames(3))
    observation.request(False, 10.0)  # what waits is dropped: nobody observes it any more
    assert observation.take_batch(force=True) is None


def test_batches_are_rated_and_bounded_by_count_and_bytes(clock):
    observation = JobObservation("j1", 1, clock=clock, min_interval_s=0.1, max_frames=4, max_bytes=100, max_buffered=10)
    observation.request(True, 10.0)
    observation.add_frames(frames(3, size=30) + frames(1, size=101, start=3) + frames(8, size=10, start=4))
    assert observation.dropped == 2  # the 101-byte frame, then the oldest when the buffer was full
    seq, batch = observation.take_batch()
    assert seq == 1 and [frame["timestamp"] for frame in batch] == [1, 2, 4, 5]  # 4 frames at most
    assert observation.take_batch() is None  # within 0.1 s of the last one
    assert observation.take_batch(force=True) == (2, [{"timestamp": index} for index in (6, 7, 8, 9)])
    clock.now += 0.1
    observation.add_frames(frames(3, size=45, start=20))
    seq, batch = observation.take_batch()
    assert seq == 3 and [frame["timestamp"] for frame in batch] == [10, 11, 20]  # 10 + 10 + 45 bytes; the next would pass 100


def test_observed_time_is_counted_for_the_timeout(clock):
    observation = JobObservation("j1", 1, clock=clock)
    clock.now += 5
    observation.request(True, 10.0)
    clock.now += 7
    assert observation.observed_seconds() == pytest.approx(7.0)
    observation.request(True, 20.0)
    clock.now += 3
    observation.request(False, 20.0)
    clock.now += 100
    observation.request(True, 20.0)
    clock.now += 2
    observation.close()
    clock.now += 50
    assert observation.observed_seconds() == pytest.approx(12.0)


def test_wait_for_change_returns_with_a_new_request_or_the_close(clock):
    observation = JobObservation("j1", 1, clock=clock)
    assert observation.wait_for_change(0, timeout_s=0.01).revision == 0
    threading.Timer(0.05, observation.request, args=(True, 15.0)).start()
    control = observation.wait_for_change(0, timeout_s=5.0)
    assert control.active and control.speed == 15.0 and control.revision == 1
    threading.Timer(0.05, observation.close).start()
    assert observation.wait_for_change(1, timeout_s=5.0).revision == 1 and observation.closed
    assert not observation.request(False, 15.0)  # a closed observation takes no requests


def test_only_simulations_are_observable(clock):
    observations = JobObservations(clock)
    assert set(OBSERVABLE_JOB_TYPES) == {JobType.SIMULATION}
    assert observations.open(job(JobType.MONITORING_POST_HOC)) is None
    assert observations.of(job(JobType.MONITORING_POST_HOC)) is None
    opened = observations.open(job())
    assert observations.open(job()) is opened and observations.get("j1", 1) is opened
    assert observations.get("j1", 2) is None
    assert observations.close(job()) is opened and opened.closed and len(observations) == 0
    assert observations.close(job()) is None
