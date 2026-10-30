import pytest

from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobState, JobType
from scenegems_tool.cluster.protocol.messages import Heartbeat, JobResult
from scenegems_tool.persistence.schema import NodeStatus
from scenegems_tool.persistence.stores import SlotState
from tests.scenegems_tool.persistence.stores.builders import START, make_hello, make_resources, make_submission

pytestmark = pytest.mark.postgres

SCENE = JobType.SCENE_GENERATION
KINEMATIC = JobType.SIMULATION


def test_register_creates_an_online_node(node_store):
    hello = make_hello("node-a", slots={SCENE: 2, KINEMATIC: 4}, labels={"site": "lab"}, fingerprints={"scenegems-scene-generation": "f1"}, components=["scene_generation", "control_layer/none"])
    node = node_store.register(hello)
    assert node.status == NodeStatus.ONLINE
    assert node.name == "node-a-host"
    assert node.labels == {"site": "lab"}
    assert node.slots == {SCENE: SlotState(slots=2, slots_in_use=0), KINEMATIC: SlotState(slots=4, slots_in_use=0)}
    assert node.components == ("control_layer/none", "scene_generation")
    assert node.fingerprints == {"scenegems-scene-generation": "f1"}
    assert node.registered_at == node.last_seen_at == START
    assert node_store.get("node-a") == node


def test_register_again_replaces_slots_components_and_fingerprints(node_store, clock):
    node_store.register(make_hello("node-a", slots={SCENE: 2, KINEMATIC: 4}, fingerprints={"old-image": "f0", "kept-image": "f1"}))
    clock.advance(60)
    node = node_store.register(make_hello("node-a", slots={KINEMATIC: 1}, fingerprints={"kept-image": "f2"}, name="renamed", components=["simulation_layer/kinematic"]))
    assert node.slots == {KINEMATIC: SlotState(slots=1, slots_in_use=0)}
    assert node.components == ("simulation_layer/kinematic",)
    assert node.fingerprints == {"kept-image": "f2"}
    assert node.name == "renamed"
    assert node.registered_at == START
    assert node.last_seen_at == clock.now


def test_register_stores_the_machine_and_the_latest_hello_wins(node_store):
    assert node_store.register(make_hello("node-a")).machine is None
    assert node_store.register(make_hello("node-a", machine="lab-pc-3")).machine == "lab-pc-3"
    assert node_store.get("node-a").machine == "lab-pc-3"
    assert node_store.list_nodes()[0].machine == "lab-pc-3"
    assert node_store.heartbeat("node-a", Heartbeat(resources=make_resources())).machine == "lab-pc-3"
    assert node_store.register(make_hello("node-a", machine="lab-pc-4")).machine == "lab-pc-4"
    assert node_store.register(make_hello("node-a")).machine is None


def test_register_keeps_a_drain(node_store):
    node_store.register(make_hello("node-a"))
    node_store.set_status("node-a", NodeStatus.DRAINING)
    assert node_store.register(make_hello("node-a")).status == NodeStatus.DRAINING


def test_register_brings_an_offline_node_online(node_store):
    node_store.register(make_hello("node-a"))
    node_store.set_status("node-a", NodeStatus.OFFLINE)
    assert node_store.register(make_hello("node-a")).status == NodeStatus.ONLINE


def test_heartbeat_records_resources_and_slot_usage(node_store, clock):
    node_store.register(make_hello("node-a", slots={SCENE: 2, KINEMATIC: 4}))
    clock.advance(5)
    node = node_store.heartbeat("node-a", Heartbeat(resources=make_resources(free_memory_mb=3000), slots_in_use={KINEMATIC: 3}))
    assert node.last_seen_at == clock.now
    assert node.resources.free_memory_mb == 3000
    assert node.slots == {SCENE: SlotState(slots=2, slots_in_use=0), KINEMATIC: SlotState(slots=4, slots_in_use=3)}


def test_heartbeat_of_an_unknown_node(node_store):
    assert node_store.heartbeat("ghost", Heartbeat(resources=make_resources())) is None


def test_heartbeat_brings_an_offline_node_online_but_keeps_a_drain(node_store):
    node_store.register(make_hello("node-a"))
    node_store.register(make_hello("node-b"))
    node_store.set_status("node-a", NodeStatus.OFFLINE)
    node_store.set_status("node-b", NodeStatus.DRAINING)
    assert node_store.heartbeat("node-a", Heartbeat(resources=make_resources())).status == NodeStatus.ONLINE
    assert node_store.heartbeat("node-b", Heartbeat(resources=make_resources())).status == NodeStatus.DRAINING


def test_set_status_of_an_unknown_node(node_store):
    assert node_store.set_status("ghost", NodeStatus.DRAINING) is None


def test_silent_nodes_go_offline(node_store, clock):
    node_store.register(make_hello("node-a"))
    node_store.register(make_hello("node-b"))
    node_store.register(make_hello("node-c"))
    node_store.set_status("node-c", NodeStatus.DRAINING)
    clock.advance(20)
    node_store.heartbeat("node-b", Heartbeat(resources=make_resources()))
    clock.advance(15)
    # node-a and node-c last seen 35 s ago, node-b 15 s ago
    assert node_store.mark_silent_nodes_offline(30) == ["node-a", "node-c"]
    assert node_store.mark_silent_nodes_offline(30) == []
    assert [node.node_id for node in node_store.list_nodes(NodeStatus.OFFLINE)] == ["node-a", "node-c"]
    assert node_store.get("node-b").status == NodeStatus.ONLINE


def test_remove_offline_deletes_only_an_offline_node(node_store):
    node_store.register(make_hello("node-a", slots={SCENE: 2}, fingerprints={"image": "f1"}))
    node_store.register(make_hello("node-b"))
    assert node_store.remove_offline("node-a") is False  # online
    node_store.set_status("node-a", NodeStatus.DRAINING)
    assert node_store.remove_offline("node-a") is False
    node_store.set_status("node-a", NodeStatus.OFFLINE)
    assert node_store.remove_offline("node-a") is True
    assert node_store.get("node-a") is None
    assert [node.node_id for node in node_store.list_nodes()] == ["node-b"]
    assert node_store.remove_offline("node-a") is None


def test_remove_offline_keeps_the_jobs_the_node_ran(node_store, job_store):
    node_store.register(make_hello("node-a", slots={SCENE: 1}))
    job = job_store.submit(make_submission()).job
    lease = job_store.claim_next("node-a", 30.0)
    job_store.accept(lease.lease_id, 30.0)
    job_store.report_result(JobResult(lease_id=lease.lease_id, job_id=job.job_id, idempotency_key=job.idempotency_key, outcome=JobOutcome.SUCCEEDED, result={}, error=None, retryable=False))
    node_store.set_status("node-a", NodeStatus.OFFLINE)
    assert node_store.remove_offline("node-a") is True
    finished = job_store.get(job.job_id)
    assert finished.state == JobState.SUCCEEDED and finished.lease_owner is None


def test_remove_offline_refuses_a_node_that_holds_a_lease(node_store, job_store):
    node_store.register(make_hello("node-a", slots={SCENE: 1}))
    job_store.submit(make_submission())
    job_store.claim_next("node-a", 30.0)
    node_store.set_status("node-a", NodeStatus.OFFLINE)
    assert node_store.remove_offline("node-a") is False
    assert node_store.get("node-a") is not None


def test_a_removed_node_registers_anew(node_store):
    node_store.register(make_hello("node-a", slots={SCENE: 2}))
    node_store.set_status("node-a", NodeStatus.OFFLINE)
    node_store.remove_offline("node-a")
    node = node_store.register(make_hello("node-a", slots={KINEMATIC: 1}))
    assert node.status == NodeStatus.ONLINE and node.slots == {KINEMATIC: SlotState(slots=1, slots_in_use=0)}


def test_list_nodes(node_store):
    for node_id in ("node-b", "node-a"):
        node_store.register(make_hello(node_id))
    node_store.set_status("node-b", NodeStatus.DRAINING)
    assert [node.node_id for node in node_store.list_nodes()] == ["node-a", "node-b"]
    assert [node.node_id for node in node_store.list_nodes(NodeStatus.DRAINING)] == ["node-b"]
