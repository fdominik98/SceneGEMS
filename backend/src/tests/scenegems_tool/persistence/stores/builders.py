"""Builders for node and job messages and campaign classes, and a clock the tests move by hand."""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Collection, Dict, Optional

from scenegems_tool.cluster.fingerprints.components import COMPONENTS
from scenegems_tool.cluster.protocol.jobs import JobRequirements, JobSubmission, JobType
from scenegems_tool.cluster.protocol.messages import Hello
from scenegems_tool.cluster.protocol.node_description import NodeResources, SlotOffer
from scenegems_tool.persistence.stores import ClassSpec

START = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)


class ManualClock:
    """A clock that moves only when the test advances it."""

    def __init__(self, now: datetime = START):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now


def make_resources(cpus: float = 8.0, memory_mb: int = 16000, free_memory_mb: int = 12000) -> NodeResources:
    return NodeResources(cpus=cpus, memory_mb=memory_mb, free_memory_mb=free_memory_mb, free_disk_mb=50000, load_average=0.1)


def make_hello(
    node_id: str,
    slots: Optional[Dict[JobType, int]] = None,
    labels: Optional[Dict[str, str]] = None,
    fingerprints: Optional[Dict[str, str]] = None,
    resources: Optional[NodeResources] = None,
    name: Optional[str] = None,
    machine: Optional[str] = None,
    components: Optional[Collection[str]] = None,
) -> Hello:
    """A node's Hello; it offers every component of the catalog unless components names some."""
    slots = {JobType.SCENE_GENERATION: 2} if slots is None else slots
    return Hello(
        node_id=node_id,
        node_name=name or f"{node_id}-host",
        software_revision="755cbec",
        machine=machine,
        slots=[SlotOffer(job_type=job_type, slots=count) for job_type, count in slots.items()],
        components=list(COMPONENTS if components is None else components),
        labels=labels or {},
        resources=resources or make_resources(),
        fingerprints=fingerprints or {},
    )


def make_submission(
    job_type: JobType = JobType.SCENE_GENERATION,
    priority: int = 0,
    idempotency_key: Optional[str] = None,
    max_attempts: int = 3,
    requirements: Optional[JobRequirements] = None,
    payload: Optional[dict] = None,
    allowed_nodes: Optional[list] = None,
) -> JobSubmission:
    return JobSubmission(
        job_type=job_type,
        payload=payload or {"scene": 1},
        requirements=requirements or JobRequirements(),
        priority=priority,
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
        allowed_nodes=allowed_nodes or [],
    )


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


CONFIG_HASH = sha256_of("config")


def make_class_spec(class_id: str = "2vessel_0obstacle_scenarios/functional_model0", quota: int = 3, failure_budget: Optional[int] = 2, vessels: int = 2, obstacles: int = 0) -> ClassSpec:
    return ClassSpec(class_id=class_id, content_hash=sha256_of(class_id), vessel_count=vessels, obstacle_count=obstacles, quota=quota, failure_budget=failure_budget)
