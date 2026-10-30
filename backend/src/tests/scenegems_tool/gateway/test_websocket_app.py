"""The WebSocket endpoint of the workbench gateway, driven with a scripted socket.

Ported from the old test_websocket_initial_status.py, which patched simulation.backend_service.websocket_app
and expected a `simulation_status` of `offline` first. The gateway now sends the simulation status of the empty
simulation session (`not initialized`) and the WARA-PS connection status when a client connects.

The endpoint function is called directly, without the FastAPI lifespan: the lifespan registers process signal
handlers and shuts down Docker subsystems, which a test must not do.
"""

import json
from typing import List

import pytest
from fastapi import WebSocketDisconnect

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


async def test_initial_simulation_status_is_sent_on_connection():
    socket = await converse()
    assert socket.sent[0] == {"type": "simulation_status", "status": "not initialized"}


async def test_mqtt_broker_status_is_disconnected_on_connection():
    socket = await converse()
    assert any(message["type"] == "mqtt_broker_status" and message["status"] == "disconnected" for message in socket.sent)


async def test_the_session_is_removed_when_the_client_disconnects():
    await converse()
    assert websocket_app.websocket_session_manager._sessions_by_connection == {}


async def test_invalid_json_is_answered_with_an_error():
    socket = await converse("{not json")
    assert {"type": "error", "message": "Invalid JSON message payload."} in socket.sent


async def test_unknown_message_types_are_reported():
    socket = await converse({"type": "make_coffee"})
    assert {"type": "error", "message": "Unknown message type: make_coffee"} in socket.sent


async def test_starting_a_simulation_that_was_never_initialized_is_an_error():
    socket = await converse({"type": "start_simulation"})
    assert {"type": "error", "message": "Simulation is not initialized"} in socket.sent


async def test_an_invalid_simulation_configuration_is_rejected_with_the_reason():
    body = {
        "type": "initialize_simulation",
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


class TestRunRecorder:
    async def test_the_gateway_on_its_own_records_nothing(self, monkeypatch):
        monkeypatch.setattr(websocket_app.app.state, "run_recorder", None)
        assert websocket_app.run_recorder() is None

    async def test_each_connection_gets_the_recorder_the_master_set(self, monkeypatch):
        monkeypatch.setattr(websocket_app.app.state, "run_recorder", None)
        recorder = object()
        websocket_app.set_run_recorder(recorder)
        assert websocket_app.run_recorder() is recorder
        sessions = []
        create_session = websocket_app.websocket_session_manager.create_session

        def created(websocket, live_sessions=True):
            session, processor = create_session(websocket=websocket, live_sessions=live_sessions)
            sessions.append(session)
            return session, processor

        monkeypatch.setattr(websocket_app.websocket_session_manager, "create_session", created)
        await converse()
        (session,) = sessions
        assert session.run_recorder is recorder
