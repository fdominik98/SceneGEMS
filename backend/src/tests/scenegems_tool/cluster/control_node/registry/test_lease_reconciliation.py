from datetime import datetime, timezone

from scenegems_tool.cluster.control_node.registry.lease_reconciliation import reconcile_leases
from scenegems_tool.cluster.protocol.jobs import JobSpec, JobState, JobType
from scenegems_tool.persistence.stores import Lease

EXPIRES = datetime(2026, 10, 25, 12, 0, 30, tzinfo=timezone.utc)


def _lease(lease_id: str, state: JobState) -> Lease:
    job = JobSpec(job_id=f"job-{lease_id}", job_type=JobType.SCENE_GENERATION, attempt=1, idempotency_key=f"key-{lease_id}")
    return Lease(lease_id=lease_id, worker_node_id="worker-node-a", state=state, expires_at=EXPIRES, job=job)


def _ids(leases):
    return [lease.lease_id for lease in leases]


def test_each_case_of_the_table():
    active = [_lease("running-reported", JobState.RUNNING), _lease("offered-reported", JobState.LEASED), _lease("offered-silent", JobState.LEASED), _lease("running-silent", JobState.RUNNING)]
    plan = reconcile_leases(["running-reported", "offered-reported", "unknown"], active)
    assert _ids(plan.keep) == ["running-reported"]
    assert _ids(plan.accept) == ["offered-reported"]
    assert _ids(plan.withdraw) == ["offered-silent"]
    assert _ids(plan.fail) == ["running-silent"]
    assert plan.cancel == ["unknown"]


def test_nothing_on_either_side():
    plan = reconcile_leases([], [])
    assert (plan.keep, plan.accept, plan.withdraw, plan.fail, plan.cancel) == ([], [], [], [], [])


def test_a_lease_reported_twice_counts_once():
    plan = reconcile_leases(["gone", "gone"], [])
    assert plan.cancel == ["gone"]
