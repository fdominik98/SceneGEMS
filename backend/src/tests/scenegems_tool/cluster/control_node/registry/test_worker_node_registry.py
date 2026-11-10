import anyio
import pytest

from scenegems_tool.cluster.control_node.registry.worker_node_registry import CLOSE_REPLACED, CLOSE_SILENT, WorkerNodeRegistry
from scenegems_tool.cluster.control_node.registry.worker_node_session import WorkerNodeSession
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.messages import Drain, Heartbeat
from scenegems_tool.persistence.schema import WorkerNodeStatus
from tests.scenegems_tool.cluster.control_node.conftest import EXPECTED
from tests.scenegems_tool.cluster.control_node.fake_socket import RecordingSocket
from tests.scenegems_tool.cluster.control_node.fake_stores import InMemoryWorkerNodeStore
from tests.scenegems_tool.persistence.stores.builders import ManualClock, make_hello, make_resources


@pytest.fixture
def clock():
    return ManualClock()


@pytest.fixture
def worker_nodes(clock):
    return InMemoryWorkerNodeStore(clock)


@pytest.fixture
def registry(worker_nodes):
    return WorkerNodeRegistry(worker_nodes, worker_node_offline_after_s=15.0)


def _connect(registry, clock, worker_node_id, fingerprints=None) -> WorkerNodeSession:
    async def connect():
        record = await registry.register(make_hello(worker_node_id, slots={JobType.SCENE_GENERATION: 1}, fingerprints=dict(EXPECTED) if fingerprints is None else fingerprints))
        session = WorkerNodeSession(worker_node_id=worker_node_id, socket=RecordingSocket(), record=record, connected_at=clock.now, ready=True)
        await registry.connect(session)
        return session

    return anyio.run(connect)


def test_sessions_are_listed_once_ready_and_until_closed(registry, clock):
    a = _connect(registry, clock, "worker-node-a")
    b = _connect(registry, clock, "worker-node-b")
    assert registry.connected() == [a, b]
    b.ready = False
    assert registry.connected() == [a]
    a.closed = True
    assert registry.connected() == []


def test_a_newer_connection_replaces_the_older(registry, clock):
    old = _connect(registry, clock, "worker-node-a")
    old.leases["lease-1"] = "job-1"
    new = _connect(registry, clock, "worker-node-a")
    assert registry.session("worker-node-a") is new
    assert old.replaced and old.leases == {} and old.socket.closed_with == CLOSE_REPLACED
    assert registry.disconnect(old) is False and registry.session("worker-node-a") is new
    assert registry.disconnect(new) is True and registry.session("worker-node-a") is None


def test_heartbeats_update_the_worker_node_and_bring_it_back_online(registry, worker_nodes, clock):
    session = _connect(registry, clock, "worker-node-a")
    worker_nodes.set_status("worker-node-a", WorkerNodeStatus.OFFLINE)
    clock.advance(5)
    anyio.run(registry.heartbeat, session, Heartbeat(resources=make_resources(free_memory_mb=777)))
    assert session.record.status == WorkerNodeStatus.ONLINE and session.record.resources.free_memory_mb == 777
    assert session.record.last_seen_at == clock.now


def test_silent_worker_nodes_go_offline_and_are_disconnected(registry, clock):
    quiet = _connect(registry, clock, "worker-node-quiet")
    talking = _connect(registry, clock, "worker-node-talking")
    clock.advance(10)
    anyio.run(registry.heartbeat, talking, Heartbeat(resources=make_resources()))
    clock.advance(5)
    assert anyio.run(registry.sweep_silent) == []  # 15 s is not more than 15 s
    clock.advance(0.1)
    assert anyio.run(registry.sweep_silent) == ["worker-node-quiet"]
    assert quiet.socket.closed_with == CLOSE_SILENT and talking.socket.closed_with is None
    assert registry.connected() == [talking]


def test_drain_tells_the_worker_node_and_resume_ends_it(registry, worker_nodes, clock):
    session = _connect(registry, clock, "worker-node-a")
    record = anyio.run(registry.drain, "worker-node-a", "maintenance")
    assert record.status == WorkerNodeStatus.DRAINING and session.record.status == WorkerNodeStatus.DRAINING
    assert session.socket.of_type(Drain) == [Drain(reason="maintenance")]
    assert anyio.run(registry.resume, "worker-node-a").status == WorkerNodeStatus.ONLINE
    assert session.record.status == WorkerNodeStatus.ONLINE


def test_resume_leaves_an_offline_worker_node_offline(registry, worker_nodes, clock):
    _connect(registry, clock, "worker-node-a")
    worker_nodes.set_status("worker-node-a", WorkerNodeStatus.OFFLINE)
    assert anyio.run(registry.resume, "worker-node-a").status == WorkerNodeStatus.OFFLINE
    assert anyio.run(registry.drain, "nobody", "x") is None and anyio.run(registry.resume, "nobody") is None


def test_remove_forgets_an_offline_worker_node_and_tells_the_listener(registry, worker_nodes, clock):
    changed = []
    registry.on_change = changed.append
    session = _connect(registry, clock, "worker-node-a")
    changed.clear()
    assert anyio.run(registry.remove, "worker-node-a") is False  # connected
    worker_nodes.set_status("worker-node-a", WorkerNodeStatus.OFFLINE)
    assert anyio.run(registry.remove, "worker-node-a") is False  # still has its control link
    registry.disconnect(session)
    changed.clear()
    assert anyio.run(registry.remove, "worker-node-a") is True
    assert changed == ["worker-node-a"] and worker_nodes.get("worker-node-a") is None
    assert anyio.run(registry.remove, "worker-node-a") is None
    assert anyio.run(registry.remove, "nobody") is None


def test_remove_refuses_an_online_worker_node_without_a_link(registry, worker_nodes, clock):
    session = _connect(registry, clock, "worker-node-a")
    registry.disconnect(session)
    assert anyio.run(registry.remove, "worker-node-a") is False and worker_nodes.get("worker-node-a") is not None


def test_out_of_date_is_recomputed_against_the_expected_set(registry, clock):
    session = _connect(registry, clock, "worker-node-a", fingerprints={})
    assert registry.refresh_out_of_date(session, None) == frozenset()  # nothing to compare with yet
    stale = registry.refresh_out_of_date(session, EXPECTED)
    assert stale == session.stale_components and "scene_generation" in stale and session.out_of_date[0].missing
    assert "control_layer/none" not in stale and "control_layer/none" in session.usable_components, "a component without images is never stale"
    assert registry.refresh_out_of_date(session, {}) == frozenset() and session.out_of_date == [] and session.stale_components == frozenset()
