"""One accepted lease and its state machine.

    running ──worker stops──> finished ──result sent──> ended
       │ Cancel from the control node      ──> cancelling ──worker stops──> ended (no result)
       │ no LeaseRenewed in time     ──> lost       ──worker stops──> ended (no result)
       └ the worker node shuts down         ──> releasing  ──worker stops──> ended (LeaseRelease sent)

The worker node renews a running lease every `renew_every_s` and counts it lost when no
LeaseRenewed confirmed it for `lease_timeout_s`, measured on the worker node's monotonic clock
from the last confirmation (the accepted offer counts as one). The control node's lease has
expired by then, so a result would be refused as stale and the work is stopped instead.
Times are passed in, so the machine is tested without a clock.
"""

import threading
from enum import Enum
from typing import Optional

from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.messages import JobResult


class LeasePhase(str, Enum):
    RUNNING = "running"
    FINISHED = "finished"  # the outcome is ready and waits to be sent
    CANCELLING = "cancelling"
    LOST = "lost"
    RELEASING = "releasing"
    ENDED = "ended"


_STOPPING = (LeasePhase.CANCELLING, LeasePhase.LOST, LeasePhase.RELEASING)


class LeaseTransitionError(RuntimeError):
    pass


class Lease:
    def __init__(self, lease_id: str, job: JobSpec, accepted_at: float):
        self.lease_id = lease_id
        self.job = job
        self.phase = LeasePhase.RUNNING
        self.cancel = threading.Event()  # handed to run_job
        self.confirmed_at = accepted_at
        self.renewal_sent_at = accepted_at
        self.result: Optional[JobResult] = None
        self.release_pending = False  # a LeaseRelease waits to be sent
        self.stop_reason = ""

    @property
    def job_id(self) -> str:
        return self.job.job_id

    @property
    def held(self) -> bool:
        """The control node still counts this lease as the worker node's: reported in running_lease_ids."""
        return self.phase in (LeasePhase.RUNNING, LeasePhase.FINISHED, LeasePhase.RELEASING)

    @property
    def worker_running(self) -> bool:
        return self.phase == LeasePhase.RUNNING or self.phase in _STOPPING

    def renewal_due(self, now: float, renew_every_s: float) -> bool:
        return self.phase == LeasePhase.RUNNING and now - self.renewal_sent_at >= renew_every_s

    def renewal_sent(self, now: float) -> None:
        self.renewal_sent_at = now

    def renewed(self, now: float) -> None:
        if self.phase in (LeasePhase.RUNNING, LeasePhase.FINISHED):
            self.confirmed_at = max(self.confirmed_at, now)

    def is_overdue(self, now: float, lease_timeout_s: float) -> bool:
        return self.phase == LeasePhase.RUNNING and now - self.confirmed_at > lease_timeout_s

    def cancel_by_control_node(self, reason: str) -> None:
        if self.phase == LeasePhase.RUNNING:
            self._stop(LeasePhase.CANCELLING, reason)
        elif self.phase == LeasePhase.FINISHED:
            self.result = None  # the control node ended the lease; its result would be stale
            self.phase = LeasePhase.ENDED

    def lose(self, reason: str) -> None:
        if self.phase != LeasePhase.RUNNING:
            raise LeaseTransitionError(f"Lease {self.lease_id} is {self.phase.value}, only a running lease can be lost")
        self._stop(LeasePhase.LOST, reason)

    def release(self, reason: str) -> None:
        """Give the job back; a finished lease keeps its result instead, which is worth more to the control node."""
        if self.phase == LeasePhase.RUNNING:
            self._stop(LeasePhase.RELEASING, reason)

    def worker_stopped(self, result: JobResult) -> None:
        if self.phase == LeasePhase.RUNNING:
            self.result = result
            self.phase = LeasePhase.FINISHED
        elif self.phase == LeasePhase.RELEASING:
            self.release_pending = True
            self.phase = LeasePhase.ENDED
        elif self.phase in (LeasePhase.CANCELLING, LeasePhase.LOST):
            self.phase = LeasePhase.ENDED
        else:
            raise LeaseTransitionError(f"Lease {self.lease_id} is {self.phase.value}; its worker stopped already")

    def result_sent(self) -> None:
        if self.phase != LeasePhase.FINISHED:
            raise LeaseTransitionError(f"Lease {self.lease_id} is {self.phase.value}, it has no result to send")
        self.result = None
        self.phase = LeasePhase.ENDED

    def _stop(self, phase: LeasePhase, reason: str) -> None:
        self.phase = phase
        self.stop_reason = reason
        self.cancel.set()
