"""What the scheduler does with a worker node that keeps rejecting the same job.

A rejected offer returns the job to the queue without using an attempt, so draining or a
busy worker node never burns retries. Without a rule, the claim would hand the same job straight
back to the worker node that refused it, forever. So after a reject the job is held back from that
worker node, 30 s after the first reject and twice as long after each further one, up to 10
minutes. Other worker nodes get the job meanwhile, and the worker node keeps getting other jobs; when no
other worker node can run the job, the rejecting worker node is asked again after the hold.

The holds live in the control node's memory and are dropped when the job ends. Every reject is
also a job event (REJECTED, with the worker node), so at start the control plane replays the
recent rejects of unfinished jobs through restore and a restarted control node keeps the holds.
The replay looks back RESTORE_HOLDS maximum holds: enough rejects to reach the longest hold,
so a hold rebuilt from that window is the one the control node had, or at most a step shorter.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Tuple

from scenegems_tool.persistence.clock import Clock, utc_now

RESTORE_HOLDS = 6  # 30, 60, 120, 240, 480, then 600 s: six rejects reach the longest hold


@dataclass
class _Hold:
    rejects: int
    until: datetime


@dataclass
class RejectBackoff:
    initial_hold_s: float = 30.0
    max_hold_s: float = 600.0
    clock: Clock = utc_now
    _holds: Dict[Tuple[str, str], _Hold] = field(default_factory=dict)

    def rejected(self, worker_node_id: str, job_id: str) -> datetime:
        """Records a reject; returns until when the job is held back from the worker node."""
        return self._record(worker_node_id, job_id, self.clock())

    def restore_since(self) -> datetime:
        """How far back restore needs the rejects."""
        return self.clock() - timedelta(seconds=self.max_hold_s * RESTORE_HOLDS)

    def restore(self, rejections: Iterable[Tuple[str, str, datetime]]) -> int:
        """Replays past rejects (worker node, job, time), oldest first, as if each had been recorded at its time; returns the holds kept."""
        for worker_node_id, job_id, at in rejections:
            self._record(worker_node_id, job_id, at)
        self._prune(self.clock())
        return len(self._holds)

    def _record(self, worker_node_id: str, job_id: str, now: datetime) -> datetime:
        self._prune(now)
        hold = self._holds.get((worker_node_id, job_id))
        rejects = 1 if hold is None else hold.rejects + 1
        until = now + timedelta(seconds=self.hold_s(rejects))
        self._holds[(worker_node_id, job_id)] = _Hold(rejects, until)
        return until

    def hold_s(self, rejects: int) -> float:
        return min(self.initial_hold_s * 2 ** (rejects - 1), self.max_hold_s)

    def held_jobs(self, worker_node_id: str) -> List[str]:
        """Jobs not to offer to the worker node now."""
        now = self.clock()
        return sorted(job_id for (holder, job_id), hold in self._holds.items() if holder == worker_node_id and hold.until > now)

    def job_ended(self, job_id: str) -> None:
        for key in [key for key in self._holds if key[1] == job_id]:
            del self._holds[key]

    def _prune(self, now: datetime) -> None:
        # A worker node that has not rejected the job for a full maximum hold starts again at the first hold
        horizon = now - timedelta(seconds=self.max_hold_s)
        for key in [key for key, hold in self._holds.items() if hold.until < horizon]:
            del self._holds[key]
