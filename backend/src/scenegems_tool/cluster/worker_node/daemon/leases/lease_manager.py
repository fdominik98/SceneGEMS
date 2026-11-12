"""The worker node's leases: accept or reject offers, run, renew, cancel, drain, and report results.

Control node messages arrive on the connection thread (`handle`), workers finish on their own
threads, and the daemon's ticker calls `tick` a few times a second, connected or not. The
ticker renews leases, gives up overdue ones, streams report frames and retries results
and releases that could not be sent while the control node was unreachable. Leases live in
this process only: they survive a reconnect, not a restart (the control node's lease expires).

Frames of one lease are sent under that lease's lock, so its status and log lines always
reach the control node before its result.

Observation: an accepted simulation gets an observation in WorkerNodeContext.observations, which the
control node's Observe switches on and off (on_observe) and the job's stack feeds with the run's
frames. The daemon's relay calls relay_observations about 10 times a second; each observed job
sends at most one ObservationFrames batch per call (job_observation.py bounds and rates them).
When the job's worker stops, what is left goes out (if the lease still holds) and the
observation is closed.
"""

import logging
import threading
import time
from typing import Callable, Dict, List, Optional, Protocol, Tuple

from scenegems_tool.cluster.fingerprints.components import slot_job_types
from scenegems_tool.cluster.protocol.jobs import JobSpec, JobType
from scenegems_tool.cluster.protocol.messages import (
    Cancel,
    ControlNodeMessage,
    Drain,
    JobResult,
    LeaseAccept,
    LeaseOffer,
    LeaseReject,
    LeaseRelease,
    LeaseRenew,
    LeaseRenewed,
    ObservationFrames,
    Observe,
    StartJob,
)
from scenegems_tool.cluster.protocol.model_base import ProtocolFrame
from scenegems_tool.cluster.protocol.worker_node_description import SlotUsage
from scenegems_tool.cluster.worker_node.daemon.leases.lease import Lease, LeasePhase
from scenegems_tool.cluster.worker_node.daemon.leases.lease_worker import JobRunner, start_lease_worker
from scenegems_tool.cluster.worker_node.daemon.leases.report_batcher import ReportBatcher
from scenegems_tool.cluster.worker_node.daemon.leases.slot_table import SlotTable
from scenegems_tool.cluster.worker_node.job_observation import JobObservation
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext

_logger = logging.getLogger(__name__)

RENEWALS_PER_TIMEOUT = 3  # renew three times per lease timeout, so one lost renewal does not lose the lease


class FrameSender(Protocol):
    @property
    def connected(self) -> bool: ...

    def send(self, frame: ProtocolFrame) -> bool: ...  # False when the frame could not be sent


class LeaseManager:
    def __init__(
        self,
        slots: SlotTable,
        worker_node: WorkerNodeContext,
        sender: FrameSender,
        *,
        run: Optional[JobRunner] = None,
        clock: Callable[[], float] = time.monotonic,
        batcher: Callable[[str, str], ReportBatcher] = ReportBatcher,
    ):
        if run is None:
            from scenegems_tool.cluster.worker_node.jobs.job_runner import run_job as run
        self.slots = slots
        self.worker_node = worker_node
        self.sender = sender
        self._run = run
        self._clock = clock
        self._new_batcher = batcher
        self._lock = threading.RLock()
        self._leases: Dict[str, Lease] = {}
        self._batchers: Dict[str, ReportBatcher] = {}
        self._frame_locks: Dict[str, threading.Lock] = {}
        self._workers: Dict[str, threading.Thread] = {}
        self._observation_lock = threading.Lock()  # one ObservationFrames at a time, so every job's seq goes out in order
        self.lease_timeout_s: Optional[float] = None
        self.draining = False
        self.drain_reason = ""
        self.shutting_down = False

    # Control node messages

    def set_lease_timeout(self, lease_timeout_s: float) -> None:
        self.lease_timeout_s = lease_timeout_s

    @property
    def renew_every_s(self) -> Optional[float]:
        return None if self.lease_timeout_s is None else self.lease_timeout_s / RENEWALS_PER_TIMEOUT

    def handle(self, message: ControlNodeMessage) -> bool:
        """Act on a lease message; False for messages that are not about leases."""
        if isinstance(message, LeaseOffer):
            self.on_offer(message)
        elif isinstance(message, LeaseRenewed):
            self.on_renewed(message)
        elif isinstance(message, Cancel):
            self.on_cancel(message)
        elif isinstance(message, Drain):
            self.on_drain(message)
        elif isinstance(message, Observe):
            self.on_observe(message)
        elif isinstance(message, StartJob):
            self.on_start(message)
        else:
            return False
        return True

    def on_offer(self, offer: LeaseOffer) -> None:
        job = offer.job
        with self._lock:
            existing = self._leases.get(offer.lease_id)
            if existing is not None:
                if existing.held:
                    self.sender.send(LeaseAccept(lease_id=offer.lease_id))  # the control node asked again, for example after a reconnect
                else:
                    self.sender.send(LeaseReject(lease_id=offer.lease_id, reason=f"the lease is {existing.phase.value} on this worker node"))
                return
            reason = self._refusal(job)
            if reason is None:
                full = self.slots.take_all(self._slot_types(job))
                if full is not None:
                    reason = f"all {self.slots.capacity[full]} {full.value} slots are in use"
            if reason is not None:
                _logger.info("Rejecting lease %s (job %s): %s", offer.lease_id, job.job_id, reason)
                self.sender.send(LeaseReject(lease_id=offer.lease_id, reason=reason))
                return
            if not self.sender.send(LeaseAccept(lease_id=offer.lease_id)):
                self.slots.give_back_all(self._slot_types(job))  # the control node never heard of the accept; its offer expires
                return
            lease = Lease(offer.lease_id, job, self._clock())
            batcher = self._new_batcher(offer.lease_id, job.job_id)
            self._leases[lease.lease_id] = lease
            self._batchers[lease.lease_id] = batcher
            self._frame_locks[lease.lease_id] = threading.Lock()
            _logger.info("Accepted lease %s: %s job %s, attempt %d", lease.lease_id, job.job_type.value, job.job_id, job.attempt)
            batcher.daemon_line(f"accepted on worker node {self.worker_node.worker_node_id}, attempt {job.attempt}")
            self.worker_node.observations.open(job)
            self._workers[lease.lease_id] = start_lease_worker(lease, self._run, self.worker_node, batcher, self._worker_stopped)

    def on_renewed(self, message: LeaseRenewed) -> None:
        with self._lock:
            lease = self._leases.get(message.lease_id)
            if lease is not None:
                lease.renewed(self._clock())

    def on_cancel(self, message: Cancel) -> None:
        with self._lock:
            lease = self._leases.get(message.lease_id)
            if lease is None:
                _logger.info("Cancel for lease %s, which this worker node does not hold", message.lease_id)
                return
            _logger.info("The control node cancelled lease %s (job %s): %s", lease.lease_id, lease.job_id, message.reason)
            lease.cancel_by_control_node(message.reason)
            self._forget_if_ended(lease)

    def on_observe(self, message: Observe) -> None:
        with self._lock:
            lease = next((lease for lease in self._leases.values() if lease.job_id == message.job_id and lease.job.attempt == message.attempt), None)
        observation = self.worker_node.observations.get(message.job_id, message.attempt) if lease is not None and lease.phase == LeasePhase.RUNNING else None
        if observation is None:
            _logger.debug("Observe for job %s attempt %d, which this worker node does not run observably", message.job_id, message.attempt)
            return
        if observation.request(message.active, message.speed):
            what = f"observed at {message.speed:g} times real time" if message.active else "no longer observed"
            _logger.info("Job %s (lease %s): %s", lease.job_id, lease.lease_id, what)

    def on_start(self, message: StartJob) -> None:
        """The operator's Start reaches the job through its observation, as the request to observe does."""
        with self._lock:
            lease = next((lease for lease in self._leases.values() if lease.job_id == message.job_id and lease.job.attempt == message.attempt), None)
        observation = self.worker_node.observations.get(message.job_id, message.attempt) if lease is not None and lease.phase == LeasePhase.RUNNING else None
        if observation is None:
            _logger.debug("Start for job %s attempt %d, which this worker node does not run", message.job_id, message.attempt)
            return
        if observation.start():
            _logger.info("Job %s (lease %s): started by the operator", lease.job_id, lease.lease_id)

    def on_drain(self, message: Drain) -> None:
        with self._lock:
            self.draining = True
            self.drain_reason = message.reason
        _logger.info("Draining: no new leases, %d running ones finish (%s)", len(self.running_lease_ids()), message.reason)

    @staticmethod
    def _slot_types(job: JobSpec) -> Tuple[JobType, ...]:
        """The slots the job takes: its own type's, and a monitoring slot for a simulation judged while it runs."""
        return slot_job_types(job.job_type, job.requirements.components)

    def _refusal(self, job: JobSpec) -> Optional[str]:
        if self.shutting_down:
            return "the worker node is shutting down"
        if self.draining:
            return f"the worker node is draining ({self.drain_reason})" if self.drain_reason else "the worker node is draining"
        for job_type in self._slot_types(job):
            if not self.slots.offers(job_type):
                return f"this worker node offers no {job_type.value} slots"
        lacking = self.worker_node.lacks(job)
        if lacking:
            return f"this worker node does not offer the components {', '.join(lacking)}"
        return None

    # Workers

    def _worker_stopped(self, lease: Lease, result: JobResult) -> None:
        with self._lock:
            self.slots.give_back_all(self._slot_types(lease.job))
            self._workers.pop(lease.lease_id, None)
            lease.worker_stopped(result)
            _logger.info("Lease %s stopped: %s", lease.lease_id, result.outcome.value if lease.phase == LeasePhase.FINISHED else lease.stop_reason or lease.phase.value)
        self._end_observation(lease)
        self._deliver(lease)

    def _deliver(self, lease: Lease) -> None:
        """Send what an ended or finished lease still owes the control node: final reports and the result, or the release."""
        lock = self._frame_locks.get(lease.lease_id)
        if lock is None:
            return
        with lock:
            if lease.phase == LeasePhase.FINISHED and lease.result is not None:
                if not self._send_reports(lease, force=True) or not self.sender.send(lease.result):
                    return  # retried by the ticker
                with self._lock:
                    lease.result_sent()
            elif lease.release_pending:
                if not self.sender.send(LeaseRelease(lease_id=lease.lease_id, reason=lease.stop_reason)):
                    return
                lease.release_pending = False
        with self._lock:
            self._forget_if_ended(lease)

    def _send_reports(self, lease: Lease, *, force: bool = False) -> bool:
        batcher = self._batchers.get(lease.lease_id)
        if batcher is None or not self.sender.connected:
            return False
        for frame in batcher.take_frames(force=force):
            if not self.sender.send(frame):
                return False
        return True

    def _forget_if_ended(self, lease: Lease) -> None:
        if lease.phase == LeasePhase.ENDED and not lease.release_pending:
            self._leases.pop(lease.lease_id, None)
            self._batchers.pop(lease.lease_id, None)
            self._frame_locks.pop(lease.lease_id, None)

    # Ticker

    def tick(self) -> None:
        now = self._clock()
        with self._lock:
            leases = list(self._leases.values())
        for lease in leases:
            if lease.phase == LeasePhase.RUNNING and self.lease_timeout_s is not None:
                if lease.is_overdue(now, self.lease_timeout_s):
                    self._lose(lease, now)
                elif lease.renewal_due(now, self.renew_every_s) and self.sender.send(LeaseRenew(lease_id=lease.lease_id)):
                    lease.renewal_sent(now)
            if lease.phase == LeasePhase.RUNNING:
                lock = self._frame_locks.get(lease.lease_id)
                if lock is not None and lock.acquire(blocking=False):
                    try:
                        self._send_reports(lease)
                    finally:
                        lock.release()
            elif lease.phase == LeasePhase.FINISHED or lease.release_pending:
                self._deliver(lease)

    # Observation

    def relay_observations(self) -> int:
        """Sends each observed job's batch of frames when one is due; the number of batches sent."""
        if not self.sender.connected:
            return 0
        with self._lock:
            leases = [lease for lease in self._leases.values() if lease.phase == LeasePhase.RUNNING]
        sent = 0
        for lease in leases:
            observation = self.worker_node.observations.of(lease.job)
            if observation is not None and self._send_frames(lease, observation):
                sent += 1
        return sent

    def _send_frames(self, lease: Lease, observation: JobObservation, force: bool = False) -> bool:
        with self._observation_lock:
            batch = observation.take_batch(force=force)
            if batch is None:
                return False
            seq, frames = batch
            return self.sender.send(ObservationFrames(lease_id=lease.lease_id, job_id=lease.job_id, attempt=lease.job.attempt, seq=seq, frames=frames))

    def _end_observation(self, lease: Lease) -> None:
        """The job's run is over: the frames still waiting go out while the lease holds, then the observation closes."""
        observation = self.worker_node.observations.of(lease.job)
        if observation is None:
            return
        if lease.held and observation.active and self.sender.connected:
            while self._send_frames(lease, observation, force=True):
                pass
        self.worker_node.observations.close(lease.job)

    def _lose(self, lease: Lease, now: float) -> None:
        silent_s = now - lease.confirmed_at
        _logger.warning("Lease %s (job %s) was not renewed for %.0f s; stopping the job, the control node has requeued it", lease.lease_id, lease.job_id, silent_s)
        with self._lock:
            lease.lose(f"no lease renewal confirmed for {silent_s:.0f} s")

    # State for Hello and Heartbeat

    def running_lease_ids(self) -> List[str]:
        with self._lock:
            return sorted(lease.lease_id for lease in self._leases.values() if lease.held)

    def slots_in_use(self) -> SlotUsage:
        return self.slots.in_use()

    def lease(self, lease_id: str) -> Optional[Lease]:
        with self._lock:
            return self._leases.get(lease_id)

    @property
    def busy(self) -> bool:
        with self._lock:
            return bool(self._leases)

    # Shutdown

    def shutdown(self, reason: str, timeout_s: float) -> None:
        """Stop accepting, stop every running job, wait for the workers, then release their leases."""
        with self._lock:
            self.shutting_down = True
            for lease in self._leases.values():
                lease.release(reason)
            workers = list(self._workers.values())
        deadline = time.monotonic() + timeout_s
        for worker in workers:
            worker.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._lock:
            leases = list(self._leases.values())
        for lease in leases:
            self._deliver(lease)
