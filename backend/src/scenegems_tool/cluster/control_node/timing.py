"""How often the control node and its worker nodes talk, and how long a silent worker node or lease is trusted.

The values follow from one requirement: a worker node lost in the middle of a job must have its
jobs requeued within about half a minute (exit criterion 2 of Phase 3), while a busy worker node
on a slow network must not lose its leases by accident.

    heartbeat every 5 s          a worker node is offline after 15 s of silence, three missed beats
    lease of 30 s                the worker node renews every 10 s, so two renewals may get lost
    offer of 10 s                accepting is immediate; a lost offer is back in the queue soon
    expiry sweep every 2 s       an expired lease is requeued at most 2 s after its expiry
    silence sweep every 5 s      offline detection takes 15 to 20 s
    scheduling at least every 1 s, and at once after anything that may free or add work
    pipeline tick every 2 s      the campaign engine (assurance/pipeline); at once again while it catches up
    stalled after 60 s           a campaign whose needed job type no worker node runs (with its pinned fingerprints)

So a worker node that dies right after renewing has its jobs back in the queue after at most
32 s, and offered to another worker node about a second later. A lease is dead at its expiry
instant whatever the sweep does (persistence/stores/job_lifecycle.py), so the sweep
period changes only how soon a job is requeued, never whether two worker nodes hold it.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ControlTiming:
    heartbeat_interval_s: float = 5.0  # sent to the worker node in Welcome
    worker_node_offline_after_s: float = 15.0
    lease_timeout_s: float = 30.0  # sent to the worker node in Welcome; every accept and renewal extends a running lease by this much
    offer_timeout_s: float = 10.0  # an unaccepted offer expires after this
    expiry_sweep_interval_s: float = 2.0
    offline_sweep_interval_s: float = 5.0
    schedule_interval_s: float = 1.0
    hello_timeout_s: float = 10.0  # the worker node must send Hello this soon after the socket opens
    pipeline_tick_interval_s: float = 2.0  # the pipeline engine's tick while it has nothing to catch up on
    campaign_stall_after_s: float = 60.0  # a campaign is stalled after this long without a worker node for a job type it needs

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            if value <= 0:
                raise ValueError(f"{name} must be positive, got {value}")
        if self.worker_node_offline_after_s < 2 * self.heartbeat_interval_s:
            raise ValueError("a worker node must be allowed to miss at least one heartbeat before it is offline")

    @property
    def renew_interval_s(self) -> float:
        """How often a worker node renews a running lease: a third of the lease, as the worker node daemon derives it from Welcome."""
        return self.lease_timeout_s / 3.0
