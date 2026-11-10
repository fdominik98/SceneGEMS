import threading

import numpy

from scenegems_tool.cluster.protocol.jobs import JobOutcome
from scenegems_tool.cluster.worker_node.daemon.leases.lease import Lease
from scenegems_tool.cluster.worker_node.daemon.leases.lease_worker import execute_lease, start_lease_worker
from scenegems_tool.cluster.worker_node.daemon.leases.report_batcher import ReportBatcher
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from tests.scenegems_tool.cluster.worker_node.daemon.conftest import make_job


def lease() -> Lease:
    return Lease("lease-1", make_job("job-1"), 0.0)


def report() -> ReportBatcher:
    return ReportBatcher("lease-1", "job-1")


def test_the_job_gets_its_spec_the_worker_node_the_report_and_the_cancel_event():
    current, batcher, worker_node = lease(), report(), object()
    seen = {}

    def run(job, given_worker_node, given_report, cancel):
        seen.update(job=job, worker_node=given_worker_node, report=given_report, cancel=cancel)
        return {"answer": 42}

    result = execute_lease(current, run, worker_node, batcher)
    assert seen == {"job": current.job, "worker_node": worker_node, "report": batcher, "cancel": current.cancel}
    assert result.outcome == JobOutcome.SUCCEEDED and result.result == {"answer": 42}
    assert (result.lease_id, result.job_id, result.idempotency_key) == ("lease-1", "job-1", "job-1/key")


def test_job_failed_keeps_its_retryable_flag():
    def run(*_):
        raise JobFailed("payload invalid", retryable=False)

    result = execute_lease(lease(), run, object(), report())
    assert result.outcome == JobOutcome.FAILED and result.error == "payload invalid" and result.retryable is False


def test_any_other_exception_may_be_retried():
    def run(*_):
        raise KeyError("missing")

    result = execute_lease(lease(), run, object(), report())
    assert result.outcome == JobOutcome.FAILED and result.retryable is True and "KeyError" in result.error


def test_a_result_that_cannot_be_encoded_fails_for_good():
    result = execute_lease(lease(), lambda *_: {"value": numpy.zeros(2)}, object(), report())
    assert result.outcome == JobOutcome.FAILED and result.retryable is False and "cannot be sent" in result.error


def test_the_worker_thread_hands_the_result_back():
    done = threading.Event()
    received = []

    def stopped(current, result):
        received.append((current.lease_id, result.outcome))
        done.set()

    start_lease_worker(lease(), lambda *_: {}, object(), report(), stopped)
    assert done.wait(5)
    assert received == [("lease-1", JobOutcome.SUCCEEDED)]
