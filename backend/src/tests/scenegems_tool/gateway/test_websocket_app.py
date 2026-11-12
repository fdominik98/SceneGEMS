"""The WebSocket endpoint of the workbench gateway, driven with a scripted socket.

The endpoint function is called directly; the lifespan is tested apart with its folder creation replaced.
"""

import json
from typing import List

import pytest
from fastapi import FastAPI, WebSocketDisconnect

from scenegems_tool.gateway import websocket_app
from tests.scenegems_tool.gateway.conftest import FakeWebSocket, settle

pytestmark = pytest.mark.anyio


class ScriptedWebSocket(FakeWebSocket):
    """Delivers the scripted texts, then disconnects like a browser that closed the tab."""

    def __init__(self, texts: List[str]) -> None:
        super().__init__()
        self.texts = list(texts)
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        if self.texts:
            return self.texts.pop(0)
        await settle()  # the outbound queue is flushed before the client goes away
        raise WebSocketDisconnect()


async def converse(*messages) -> ScriptedWebSocket:
    socket = ScriptedWebSocket([message if isinstance(message, str) else json.dumps(message) for message in messages])
    await websocket_app.backend_service_socket(socket)
    return socket


@pytest.fixture(autouse=True)
def clean_manager():
    yield
    websocket_app.websocket_session_manager.shutdown_all()


async def test_the_connection_is_accepted():
    assert (await converse()).accepted


async def test_nothing_is_sent_until_the_console_asks():
    """The gateway has no broker, simulation or monitor to report on: it only answers its helper requests."""
    assert (await converse()).sent == []


async def test_the_session_is_removed_when_the_client_disconnects():
    await converse()
    assert websocket_app.websocket_session_manager._sessions_by_connection == {}


async def test_invalid_json_is_answered_with_an_error():
    socket = await converse("{not json")
    assert {"type": "error", "message": "Invalid JSON message payload."} in socket.sent


async def test_unknown_message_types_are_reported():
    socket = await converse({"type": "make_coffee"})
    assert {"type": "error", "message": "Unknown message type: make_coffee"} in socket.sent


async def test_the_stack_options_are_answered():
    socket = await converse({"type": "query_stack_options"})
    assert [message["type"] for message in socket.sent] == ["stack_options"]


@pytest.mark.parametrize("message_type", ["connect_to_mqtt_broker", "initialize_simulation", "start_simulation", "initialize_monitor"])
async def test_an_old_live_session_message_is_refused(message_type):
    socket = await converse({"type": message_type})
    assert socket.sent == [{"type": "error", "message": f"Unknown message type: {message_type}"}], "the control node runs no live session"


async def test_an_invalid_simulation_configuration_is_rejected_with_the_reason():
    body = {
        "type": "generate_simulation_models",
        "simulatorType": "Webots",
        "windVector": [0, 0, 0],
        "wave": {"amplitude": 0, "period": 0, "steepness": 0, "direction": [0, 0]},
        "simulationSpeed": 1,
        "connectionsByAgentId": {},
    }
    socket = await converse(body)
    errors = [payload["message"] for payload in socket.sent if payload["type"] == "error"]
    assert errors and errors[0].startswith("Invalid simulation configuration: Unknown simulatorType 'Webots'")


def test_health_endpoint():
    assert websocket_app.health() == {"status": "ok"}


def test_the_gateway_has_nothing_to_do_with_docker_or_recording():
    """It starts no container, so it installs no handler that removes any, and records no run."""
    for name in ("shutdown_all_docker_subsystems", "_register_process_shutdown_handlers", "set_run_recorder", "set_live_sessions"):
        assert not hasattr(websocket_app, name), name


class TestStartup:
    async def test_the_lifespan_makes_the_folders_and_ends_every_session(self, monkeypatch):
        calls = []
        monkeypatch.setattr(websocket_app, "ensure_directories", lambda: calls.append("folders"))
        monkeypatch.setattr(websocket_app.websocket_session_manager, "shutdown_all", lambda: calls.append("sessions ended"))
        async with websocket_app.lifespan(FastAPI()):
            assert calls == ["folders"]
        assert calls == ["folders", "sessions ended"]
