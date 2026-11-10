"""Live simulations on the control node: which job attempts browsers observe, and the Observe frames that tell their worker nodes.

The live channel's observation hub (live/observation_hub.py) reports a job instance's first
observer and its last (observe), and a new speed while observed (speed_changed). For each
observed attempt this sends Observe to every connected worker node that holds a lease on the job; a
worker node that runs another attempt, or no longer runs it, ignores the frame. The same Observe
goes again to a worker node that reconnects (worker_node_connected) or accepts the job's lease later
(lease_accepted), so an observation survives both.

The worker node relays the run's frames in ObservationFrames, which handle_frames checks against
the session's leases and hands to frames_sink (the hub's publish_simulation_frames). Frames
of an attempt nobody observes any more are answered with Observe off, which corrects a worker node
that missed the off.

Everything runs on the control node's event loop; sending is asynchronous, so the synchronous
hooks queue it as tasks, in order.
"""

import asyncio
import logging
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from scenegems_tool.cluster.control_node.registry.worker_node_registry import WorkerNodeRegistry
from scenegems_tool.cluster.control_node.registry.worker_node_session import WorkerNodeSession
from scenegems_tool.cluster.protocol.messages import DEFAULT_OBSERVED_SPEED, ObservationFrames, Observe

logger = logging.getLogger(__name__)

FramesSink = Callable[[str, str, int, List[Dict[str, Any]]], None]  # (worker node id, job id, attempt, frames)


class ObservedJobs:
    def __init__(self, registry: WorkerNodeRegistry):
        self._registry = registry
        self._observers: Dict[Tuple[str, int], int] = {}  # (job id, attempt) to its observed instance topics
        self._pending: Set[asyncio.Task] = set()
        self.speed_of: Callable[[str], float] = lambda _job_id: DEFAULT_OBSERVED_SPEED
        self.frames_sink: Optional[FramesSink] = None

    # The observation hub's hooks

    def observe(self, _worker_node_id: str, job_id: str, attempt: int, observed: bool) -> None:
        """An instance topic of the attempt got its first observer (observed) or lost its last.

        The topic's worker node id is the browser's choice; the frame goes to whichever worker node holds the job.
        """
        key = (job_id, attempt)
        count = self._observers.get(key, 0)
        if observed:
            self._observers[key] = count + 1
            if count == 0:
                self._send_to_holders(job_id, [self._frame(job_id, attempt, True)])
        elif count > 1:
            self._observers[key] = count - 1
        elif self._observers.pop(key, None) is not None:
            self._send_to_holders(job_id, [self._frame(job_id, attempt, False)])

    def speed_changed(self, job_id: str, _speed: float) -> None:
        """The observers chose another speed for the job: its observed attempts' worker nodes get it."""
        self._send_to_holders(job_id, [self._frame(job_id, attempt, True) for attempt in self._attempts(job_id)])

    def is_observed(self, job_id: str, attempt: int) -> bool:
        return (job_id, attempt) in self._observers

    # The control plane's hooks

    def worker_node_connected(self, session: WorkerNodeSession) -> None:
        """A worker node (re)connected: the observed jobs it still runs are observed again."""
        frames = [self._frame(job_id, attempt, True) for job_id in sorted(set(session.leases.values())) for attempt in self._attempts(job_id)]
        self._send(session, frames)

    def lease_accepted(self, session: WorkerNodeSession, job_id: str) -> None:
        """The worker node took the job's lease: an observation that began before is sent to it."""
        self._send(session, [self._frame(job_id, attempt, True) for attempt in self._attempts(job_id)])

    def handle_frames(self, session: WorkerNodeSession, frame: ObservationFrames) -> None:
        if not session.owns(frame.lease_id, frame.job_id):
            logger.debug("Worker node %s sent frames of lease %s, which it does not hold", session.worker_node_id, frame.lease_id)
            return
        if not self.is_observed(frame.job_id, frame.attempt):
            self._send(session, [Observe(job_id=frame.job_id, attempt=frame.attempt, active=False)])
            return
        if self.frames_sink is not None:
            self.frames_sink(session.worker_node_id, frame.job_id, frame.attempt, list(frame.frames))

    # Sending

    def _attempts(self, job_id: str) -> List[int]:
        return sorted(attempt for observed_job, attempt in self._observers if observed_job == job_id)

    def _frame(self, job_id: str, attempt: int, active: bool) -> Observe:
        return Observe(job_id=job_id, attempt=attempt, active=active, speed=self.speed_of(job_id))

    def _send_to_holders(self, job_id: str, frames: List[Observe]) -> None:
        for session in self._registry.connected():
            if job_id in session.leases.values():
                self._send(session, frames)

    def _send(self, session: WorkerNodeSession, frames: Iterable[Observe]) -> None:
        frames = list(frames)
        if not frames:
            return
        self._pending = {task for task in self._pending if not task.done()}  # kept only so the loop does not drop running sends
        self._pending.add(asyncio.get_running_loop().create_task(self._deliver(session, frames)))

    @staticmethod
    async def _deliver(session: WorkerNodeSession, frames: List[Observe]) -> None:
        for frame in frames:
            if not await session.send(frame):
                logger.info("Observe for job %s did not reach worker node %s; it is sent again when the worker node reconnects", frame.job_id, session.worker_node_id)
                return

    async def settle(self) -> None:
        """Waits until every queued Observe was sent (tests, shutdown)."""
        while True:
            pending = [task for task in self._pending if not task.done()]
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)
