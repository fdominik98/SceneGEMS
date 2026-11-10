from datetime import datetime, timezone

import pytest

from scenegems_tool.cluster.protocol.jobs import JobRequirements, JobSpec, JobType
from scenegems_tool.cluster.protocol.worker_node_description import WorkerNodeResources


@pytest.fixture
def resources() -> WorkerNodeResources:
    return WorkerNodeResources(cpus=8.0, memory_mb=16000, free_memory_mb=9000, free_disk_mb=50000, load_average=0.25)


@pytest.fixture
def job_spec() -> JobSpec:
    return JobSpec(
        job_id="job-1",
        job_type=JobType.SIMULATION,
        payload={"steps": 300, "dt": 1.0},
        requirements=JobRequirements(labels={"site": "lab"}, components=["asv_system/replay", "simulation_layer/kinematic"], fingerprints={"scenegems-scenario-execution": "abc123"}),
        attempt=1,
        idempotency_key="job-1/1",
    )


@pytest.fixture
def instant() -> datetime:
    return datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
