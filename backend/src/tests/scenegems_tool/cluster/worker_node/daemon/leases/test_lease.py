import pytest

from scenegems_tool.cluster.protocol.jobs import JobOutcome
from scenegems_tool.cluster.protocol.messages import JobResult
from scenegems_tool.cluster.worker_node.daemon.leases.lease import Lease, LeasePhase, LeaseTransitionError
from tests.scenegems_tool.cluster.worker_node.daemon.conftest import make_job

TIMEOUT_S, RENEW_S = 9.0, 3.0


def lease(accepted_at: float = 100.0) -> Lease:
    return Lease("lease-1", make_job("job-1"), accepted_at)


def result() -> JobResult:
    return JobResult(lease_id="lease-1", job_id="job-1", idempotency_key="job-1/key", outcome=JobOutcome.SUCCEEDED)


def test_a_running_lease_finishes_then_ends_when_its_result_is_sent():
    current = lease()
    assert current.phase == LeasePhase.RUNNING and current.held and current.worker_running
    current.worker_stopped(result())
    assert current.phase == LeasePhase.FINISHED and current.held and not current.worker_running
    assert current.result is not None
    current.result_sent()
    assert current.phase == LeasePhase.ENDED and current.result is None and not current.held


def test_renewals_fall_due_at_the_interval_and_confirmations_keep_the_lease():
    current = lease(100.0)
    assert not current.renewal_due(102.9, RENEW_S)
    assert current.renewal_due(103.0, RENEW_S)
    current.renewal_sent(103.0)
    assert not current.renewal_due(105.0, RENEW_S)
    current.renewed(103.1)
    assert not current.is_overdue(112.0, TIMEOUT_S)
    assert current.is_overdue(112.2, TIMEOUT_S)


def test_a_late_confirmation_never_moves_the_lease_backwards():
    current = lease(100.0)
    current.renewed(105.0)
    current.renewed(104.0)
    assert current.confirmed_at == 105.0


def test_an_unconfirmed_lease_is_overdue_after_the_timeout_from_the_accept():
    current = lease(100.0)
    current.renewal_sent(103.0)
    current.renewal_sent(106.0)
    assert current.is_overdue(109.1, TIMEOUT_S)


def test_a_lost_lease_stops_its_job_and_ends_without_a_result():
    current = lease()
    current.lose("no renewal")
    assert current.phase == LeasePhase.LOST and current.cancel.is_set() and not current.held
    assert not current.renewal_due(1000.0, RENEW_S) and not current.is_overdue(1000.0, TIMEOUT_S)
    current.worker_stopped(result())
    assert current.phase == LeasePhase.ENDED and current.result is None and not current.release_pending


def test_a_cancelled_lease_ends_without_a_result():
    current = lease()
    current.cancel_by_control_node("stopped")
    assert current.phase == LeasePhase.CANCELLING and current.cancel.is_set() and current.stop_reason == "stopped"
    current.worker_stopped(result())
    assert current.phase == LeasePhase.ENDED and current.result is None


def test_a_cancel_after_the_job_finished_drops_the_unsent_result():
    current = lease()
    current.worker_stopped(result())
    current.cancel_by_control_node("stopped")
    assert current.phase == LeasePhase.ENDED and current.result is None


def test_a_released_lease_owes_the_control_node_a_release():
    current = lease()
    current.release("shutting down")
    assert current.phase == LeasePhase.RELEASING and current.held and current.cancel.is_set()
    current.worker_stopped(result())
    assert current.phase == LeasePhase.ENDED and current.release_pending and current.result is None


def test_a_finished_lease_keeps_its_result_when_released():
    current = lease()
    current.worker_stopped(result())
    current.release("shutting down")
    assert current.phase == LeasePhase.FINISHED and current.result is not None


def test_invalid_transitions_fail():
    current = lease()
    with pytest.raises(LeaseTransitionError):
        current.result_sent()
    current.worker_stopped(result())
    with pytest.raises(LeaseTransitionError):
        current.worker_stopped(result())
    with pytest.raises(LeaseTransitionError):
        current.lose("late")
