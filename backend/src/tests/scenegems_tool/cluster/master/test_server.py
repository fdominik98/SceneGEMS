"""The master's listeners on real sockets: the node API over plain HTTP and WebSocket, with no credential."""

import asyncio
import threading

import pytest
from websockets.asyncio.client import connect

from scenegems_tool.cluster.master.api.master_apps import create_master_apps
from scenegems_tool.cluster.master.server import MAX_NODE_FRAME_BYTES, build_assurance_stores, build_live_channel, build_master, listeners, load_env_file
from scenegems_tool.cluster.master.settings import BrokerClientSettings, Listener, MasterSettings
from scenegems_tool.cluster.protocol.codec import decode_master_message, encode
from scenegems_tool.cluster.protocol.jobs import JobSubmission
from scenegems_tool.cluster.protocol.messages import LeaseOffer, Welcome
from scenegems_tool.cluster.protocol.routes import NODE_CONTROL_PATH
from tests.scenegems_tool.cluster.master.conftest import EXPECTED, SCENE
from tests.scenegems_tool.persistence.stores.builders import make_hello


def _settings(**changes) -> MasterSettings:
    return MasterSettings(master_id="lab-master", database_url="postgresql://unused", node_api=Listener("127.0.0.1", 0), operator=Listener("127.0.0.1", 0), **changes)


def test_the_master_has_two_plain_listeners_on_their_hosts(plane):
    apps = create_master_apps(plane)
    node_api, operator = listeners(_settings(), apps)
    assert node_api.config.ssl_certfile is None and operator.config.ssl_certfile is None
    assert operator.config.ws_ping_interval is None and node_api.config.ws_max_size == MAX_NODE_FRAME_BYTES == 64 * 1024 * 1024
    assert (node_api.config.app, operator.config.app) == (apps.node_api, apps.operator)
    assert len(listeners(_settings(), apps)) == 2  # no broker login hook


@pytest.fixture
def node_api_address(plane):
    """The node API on a real socket; yields its address, host and port."""
    server = listeners(_settings(), create_master_apps(plane, run_timers=True))[0]
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    started = threading.Event()
    for _ in range(200):  # until uvicorn has bound its socket
        if server.started:
            started.set()
            break
        started.wait(0.05)
    assert server.started, "the node API did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_a_node_connects_over_plain_websocket_without_pairing(node_api_address, stores):
    job = stores.jobs.submit(JobSubmission(job_type=SCENE)).job  # queued before the node connects, so its Hello triggers the offer

    async def node_session():
        async with connect(f"ws://{node_api_address}{NODE_CONTROL_PATH}", open_timeout=10) as socket:
            await socket.send(encode(make_hello("plain-node", slots={SCENE: 1}, fingerprints=dict(EXPECTED))))
            return [decode_master_message(await asyncio.wait_for(socket.recv(), 10)) for _ in range(2)]

    welcome, offer = asyncio.run(node_session())
    assert isinstance(welcome, Welcome) and isinstance(offer, LeaseOffer) and offer.job.job_id == job.job_id


def test_the_master_has_one_assurance_stores_shared_with_its_pipeline_engine(plane):
    from sqlalchemy.orm import sessionmaker

    sessions = sessionmaker()
    stores = build_assurance_stores(sessions)
    plane.attach_pipeline(stores)
    assert stores.session_factory is sessions and plane.pipeline.stores is stores


def test_the_live_channel_observes_pools_when_the_cluster_broker_is_known(plane):
    without = build_live_channel(_settings(), plane, None)
    assert not without.producers.hub.broker_configured
    channel = build_live_channel(_settings(broker=BrokerClientSettings("cluster-broker", 1883)), plane, None)
    hub = channel.producers.hub
    assert hub.broker_configured
    client = hub._broker_factory()
    assert (client.host, client.port) == ("cluster-broker", 1883)


def test_an_env_file_fills_only_what_the_environment_lacks(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\nSCENEGEMS_MASTER_ID=from-file\nPOSTGRES_DB='quoted'\n\nnot a line\n", encoding="utf-8")
    environ = {"SCENEGEMS_MASTER_ID": "from-environment"}
    load_env_file(env_file, environ)
    assert environ == {"SCENEGEMS_MASTER_ID": "from-environment", "POSTGRES_DB": "quoted"}


def test_the_master_hands_the_gateway_a_recorder_of_live_sessions(tmp_path, monkeypatch):
    from scenegems_tool.cluster.master.settings import ArtifactSettings
    from scenegems_tool.gateway import websocket_app
    from scenegems_tool.gateway.live_run_recorder import LiveRunRecorder

    monkeypatch.setattr(websocket_app.app.state, "run_recorder", None)
    settings = _settings(artifacts=ArtifactSettings(folder=tmp_path, max_bytes=1024))
    build_master(settings, with_gateway=False)
    assert websocket_app.run_recorder() is None  # without the gateway nothing is recorded
    build_master(settings)
    recorder = websocket_app.run_recorder()
    assert isinstance(recorder, LiveRunRecorder) and recorder.pipeline is not None and recorder.pipeline.stores is recorder.stores
    assert recorder.max_bytes == 1024 and recorder.artifacts.store.root == tmp_path and recorder._announce is not None


def test_the_master_turns_the_gateway_s_live_sessions_off_when_told(monkeypatch):
    from starlette.testclient import TestClient

    from scenegems_tool.cluster.master.api.operator_routes import STATUS_PATH
    from scenegems_tool.gateway import websocket_app

    monkeypatch.setattr(websocket_app.app.state, "live_sessions", True)
    monkeypatch.setattr(websocket_app.app.state, "run_recorder", None)
    apps = build_master(_settings(live_sessions=False))
    assert websocket_app.live_sessions() is False
    client = TestClient(apps.operator)  # no lifespan: the gateway's installs signal handlers
    assert client.get(STATUS_PATH).json()["live_sessions"] is False
    assert client.get("/health").json() == {"status": "ok"}
    build_master(_settings())
    assert websocket_app.live_sessions() is True
    without_gateway = build_master(_settings(), with_gateway=False)
    client = TestClient(without_gateway.operator)
    assert client.get(STATUS_PATH).json()["live_sessions"] is False
    assert client.get("/health").status_code == 200
