"""Records built from transient rows, without a database."""

from datetime import datetime, timedelta, timezone

from scenegems_tool.cluster.protocol.jobs import JobRequirements, JobState, JobType
from scenegems_tool.persistence.schema import JobRow, WorkerNodeCapabilityRow, WorkerNodeComponentRow, WorkerNodeFingerprintRow, WorkerNodeRow, WorkerNodeStatus
from scenegems_tool.persistence.stores import JobRecord, Lease, SlotState, WorkerNodeRecord

START = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)


def _job_row(**overrides) -> JobRow:
    values = dict(
        id="job-1",
        seq=1,
        job_type=JobType.SIMULATION,
        payload={"steps": 300},
        required_labels={"site": "lab"},
        required_fingerprints={"scenegems-simulation": "f1"},
        min_memory_mb=2000,
        min_cpus=1.5,
        priority=5,
        max_attempts=3,
        idempotency_key="key-1",
        state=JobState.RUNNING,
        attempt=2,
        failed_attempts=1,
        lease_id="lease-2",
        lease_owner="worker-node-a",
        lease_expires_at=START + timedelta(seconds=30),
        submitted_at=START,
        updated_at=START,
        started_at=START,
        finished_at=None,
        result_attempt=1,
        result=None,
        error="boom",
    )
    values.update(overrides)
    return JobRow(**values)


def test_job_record_rebuilds_the_requirements():
    record = JobRecord.from_row(_job_row())
    assert record.requirements == JobRequirements(labels={"site": "lab"}, fingerprints={"scenegems-simulation": "f1"}, min_memory_mb=2000, min_cpus=1.5)
    assert (record.state, record.attempt, record.failed_attempts, record.error) == (JobState.RUNNING, 2, 1, "boom")
    assert record.allowed_worker_nodes == ()
    assert JobRecord.from_row(_job_row(allowed_worker_nodes=["worker-node-a", "worker-node-b"])).allowed_worker_nodes == ("worker-node-a", "worker-node-b")


def test_lease_carries_the_job_spec_for_the_offer():
    lease = Lease.from_row(_job_row())
    assert (lease.lease_id, lease.worker_node_id, lease.state) == ("lease-2", "worker-node-a", JobState.RUNNING)
    assert lease.job.job_id == "job-1"
    assert lease.job.attempt == 2
    assert lease.job.idempotency_key == "key-1"
    assert lease.job.payload == {"steps": 300}


def test_records_do_not_share_mutable_state_with_rows():
    row = _job_row()
    record = JobRecord.from_row(row)
    row.payload["steps"] = 1
    assert record.payload == {"steps": 300}


def test_worker_node_record():
    row = WorkerNodeRow(
        id="worker-node-a",
        name="lab-1",
        status=WorkerNodeStatus.DRAINING,
        labels={"gpu": "yes"},
        software_revision="755cbec",
        cpus=8.0,
        memory_mb=16000,
        free_memory_mb=9000,
        free_disk_mb=50000,
        load_average=0.5,
        registered_at=START,
        last_seen_at=START,
    )
    row.capabilities = [WorkerNodeCapabilityRow(job_type=JobType.SCENE_GENERATION, slots=4, slots_in_use=1)]
    row.fingerprints = [WorkerNodeFingerprintRow(image="scenegems-scene-generation", fingerprint="f1")]
    row.components = [WorkerNodeComponentRow(component="monitoring"), WorkerNodeComponentRow(component="scene_generation")]
    record = WorkerNodeRecord.from_row(row)
    assert record.status == WorkerNodeStatus.DRAINING
    assert record.slots == {JobType.SCENE_GENERATION: SlotState(slots=4, slots_in_use=1)}
    assert record.components == ("monitoring", "scene_generation")
    assert record.fingerprints == {"scenegems-scene-generation": "f1"}
    assert record.resources.free_memory_mb == 9000
