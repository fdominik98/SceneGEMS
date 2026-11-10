"""The origin guard: pages of other origins may not post to the operator listener or open its WebSockets."""

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from scenegems_tool.cluster.control_node.api.control_node_apps import create_operator_app
from scenegems_tool.cluster.control_node.api.operator_routes import STATUS_PATH, WORKER_NODES_PATH
from scenegems_tool.cluster.control_node.api.origin_guard import POLICY_VIOLATION
from scenegems_tool.cluster.protocol.routes import LIVE_PATH

UI = "http://localhost:5173"
STRANGER = "https://evil.example"
DRAIN = f"{WORKER_NODES_PATH}/no-such-worker-node/drain"


@pytest.fixture
def operator(memory_plane):
    with TestClient(create_operator_app(memory_plane)) as client:
        yield client


def test_a_post_from_another_origin_is_refused(operator):
    response = operator.post(DRAIN, headers={"Origin": STRANGER})
    assert response.status_code == 403 and response.json() == {"detail": "origin not allowed"}
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize("headers", [{"Origin": UI}, {"Origin": UI + "/"}, {}])
def test_a_post_from_the_ui_or_without_an_origin_reaches_the_route(operator, headers):
    assert operator.post(DRAIN, headers=headers).status_code == 404  # the route ran: the worker node is unknown


def test_a_page_with_a_null_origin_is_refused(operator):
    assert operator.post(DRAIN, headers={"Origin": "null"}).status_code == 403


def test_reads_and_preflights_pass_for_any_origin(operator):
    # CORS keeps the answer of a read from another origin's page; the guard need not refuse it
    response = operator.get(STATUS_PATH, headers={"Origin": STRANGER})
    assert response.status_code == 200 and "access-control-allow-origin" not in response.headers
    preflight = operator.options(DRAIN, headers={"Origin": UI, "Access-Control-Request-Method": "POST"})
    assert preflight.status_code == 200


def test_the_live_channel_refuses_another_origin(operator):
    with pytest.raises(WebSocketDisconnect) as refused:
        with operator.websocket_connect(LIVE_PATH, headers={"Origin": STRANGER}):
            pass
    assert refused.value.code == POLICY_VIOLATION


@pytest.mark.parametrize("headers", [{"Origin": UI}, {}])
def test_the_live_channel_accepts_the_ui_and_programs(operator, headers):
    with operator.websocket_connect(LIVE_PATH, headers=headers) as socket:
        socket.send_json({"version": 1, "type": "ping"})
        assert socket.receive_json() == {"version": 1, "type": "pong"}


def test_the_allowed_origins_are_the_operator_apps(memory_plane):
    with TestClient(create_operator_app(memory_plane, allowed_origins=["https://ui.lab.example"])) as client:
        assert client.post(DRAIN, headers={"Origin": "https://ui.lab.example"}).status_code == 404
        assert client.post(DRAIN, headers={"Origin": UI}).status_code == 403
