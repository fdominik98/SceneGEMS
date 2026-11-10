import pytest

from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobState, JobType
from scenegems_tool.cluster.protocol.messages import Heartbeat, JobResult
from scenegems_tool.persistence.schema import WorkerNodeStatus
from scenegems_tool.persistence.stores import SlotState
from tests.scenegems_tool.persistence.stores.builders import START, make_hello, make_resources, make_submission

pytestmark = pytest.mark.postgres

SCENE = JobType.SCENE_GENERATION
KINEMATIC = JobType.SIMULATION


def test_register_creates_an_online_worker_node(worker_node_store):
    hello = make_hello(
        "worker-node-a", slots={SCENE: 2, KINEMATIC: 4}, labels={"site": "lab"}, fingerprints={"scenegems-scene-generation": "f1"}, components=["scene_generation", "control_layer/none"]
    )
    worker_node = worker_node_store.register(hello)
    assert worker_node.status == WorkerNodeStatus.ONLINE
    assert worker_node.name == "worker-node-a-host"
    assert worker_node.labels == {"site": "lab"}
    assert worker_node.slots == {SCENE: SlotState(slots=2, slots_in_use=0), KINEMATIC: SlotState(slots=4, slots_in_use=0)}
    assert worker_node.components == ("control_layer/none", "scene_generation")
    assert worker_node.fingerprints == {"scenegems-scene-generation": "f1"}
    assert worker_node.registered_at == worker_node.last_seen_at == START
    assert worker_node_store.get("worker-node-a") == worker_node


def test_register_again_replaces_slots_components_and_fingerprints(worker_node_store, clock):
    worker_node_store.register(make_hello("worker-node-a", slots={SCENE: 2, KINEMATIC: 4}, fingerprints={"old-image": "f0", "kept-image": "f1"}))
    clock.advance(60)
    worker_node = worker_node_store.register(make_hello("worker-node-a", slots={KINEMATIC: 1}, fingerprints={"kept-image": "f2"}, name="renamed", components=["simulation_layer/kinematic"]))
    assert worker_node.slots == {KINEMATIC: SlotState(slots=1, slots_in_use=0)}
    assert worker_node.components == ("simulation_layer/kinematic",)
    assert worker_node.fingerprints == {"kept-image": "f2"}
    assert worker_node.name == "renamed"
    assert worker_node.registered_at == START
    assert worker_node.last_seen_at == clock.now


def test_register_stores_the_machine_and_the_latest_hello_wins(worker_node_store):
    assert worker_node_store.register(make_hello("worker-node-a")).machine is None
    assert worker_node_store.register(make_hello("worker-node-a", machine="lab-pc-3")).machine == "lab-pc-3"
    assert worker_node_store.get("worker-node-a").machine == "lab-pc-3"
    assert worker_node_store.list_worker_nodes()[0].machine == "lab-pc-3"
    assert worker_node_store.heartbeat("worker-node-a", Heartbeat(resources=make_resources())).machine == "lab-pc-3"
    assert worker_node_store.register(make_hello("worker-node-a", machine="lab-pc-4")).machine == "lab-pc-4"
    assert worker_node_store.register(make_hello("worker-node-a")).machine is None


def test_register_keeps_a_drain(worker_node_store):
    worker_node_store.register(make_hello("worker-node-a"))
    worker_node_store.set_status("worker-node-a", WorkerNodeStatus.DRAINING)
    assert worker_node_store.register(make_hello("worker-node-a")).status == WorkerNodeStatus.DRAINING


def test_register_brings_an_offline_worker_node_online(worker_node_store):
    worker_node_store.register(make_hello("worker-node-a"))
    worker_node_store.set_status("worker-node-a", WorkerNodeStatus.OFFLINE)
    assert worker_node_store.register(make_hello("worker-node-a")).status == WorkerNodeStatus.ONLINE


def test_heartbeat_records_resources_and_slot_usage(worker_node_store, clock):
    worker_node_store.register(make_hello("worker-node-a", slots={SCENE: 2, KINEMATIC: 4}))
    clock.advance(5)
    worker_node = worker_node_store.heartbeat("worker-node-a", Heartbeat(resources=make_resources(free_memory_mb=3000), slots_in_use={KINEMATIC: 3}))
    assert worker_node.last_seen_at == clock.now
    assert worker_node.resources.free_memory_mb == 3000
    assert worker_node.slots == {SCENE: SlotState(slots=2, slots_in_use=0), KINEMATIC: SlotState(slots=4, slots_in_use=3)}


def test_heartbeat_of_an_unknown_worker_node(worker_node_store):
    assert worker_node_store.heartbeat("ghost", Heartbeat(resources=make_resources())) is None


def test_heartbeat_brings_an_offline_worker_node_online_but_keeps_a_drain(worker_node_store):
    worker_node_store.register(make_hello("worker-node-a"))
    worker_node_store.register(make_hello("worker-node-b"))
    worker_node_store.set_status("worker-node-a", WorkerNodeStatus.OFFLINE)
    worker_node_store.set_status("worker-node-b", WorkerNodeStatus.DRAINING)
    assert worker_node_store.heartbeat("worker-node-a", Heartbeat(resources=make_resources())).status == WorkerNodeStatus.ONLINE
    assert worker_node_store.heartbeat("worker-node-b", Heartbeat(resources=make_resources())).status == WorkerNodeStatus.DRAINING


def test_set_status_of_an_unknown_worker_node(worker_node_store):
    assert worker_node_store.set_status("ghost", WorkerNodeStatus.DRAINING) is None


def test_silent_worker_nodes_go_offline(worker_node_store, clock):
    worker_node_store.register(make_hello("worker-node-a"))
    worker_node_store.register(make_hello("worker-node-b"))
    worker_node_store.register(make_hello("worker-node-c"))
    worker_node_store.set_status("worker-node-c", WorkerNodeStatus.DRAINING)
    clock.advance(20)
    worker_node_store.heartbeat("worker-node-b", Heartbeat(resources=make_resources()))
    clock.advance(15)
    # worker-node-a and worker-node-c last seen 35 s ago, worker-node-b 15 s ago
    assert worker_node_store.mark_silent_worker_nodes_offline(30) == ["worker-node-a", "worker-node-c"]
    assert worker_node_store.mark_silent_worker_nodes_offline(30) == []
    assert [worker_node.worker_node_id for worker_node in worker_node_store.list_worker_nodes(WorkerNodeStatus.OFFLINE)] == ["worker-node-a", "worker-node-c"]
    assert worker_node_store.get("worker-node-b").status == WorkerNodeStatus.ONLINE


def test_remove_offline_deletes_only_an_offline_worker_node(worker_node_store):
    worker_node_store.register(make_hello("worker-node-a", slots={SCENE: 2}, fingerprints={"image": "f1"}))
    worker_node_store.register(make_hello("worker-node-b"))
    assert worker_node_store.remove_offline("worker-node-a") is False  # online
    worker_node_store.set_status("worker-node-a", WorkerNodeStatus.DRAINING)
    assert worker_node_store.remove_offline("worker-node-a") is False
    worker_node_store.set_status("worker-node-a", WorkerNodeStatus.OFFLINE)
    assert worker_node_store.remove_offline("worker-node-a") is True
    assert worker_node_store.get("worker-node-a") is None
    assert [worker_node.worker_node_id for worker_node in worker_node_store.list_worker_nodes()] == ["worker-node-b"]
    assert worker_node_store.remove_offline("worker-node-a") is None


def test_remove_offline_keeps_the_jobs_the_worker_node_ran(worker_node_store, job_store):
    worker_node_store.register(make_hello("worker-node-a", slots={SCENE: 1}))
    job = job_store.submit(make_submission()).job
    lease = job_store.claim_next("worker-node-a", 30.0)
    job_store.accept(lease.lease_id, 30.0)
    job_store.report_result(JobResult(lease_id=lease.lease_id, job_id=job.job_id, idempotency_key=job.idempotency_key, outcome=JobOutcome.SUCCEEDED, result={}, error=None, retryable=False))
    worker_node_store.set_status("worker-node-a", WorkerNodeStatus.OFFLINE)
    assert worker_node_store.remove_offline("worker-node-a") is True
    finished = job_store.get(job.job_id)
    assert finished.state == JobState.SUCCEEDED and finished.lease_owner is None


def test_remove_offline_refuses_a_worker_node_that_holds_a_lease(worker_node_store, job_store):
    worker_node_store.register(make_hello("worker-node-a", slots={SCENE: 1}))
    job_store.submit(make_submission())
    job_store.claim_next("worker-node-a", 30.0)
    worker_node_store.set_status("worker-node-a", WorkerNodeStatus.OFFLINE)
    assert worker_node_store.remove_offline("worker-node-a") is False
    assert worker_node_store.get("worker-node-a") is not None


def test_a_removed_worker_node_registers_anew(worker_node_store):
    worker_node_store.register(make_hello("worker-node-a", slots={SCENE: 2}))
    worker_node_store.set_status("worker-node-a", WorkerNodeStatus.OFFLINE)
    worker_node_store.remove_offline("worker-node-a")
    worker_node = worker_node_store.register(make_hello("worker-node-a", slots={KINEMATIC: 1}))
    assert worker_node.status == WorkerNodeStatus.ONLINE and worker_node.slots == {KINEMATIC: SlotState(slots=1, slots_in_use=0)}


def test_list_worker_nodes(worker_node_store):
    for worker_node_id in ("worker-node-b", "worker-node-a"):
        worker_node_store.register(make_hello(worker_node_id))
    worker_node_store.set_status("worker-node-b", WorkerNodeStatus.DRAINING)
    assert [worker_node.worker_node_id for worker_node in worker_node_store.list_worker_nodes()] == ["worker-node-a", "worker-node-b"]
    assert [worker_node.worker_node_id for worker_node in worker_node_store.list_worker_nodes(WorkerNodeStatus.DRAINING)] == ["worker-node-b"]
