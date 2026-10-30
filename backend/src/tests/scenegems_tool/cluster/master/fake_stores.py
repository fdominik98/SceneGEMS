"""In-memory stand-ins for NodeStore and JobStore, so the master's tests run without Postgres.

They follow the real stores step by step and reuse their pure rules (job_lifecycle,
free_job_types) and record types. The tests that matter most run against both these and
the real stores (the `stores` fixture in conftest.py), which keeps the two honest.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import count
from typing import Any, Collection, Dict, List, Optional, Tuple
from uuid import uuid4

from scenegems_tool.cluster.fingerprints.comparison import with_legacy_names
from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobState, JobSubmission, JobType
from scenegems_tool.cluster.protocol.messages import Heartbeat, Hello, JobResult
from scenegems_tool.cluster.protocol.node_description import NodeResources
from scenegems_tool.persistence.schema import HELD_UNTIL, JobEventKind, NodeStatus
from scenegems_tool.persistence.stores import (
    CancelOutcome,
    ExpiredLease,
    IdempotencyKeyMismatch,
    JobEventRecord,
    JobRecord,
    Lease,
    NodeRecord,
    ResultReport,
    ResultStatus,
    SlotState,
    SubmitOutcome,
    UnknownJob,
    UnknownNode,
)
from scenegems_tool.persistence.stores.job_claim import free_job_types
from scenegems_tool.persistence.stores.job_lifecycle import ACTIVE_STATES, lease_is_current, result_status, retry_backoff_s, state_after_failed_attempt
from scenegems_tool.persistence.stores.job_store import DEFAULT_RETRY_BACKOFF_BASE_S, DEFAULT_RETRY_BACKOFF_CAP_S, UNFINISHED_STATES


@dataclass
class _Node:
    id: str
    name: str
    status: NodeStatus
    labels: Dict[str, str]
    software_revision: str
    resources: NodeResources
    slots: Dict[JobType, int]
    slots_in_use: Dict[JobType, int]
    fingerprints: Dict[str, str]
    registered_at: datetime
    last_seen_at: datetime
    machine: Optional[str] = None
    components: Tuple[str, ...] = ()

    def record(self) -> NodeRecord:
        return NodeRecord(
            node_id=self.id,
            name=self.name,
            status=self.status,
            labels=dict(self.labels),
            software_revision=self.software_revision,
            resources=self.resources,
            slots={job_type: SlotState(slots=slots, slots_in_use=self.slots_in_use.get(job_type, 0)) for job_type, slots in sorted(self.slots.items())},
            fingerprints=dict(self.fingerprints),
            registered_at=self.registered_at,
            last_seen_at=self.last_seen_at,
            machine=self.machine,
            components=self.components,
        )


class InMemoryNodeStore:
    def __init__(self, clock):
        self._clock = clock
        self.lock = threading.RLock()
        self.nodes: Dict[str, _Node] = {}

    def register(self, hello: Hello) -> NodeRecord:
        with self.lock:
            now = self._clock()
            existing = self.nodes.get(hello.node_id)
            status = NodeStatus.DRAINING if existing is not None and existing.status == NodeStatus.DRAINING else NodeStatus.ONLINE
            self.nodes[hello.node_id] = _Node(
                id=hello.node_id,
                name=hello.node_name,
                status=status,
                labels=dict(hello.labels),
                software_revision=hello.software_revision,
                resources=hello.resources,
                slots={offer.job_type: offer.slots for offer in hello.slots},
                slots_in_use={},
                fingerprints=dict(hello.fingerprints),
                registered_at=existing.registered_at if existing else now,
                last_seen_at=now,
                machine=hello.machine,
                components=tuple(sorted(set(hello.components))),
            )
            return self.nodes[hello.node_id].record()

    def heartbeat(self, node_id: str, heartbeat: Heartbeat) -> Optional[NodeRecord]:
        with self.lock:
            node = self.nodes.get(node_id)
            if node is None:
                return None
            node.resources = heartbeat.resources
            node.last_seen_at = self._clock()
            if node.status == NodeStatus.OFFLINE:
                node.status = NodeStatus.ONLINE
            node.slots_in_use = {job_type: heartbeat.slots_in_use.get(job_type, 0) for job_type in node.slots}
            return node.record()

    def set_status(self, node_id: str, status: NodeStatus) -> Optional[NodeRecord]:
        with self.lock:
            node = self.nodes.get(node_id)
            if node is None:
                return None
            node.status = status
            return node.record()

    def mark_silent_nodes_offline(self, silent_for_s: float) -> List[str]:
        with self.lock:
            cutoff = self._clock() - timedelta(seconds=silent_for_s)
            silent = sorted(node.id for node in self.nodes.values() if node.status != NodeStatus.OFFLINE and node.last_seen_at < cutoff)
            for node_id in silent:
                self.nodes[node_id].status = NodeStatus.OFFLINE
            return silent

    def remove_offline(self, node_id: str) -> Optional[bool]:
        with self.lock:
            node = self.nodes.get(node_id)
            if node is None:
                return None
            if node.status != NodeStatus.OFFLINE:
                return False
            del self.nodes[node_id]
            return True

    def get(self, node_id: str) -> Optional[NodeRecord]:
        with self.lock:
            node = self.nodes.get(node_id)
            return None if node is None else node.record()

    def list_nodes(self, status: Optional[NodeStatus] = None) -> List[NodeRecord]:
        with self.lock:
            return [node.record() for node_id, node in sorted(self.nodes.items()) if status is None or node.status == status]


@dataclass
class _Job:
    """Attribute names as on JobRow, so JobRecord.from_row and Lease.from_row read it."""

    id: str
    seq: int
    job_type: JobType
    payload: Dict[str, Any]
    required_labels: Dict[str, str]
    required_fingerprints: Dict[str, str]
    required_components: List[str]
    min_memory_mb: int
    min_cpus: float
    priority: int
    max_attempts: int
    idempotency_key: str
    state: JobState
    submitted_at: datetime
    available_at: datetime
    updated_at: datetime
    attempt: int = 0
    failed_attempts: int = 0
    lease_id: Optional[str] = None
    lease_owner: Optional[str] = None
    lease_expires_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result_attempt: Optional[int] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    allowed_nodes: List[str] = field(default_factory=list)
    events: List[JobEventRecord] = field(default_factory=list)


class InMemoryJobStore:
    def __init__(self, node_store: InMemoryNodeStore, clock, retry_backoff_base_s: float = DEFAULT_RETRY_BACKOFF_BASE_S, retry_backoff_cap_s: float = DEFAULT_RETRY_BACKOFF_CAP_S):
        self._nodes = node_store
        self._clock = clock
        self.retry_backoff_base_s = retry_backoff_base_s
        self.retry_backoff_cap_s = retry_backoff_cap_s
        self._lock = node_store.lock  # one lock for both, as one database
        self._jobs: Dict[str, _Job] = {}
        self._seq = count(1)
        self._event_ids = count(1)

    def _event(self, job: _Job, kind: JobEventKind, from_state: Optional[JobState], at: datetime, detail: Optional[dict] = None) -> None:
        job.events.append(JobEventRecord(next(self._event_ids), job.id, at, kind, from_state, job.state, job.attempt, job.lease_id, job.lease_owner, detail or {}))

    def submit(self, submission: JobSubmission) -> SubmitOutcome:
        with self._lock:
            now = self._clock()
            job_id = str(uuid4())
            key = submission.idempotency_key or job_id
            for job in self._jobs.values():
                if job.idempotency_key == key:
                    return SubmitOutcome(job=JobRecord.from_row(job), created=False)
            requirements = submission.requirements
            job = _Job(
                id=job_id,
                seq=next(self._seq),
                job_type=submission.job_type,
                payload=dict(submission.payload),
                required_labels=dict(requirements.labels),
                required_fingerprints=dict(requirements.fingerprints),
                required_components=list(requirements.components),
                min_memory_mb=requirements.min_memory_mb,
                min_cpus=requirements.min_cpus,
                allowed_nodes=list(submission.allowed_nodes),
                priority=submission.priority,
                max_attempts=submission.max_attempts,
                idempotency_key=key,
                state=JobState.QUEUED,
                submitted_at=now,
                available_at=now,
                updated_at=now,
            )
            self._jobs[job_id] = job
            self._event(job, JobEventKind.SUBMITTED, None, now)
            return SubmitOutcome(job=JobRecord.from_row(job), created=True)

    def get(self, job_id: str) -> Optional[JobRecord]:
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else JobRecord.from_row(job)

    def list_jobs(self, state: Optional[JobState] = None, limit: int = 100) -> List[JobRecord]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda job: job.seq)
            return [JobRecord.from_row(job) for job in jobs if state is None or job.state == state][:limit]

    def events(self, job_id: str) -> List[JobEventRecord]:
        with self._lock:
            job = self._jobs.get(job_id)
            return [] if job is None else list(job.events)

    def recent_rejections(self, since: datetime) -> List[JobEventRecord]:
        with self._lock:
            found = [
                event
                for job in self._jobs.values()
                if job.state in (JobState.QUEUED,) + ACTIVE_STATES
                for event in job.events
                if event.kind == JobEventKind.REJECTED and event.at >= since and event.node_id is not None
            ]
            return sorted(found, key=lambda event: (event.at, event.event_id))

    def active_leases(self, node_id: Optional[str] = None) -> List[Lease]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda job: job.seq)
            return [Lease.from_row(job) for job in jobs if job.state in ACTIVE_STATES and (node_id is None or job.lease_owner == node_id)]

    def claim_next(
        self, node_id: str, lease_duration_s: float, job_types: Optional[Collection[JobType]] = None, exclude_job_ids: Collection[str] = (), components: Optional[Collection[str]] = None
    ) -> Optional[Lease]:
        with self._lock:
            now = self._clock()
            expires_at = now + timedelta(seconds=lease_duration_s)
            node = self._nodes.nodes.get(node_id)
            if node is None:
                raise UnknownNode(node_id)
            if node.status != NodeStatus.ONLINE:
                return None
            active: Dict[JobType, int] = {}
            for job in self._jobs.values():
                if job.lease_owner == node_id and job.state in ACTIVE_STATES:
                    active[job.job_type] = active.get(job.job_type, 0) + 1
            types = free_job_types(node.slots, active, job_types)
            offered = set(node.components if components is None else components)
            candidates = [
                job
                for job in self._jobs.values()
                if job.state == JobState.QUEUED
                and job.available_at <= now
                and job.job_type in types
                and job.required_labels.items() <= node.labels.items()
                and set(job.required_components) <= offered
                and job.required_fingerprints.items() <= with_legacy_names(node.fingerprints).items()
                and job.min_memory_mb <= node.resources.free_memory_mb
                and job.min_cpus <= node.resources.cpus
                and (not job.allowed_nodes or node_id in job.allowed_nodes)
                and job.id not in exclude_job_ids
            ]
            if not candidates:
                return None
            job = min(candidates, key=lambda job: (-job.priority, job.submitted_at, job.seq))
            job.state = JobState.LEASED
            job.attempt += 1
            job.lease_id = str(uuid4())
            job.lease_owner = node_id
            job.lease_expires_at = expires_at
            job.updated_at = now
            self._event(job, JobEventKind.LEASED, JobState.QUEUED, now)
            return Lease.from_row(job)

    def _by_lease(self, lease_id: str) -> Optional[_Job]:
        return next((job for job in self._jobs.values() if job.lease_id == lease_id), None)

    def accept(self, lease_id: str, lease_duration_s: float) -> Optional[Lease]:
        with self._lock:
            now = self._clock()
            job = self._by_lease(lease_id)
            if job is None or not lease_is_current(job.state, job.lease_id, job.lease_expires_at, lease_id, now):
                return None
            if job.state == JobState.RUNNING:
                return Lease.from_row(job)
            job.state = JobState.RUNNING
            job.lease_expires_at = now + timedelta(seconds=lease_duration_s)
            job.started_at = job.started_at or now
            job.updated_at = now
            self._event(job, JobEventKind.ACCEPTED, JobState.LEASED, now)
            return Lease.from_row(job)

    def renew(self, lease_id: str, lease_duration_s: float) -> Optional[Lease]:
        with self._lock:
            now = self._clock()
            job = self._by_lease(lease_id)
            if job is None or job.state != JobState.RUNNING or not lease_is_current(job.state, job.lease_id, job.lease_expires_at, lease_id, now):
                return None
            job.lease_expires_at = now + timedelta(seconds=lease_duration_s)
            job.updated_at = now
            return Lease.from_row(job)

    def reject(self, lease_id: str, reason: str) -> Optional[JobRecord]:
        return self._give_back(lease_id, reason, JobEventKind.REJECTED, (JobState.LEASED,))

    def release(self, lease_id: str, reason: str) -> Optional[JobRecord]:
        return self._give_back(lease_id, reason, JobEventKind.RELEASED, ACTIVE_STATES)

    def _give_back(self, lease_id: str, reason: str, kind: JobEventKind, allowed: Collection[JobState]) -> Optional[JobRecord]:
        with self._lock:
            now = self._clock()
            job = self._by_lease(lease_id)
            if job is None or job.state not in allowed or not lease_is_current(job.state, job.lease_id, job.lease_expires_at, lease_id, now):
                return None
            from_state = job.state
            job.state = JobState.QUEUED
            job.lease_expires_at = None
            job.updated_at = now
            self._event(job, kind, from_state, now, {"reason": reason})
            return JobRecord.from_row(job)

    def report_result(self, report: JobResult) -> ResultReport:
        with self._lock:
            now = self._clock()
            job = self._jobs.get(report.job_id)
            if job is None:
                raise UnknownJob(report.job_id)
            if job.idempotency_key != report.idempotency_key:
                raise IdempotencyKeyMismatch(f"job {job.id} has idempotency key {job.idempotency_key!r}")
            status = result_status(job.state, job.lease_id, job.lease_expires_at, job.attempt, job.result_attempt, report.lease_id, now)
            if status != ResultStatus.STORED:
                return ResultReport(status=status, job=JobRecord.from_row(job))
            from_state = job.state
            job.result_attempt = job.attempt
            job.result = dict(report.result)
            job.lease_expires_at = None
            job.updated_at = now
            if report.outcome == JobOutcome.SUCCEEDED:
                job.state, job.error, kind = JobState.SUCCEEDED, None, JobEventKind.SUCCEEDED
            else:
                job.failed_attempts += 1
                job.state = state_after_failed_attempt(job.failed_attempts, job.max_attempts, report.retryable)
                job.error = report.error
                kind = JobEventKind.ATTEMPT_FAILED if job.state == JobState.QUEUED else JobEventKind.FAILED
            if job.state == JobState.QUEUED and job.available_at < HELD_UNTIL:
                job.available_at = now + timedelta(seconds=retry_backoff_s(job.failed_attempts, self.retry_backoff_base_s, self.retry_backoff_cap_s))
            if job.state.is_terminal:
                job.finished_at = now
            self._event(job, kind, from_state, now)
            return ResultReport(status=status, job=JobRecord.from_row(job))

    def cancel(self, job_id: str, reason: str) -> CancelOutcome:
        with self._lock:
            now = self._clock()
            job = self._jobs.get(job_id)
            if job is None:
                raise UnknownJob(job_id)
            if job.state.is_terminal:
                return CancelOutcome(job=JobRecord.from_row(job), cancelled=False, lease_id=None, node_id=None)
            from_state = job.state
            was_active = from_state in ACTIVE_STATES
            job.state = JobState.CANCELLED
            job.lease_expires_at = None
            job.updated_at = job.finished_at = now
            self._event(job, JobEventKind.CANCELLED, from_state, now, {"reason": reason})
            return CancelOutcome(job=JobRecord.from_row(job), cancelled=True, lease_id=job.lease_id if was_active else None, node_id=job.lease_owner if was_active else None)

    def expire_leases(self, limit: Optional[int] = None) -> List[ExpiredLease]:
        with self._lock:
            now = self._clock()
            due = sorted((job for job in self._jobs.values() if job.state in ACTIVE_STATES and job.lease_expires_at <= now), key=lambda job: (job.lease_expires_at, job.seq))
            expired = []
            for job in due[:limit]:
                from_state = job.state
                job.failed_attempts += 1
                job.state = state_after_failed_attempt(job.failed_attempts, job.max_attempts)
                job.lease_expires_at = None
                job.updated_at = now
                if job.state == JobState.FAILED:
                    job.error = f"lease expired on attempt {job.attempt}, no attempts left"
                    job.finished_at = now
                self._event(job, JobEventKind.EXPIRED, from_state, now)
                expired.append(ExpiredLease(lease_id=job.lease_id, node_id=job.lease_owner, job=JobRecord.from_row(job)))
            return expired

    def hold_jobs(self, job_ids: Collection[str], *, session=None) -> List[str]:
        return self._set_availability(job_ids, HELD_UNTIL, lambda job: job.available_at < HELD_UNTIL)

    def release_held_jobs(self, job_ids: Collection[str], *, session=None) -> List[str]:
        return self._set_availability(job_ids, self._clock(), lambda job: job.available_at >= HELD_UNTIL)

    def _set_availability(self, job_ids: Collection[str], available_at: datetime, applies) -> List[str]:
        with self._lock:
            now = self._clock()
            changed = []
            for job_id in sorted(set(job_ids)):
                job = self._jobs.get(job_id)
                if job is not None and job.state in UNFINISHED_STATES and applies(job):
                    job.available_at = available_at
                    job.updated_at = now
                    changed.append(job_id)
            return changed
