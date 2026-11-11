"""The pieces of a pool request every pool job shares: the wait with and without a deadline, the pool that stops heartbeating, and the progress relayed as status."""

import threading
from types import SimpleNamespace

import pytest

from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs import pool_client
from scenegems_tool.cluster.worker_node.jobs.pool_client import PoolLiveness, _FollowedRequest, wait_for_reply


class _Report:
    def __init__(self):
        self.statuses = []

    def status(self, *status):
        self.statuses.append(status)


def test_a_pool_that_is_silent_for_too_long_fails_the_attempt_which_may_be_retried():
    now = [0.0]
    client = SimpleNamespace(is_heartbeat_valid=True)
    liveness = PoolLiveness(client, "simulation pool", clock=lambda: now[0])
    liveness.check()
    client.is_heartbeat_valid = False
    liveness.check()  # silent from now
    now[0] = pool_client.HEARTBEAT_LOST_S
    liveness.check()  # not yet too long
    now[0] = pool_client.HEARTBEAT_LOST_S + 0.1
    with pytest.raises(JobFailed, match="The simulation pool stopped heartbeating: its tasks are lost") as failure:
        liveness.check()
    assert failure.value.retryable


def test_a_heartbeat_in_between_starts_the_count_again():
    now = [0.0]
    client = SimpleNamespace(is_heartbeat_valid=False)
    liveness = PoolLiveness(client, "monitoring pool", clock=lambda: now[0])
    liveness.check()
    now[0] = pool_client.HEARTBEAT_LOST_S - 1
    client.is_heartbeat_valid = True
    liveness.check()
    client.is_heartbeat_valid = False
    now[0] = pool_client.HEARTBEAT_LOST_S + 5
    liveness.check()  # silent again only since now
    now[0] += pool_client.HEARTBEAT_LOST_S - 1
    liveness.check()


def test_a_wait_without_a_deadline_ends_by_its_reply_or_by_its_check():
    replied = threading.Event()
    replied.set()
    wait_for_reply(replied, _Report(), "simulation result", None, None)  # no deadline: returns with the reply

    def lost():
        raise JobFailed("The simulation pool stopped heartbeating: its tasks are lost", retryable=True)

    with pytest.raises(JobFailed, match="stopped heartbeating"):
        wait_for_reply(threading.Event(), _Report(), "simulation result", None, None, lost)


def test_a_wait_with_a_deadline_and_a_cancelled_wait_end_as_before():
    with pytest.raises(JobFailed, match="No generated scene within 0 s") as failure:
        wait_for_reply(threading.Event(), _Report(), "generated scene", None, 0.0)
    assert failure.value.retryable
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(JobFailed, match="cancelled") as failure:
        wait_for_reply(threading.Event(), _Report(), "generated scene", cancel, None)
    assert not failure.value.retryable


@pytest.mark.parametrize("relay_detail, expected", [(False, ("running", 0.5)), (True, ("running", 0.5, {"phase": "running"}))])
def test_a_progress_message_is_the_jobs_status_with_its_detail_only_for_a_request_that_relays_it(relay_detail, expected):
    report = _Report()
    followed = _FollowedRequest("job-1-1", lambda stream, message: False, None, report, relay_detail)
    followed.on_feedback("job-1-1", {"message": "running", "progress": 0.5, "detail": {"phase": "running"}})
    followed.on_feedback("someone-else", {"message": "not ours", "progress": 0.1})
    followed.on_feedback("job-1-1", {"progress": 0.7})  # no message: nothing to say
    assert report.statuses == [expected]


def test_a_progress_message_without_a_detail_or_a_number_is_a_plain_status():
    report = _Report()
    followed = _FollowedRequest("job-1-1", lambda stream, message: False, None, report, True)
    followed.on_feedback("job-1-1", {"message": "loading", "progress": None, "detail": None})
    followed.on_feedback("job-1-1", {"message": "odd", "progress": "half", "detail": {}})
    assert report.statuses == [("loading", None), ("odd", None)]
