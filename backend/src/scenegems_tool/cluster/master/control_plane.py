"""The master's control plane: node registry, scheduler and lease manager on one event loop.

The control socket hands it each node's Hello and frames, the operator API its
submissions, cancels and drains. Timers run the scheduler, the lease expiry sweep and the
silence sweep (timing.py). Store calls run in worker threads, so the event loop keeps
serving sockets while Postgres works.

A submission's payload is validated with its job type's payload model before it is stored;
an artifact reference gets a structural check only, its content is checked on the node.
The job type modules load on the first submission, so the master starts without them.

Live simulations: observations (observed_jobs.py) sends Observe to the nodes of jobs that
browsers observe, again when such a node reconnects or accepts the job's lease, and hands the
frames the nodes relay to the live channel, which create_live_channel wires to it.

With attach_pipeline the pipeline engine (assurance/pipeline) runs as one more timer on the
same loop; it submits and cancels through this control plane like the operator does. It is
loaded only then, for the same reason. wake_pipeline runs its next tick at once.
"""

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional

import anyio
from pydantic import ValidationError

from scenegems_tool.cluster.master.job_activity import JobActivity
from scenegems_tool.cluster.master.leases.lease_manager import LeaseManager
from scenegems_tool.cluster.master.observed_jobs import ObservedJobs
from scenegems_tool.cluster.master.registry.node_registry import NodeRegistry
from scenegems_tool.cluster.master.registry.node_session import ControlSocket, NodeSession
from scenegems_tool.cluster.master.scheduling.fingerprint_policy import ExpectedFingerprints, with_required_fingerprints
from scenegems_tool.cluster.master.scheduling.node_eligibility import ResourceGuard
from scenegems_tool.cluster.master.scheduling.reject_backoff import RejectBackoff
from scenegems_tool.cluster.master.scheduling.scheduler import Scheduler
from scenegems_tool.cluster.master.timing import ControlTiming
from scenegems_tool.cluster.protocol.jobs import JobSubmission, JobType
from scenegems_tool.cluster.protocol.messages import (
    Cancel,
    Heartbeat,
    Hello,
    JobResult,
    JobStatus,
    LeaseAccept,
    LeaseReject,
    LeaseRelease,
    LeaseRenew,
    LogLines,
    NodeMessage,
    ObservationFrames,
    ProtocolError,
    ProtocolErrorCode,
    Welcome,
)
from scenegems_tool.persistence.clock import Clock, utc_now
from scenegems_tool.persistence.stores import CancelOutcome, JobStore, NodeRecord, NodeStore, SubmitOutcome

if TYPE_CHECKING:
    from scenegems_tool.assurance.pipeline.pipeline_engine import NodeAvailability, PipelineEngine
    from scenegems_tool.persistence.stores import AssuranceStores

logger = logging.getLogger(__name__)


# Node frames about a lease that the lease manager handles as they are: frame type to LeaseManager method
_LEASE_STEPS = {LeaseRenew: "renew", LeaseReject: "reject", LeaseRelease: "release", JobResult: "result", JobStatus: "status", LogLines: "logs"}


class FingerprintsUnavailable(RuntimeError):
    """The expected fingerprints are not computed (yet), so a job's requirements cannot be set."""


class InvalidPayload(ValueError):
    """A submission's payload does not match its job type's payload model."""

    def __init__(self, job_type: JobType, error: ValidationError) -> None:
        super().__init__(f"Invalid {job_type.value} payload: {error}")
        self.job_type = job_type
        self.errors: List[Any] = error.errors(include_url=False, include_context=False, include_input=False)


def validate_submission_payload(submission: JobSubmission) -> JobSubmission:
    """The submission with the components its payload needs; raises InvalidPayload unless the payload validates (references are checked for shape only)."""
    from scenegems_tool.cluster.node.jobs.job_types import payload_components

    try:
        components = payload_components(submission.job_type, submission.payload)
    except ValidationError as error:
        raise InvalidPayload(submission.job_type, error) from error
    return submission.model_copy(update={"requirements": submission.requirements.model_copy(update={"components": list(components)})})


class ControlPlane:
    def __init__(
        self,
        master_id: str,
        node_store: NodeStore,
        job_store: JobStore,
        expected: ExpectedFingerprints,
        timing: ControlTiming = ControlTiming(),
        guard: ResourceGuard = ResourceGuard(),
        clock: Clock = utc_now,
    ):
        self.master_id = master_id
        self.timing = timing
        self.expected = expected
        self.jobs = job_store
        self.registry = NodeRegistry(node_store, timing.node_offline_after_s)
        self.backoff = RejectBackoff(clock=clock)
        self.activity = JobActivity(clock)
        self.scheduler = Scheduler(job_store, self.registry, expected, self.backoff, timing, guard, self.activity)
        self.leases = LeaseManager(job_store, self.registry, self.backoff, self.activity, timing, on_change=self.scheduler.wake)
        self.observations = ObservedJobs(self.registry)
        self._clock = clock
        self._tasks: List[asyncio.Task] = []
        self.pipeline: Optional["PipelineEngine"] = None

    # Lifetime

    async def start(self, timers: bool = True) -> None:
        """Loads the expected fingerprints and starts the scheduler and the sweeps; without timers a test drives them."""
        self._tasks.append(asyncio.create_task(self._load_expected()))
        if timers:
            self._tasks.append(asyncio.create_task(self.scheduler.run()))
            self._tasks.append(asyncio.create_task(self._every(self.timing.expiry_sweep_interval_s, self.leases.sweep_expired)))
            self._tasks.append(asyncio.create_task(self._every(self.timing.offline_sweep_interval_s, self.registry.sweep_silent)))
            if self.pipeline is not None:
                self._tasks.append(asyncio.create_task(self.pipeline.run(self.timing.pipeline_tick_interval_s)))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _load_expected(self) -> None:
        await self.expected.load()
        self.scheduler.wake()

    @staticmethod
    async def _every(interval_s: float, action) -> None:
        while True:
            await asyncio.sleep(interval_s)
            try:
                await action()
            except Exception:
                logger.exception("%s failed; retrying in %.0f s", getattr(action, "__name__", "timer"), interval_s)

    # Nodes

    async def open_session(self, hello: Hello, socket: ControlSocket, connected_at: Optional[datetime] = None) -> NodeSession:
        """Registers the node from its Hello, reconciles the leases it reports and sends Welcome."""
        record = await self.registry.register(hello)
        session = NodeSession(node_id=hello.node_id, socket=socket, record=record, connected_at=connected_at or self._clock())
        await self.registry.connect(session)
        frames = await self.leases.reconcile(session, hello.running_lease_ids)
        # Nothing awaits between ready and the Welcome taking the socket's send lock, so no offer can go first
        session.ready = True
        await session.send(Welcome(master_id=self.master_id, heartbeat_interval_s=self.timing.heartbeat_interval_s, lease_timeout_s=self.timing.lease_timeout_s))
        for frame in frames:
            await session.send(frame)
        self.observations.node_connected(session)
        logger.info("Node %s (%s) connected at revision %s", hello.node_id, hello.node_name, hello.software_revision)
        self.scheduler.wake()
        return session

    async def handle_frame(self, session: NodeSession, frame: NodeMessage) -> None:
        lease_step = _LEASE_STEPS.get(type(frame))
        if lease_step is not None:
            await getattr(self.leases, lease_step)(session, frame)
        elif isinstance(frame, Heartbeat):
            await self.registry.heartbeat(session, frame)
            self.scheduler.wake()
        elif isinstance(frame, LeaseAccept):
            await self.leases.accept(session, frame)
            if session.owns(frame.lease_id):
                self.observations.lease_accepted(session, session.job_of(frame.lease_id))
        elif isinstance(frame, ObservationFrames):
            self.observations.handle_frames(session, frame)
        elif isinstance(frame, Hello):
            await session.send(ProtocolError(code=ProtocolErrorCode.MALFORMED_FRAME, message="Hello was already received on this connection"))

    async def close_session(self, session: NodeSession) -> None:
        if session.replaced:
            self.registry.disconnect(session)
            return
        await self.leases.withdraw_offers(session)
        if self.registry.disconnect(session):
            logger.info("Node %s disconnected", session.node_id)

    async def drain(self, node_id: str, reason: str) -> Optional[NodeRecord]:
        return await self.registry.drain(node_id, reason)

    async def resume(self, node_id: str) -> Optional[NodeRecord]:
        record = await self.registry.resume(node_id)
        self.scheduler.wake()
        return record

    async def remove_node(self, node_id: str) -> Optional[bool]:
        """Forgets an offline node, for the operator's clean-up of old machines; None for an unknown node, False for one that is not offline."""
        return await self.registry.remove(node_id)

    # Jobs

    async def submit(self, submission: JobSubmission) -> SubmitOutcome:
        expected = self.expected.current()
        if expected is None and not submission.requirements.fingerprints:
            raise FingerprintsUnavailable(f"the master's expected image fingerprints are {self.expected.state.value}" + (f": {self.expected.error}" if self.expected.error else ""))
        submission = await anyio.to_thread.run_sync(validate_submission_payload, submission)
        if expected is not None:
            submission = with_required_fingerprints(submission, expected)
        outcome = await anyio.to_thread.run_sync(self.jobs.submit, submission)
        self.activity.changed(outcome.job.job_id)
        self.scheduler.wake()
        return outcome

    async def cancel(self, job_id: str, reason: str) -> CancelOutcome:
        outcome = await anyio.to_thread.run_sync(self.jobs.cancel, job_id, reason)
        self.backoff.job_ended(job_id)
        self.activity.changed(job_id)
        if outcome.cancelled and outcome.lease_id is not None:
            session = self.registry.session(outcome.node_id)
            if session is not None:
                session.forget(outcome.lease_id)
                await session.send(Cancel(lease_id=outcome.lease_id, job_id=job_id, reason=reason))
            self.scheduler.wake()
        return outcome

    # Campaigns

    def attach_pipeline(self, stores: "AssuranceStores") -> "PipelineEngine":
        """Runs the pipeline engine on the campaign stores as a timer of this control plane (from start on)."""
        from scenegems_tool.assurance.pipeline.pipeline_engine import EngineSettings, PipelineEngine

        self.pipeline = PipelineEngine(
            stores,
            self.jobs,
            submit=self.submit,
            cancel=self.cancel,
            expected=self.expected.current,
            nodes=self.node_availability,
            wake=self.scheduler.wake,
            clock=self._clock,
            settings=EngineSettings(stall_after_s=self.timing.campaign_stall_after_s),
        )
        return self.pipeline

    def wake_pipeline(self) -> None:
        """Runs a pipeline engine tick at once, so a campaign or workbench entry just created starts without waiting; nothing without an engine."""
        if self.pipeline is not None:
            self.pipeline.wake()

    def node_availability(self) -> List["NodeAvailability"]:
        """The connected nodes as the pipeline engine's stall check sees them."""
        from scenegems_tool.assurance.pipeline.pipeline_engine import NodeAvailability

        return [NodeAvailability(record=session.record, stale_components=session.stale_components) for session in self.registry.connected()]
