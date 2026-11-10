"""The live channel's WebSocket on the operator app (memory and -m postgres)."""

from starlette.testclient import TestClient

from scenegems_tool.cluster.control_node.api.control_node_apps import create_control_node_apps, create_operator_app
from scenegems_tool.cluster.control_node.live.topics import WorkerNodesTopic, create_live_channel
from scenegems_tool.cluster.protocol.routes import LIVE_PATH
from tests.scenegems_tool.cluster.control_node.live.fake_broker import FakeBroker
from tests.scenegems_tool.cluster.control_node.live.live_browser import LiveBrowser


def _paths(app):
    return {getattr(route, "path", None) for route in app.routes}


def test_the_live_channel_is_on_the_operator_listener_only(plane):
    apps = create_control_node_apps(plane)
    assert LIVE_PATH in _paths(apps.operator) and LIVE_PATH not in _paths(apps.worker_node_api)


def test_a_browser_subscribes_pings_and_leaves(plane):
    channel = create_live_channel(plane)
    with TestClient(create_operator_app(plane, live=channel)) as client:
        browser = LiveBrowser(client)
        assert browser.subscribe("worker_nodes") == []
        assert channel.subscriber_count("worker_nodes") == 1
        browser.send({"type": "ping"})
        assert browser.receive() == {"version": 1, "type": "pong"}
        browser.close()
        assert channel.topics() == set() and channel.connection_count == 0


def test_the_operator_app_makes_a_channel_on_the_control_plane_when_given_none(plane):
    with TestClient(create_operator_app(plane)) as client:
        browser = LiveBrowser(client)
        assert browser.subscribe("worker_nodes") == []
        assert isinstance(plane.registry.on_change.__self__, WorkerNodesTopic)
        browser.close()


def test_the_operator_listener_closes_the_broker_connection_at_shutdown(plane):
    broker = FakeBroker()
    channel = create_live_channel(plane, broker=lambda: broker)
    with TestClient(create_operator_app(plane, live=channel)) as client:
        browser = LiveBrowser(client)
        browser.send({"type": "subscribe", "topic": "instance:no-such-worker-node/scene_generation-0"})
        assert browser.receive()["type"] == "error"  # the broker was opened for it nonetheless, then the topic left
        browser.close()
    assert broker.started == 1 and broker.filters == [] and broker.stopped == 1
