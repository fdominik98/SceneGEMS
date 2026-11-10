"""After a reconnect: the leases a worker node says it still runs against the leases the store holds for it.

A worker node reconnects after a network outage or a control node restart. Its Hello lists the leases it
still runs; the store knows which leases of the worker node are active. Each side may know leases
the other lost:

    in the store       reported   action
    running            yes        keep: renew it, the job goes on
    offered            yes        accept it: the worker node accepted, the control node never saw it
    offered            no         withdraw the offer (no attempt used)
    running            no         fail the attempt (retryable): the worker node lost the job, a restart for example
    not active         yes        cancel: the lease expired or ended, the worker node must stop that job
"""

from dataclasses import dataclass, field
from typing import Iterable, List

from scenegems_tool.cluster.protocol.jobs import JobState
from scenegems_tool.persistence.stores import Lease


@dataclass(frozen=True)
class LeaseReconciliation:
    keep: List[Lease] = field(default_factory=list)
    accept: List[Lease] = field(default_factory=list)
    withdraw: List[Lease] = field(default_factory=list)
    fail: List[Lease] = field(default_factory=list)
    cancel: List[str] = field(default_factory=list)  # lease ids the store does not hold for this worker node


def reconcile_leases(reported_lease_ids: Iterable[str], active_leases: Iterable[Lease]) -> LeaseReconciliation:
    reported = list(dict.fromkeys(reported_lease_ids))
    active = {lease.lease_id: lease for lease in active_leases}
    plan = LeaseReconciliation()
    for lease in active.values():
        if lease.lease_id in reported:
            (plan.keep if lease.state == JobState.RUNNING else plan.accept).append(lease)
        else:
            (plan.fail if lease.state == JobState.RUNNING else plan.withdraw).append(lease)
    plan.cancel.extend(lease_id for lease_id in reported if lease_id not in active)
    return plan
