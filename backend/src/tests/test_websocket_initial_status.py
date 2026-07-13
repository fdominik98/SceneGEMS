import unittest

from fastapi import WebSocketDisconnect

import simulation.backend_service.websocket_app as websocket_app
from scenegems_tool.backend_service.protocol import SimulationStatus
from scenegems_tool.backend_service.websocket_app import backend_service_socket


class _FakeWebSocket:
    def __init__(self):
        self.sent_payloads = []

    async def accept(self) -> None:
        return

    async def send_json(self, payload) -> None:
        self.sent_payloads.append(payload)

    async def receive_text(self) -> str:
        raise WebSocketDisconnect()


class _FakeSession:
    def __init__(self):
        self.session_id = "test-session-id"

    def get_simulation_status(self) -> SimulationStatus:
        return SimulationStatus.OFFLINE

    def cancel(self) -> None:
        return


class TestWebsocketInitialStatus(unittest.IsolatedAsyncioTestCase):
    async def test_initial_simulation_status_is_sent_on_connection(self):
        fake_ws = _FakeWebSocket()
        fake_session = _FakeSession()
        manager = websocket_app.websocket_session_manager
        original_create_session = manager.create_session
        original_remove_session = manager.remove_session

        def _fake_create_session(*_args: object, **_kwargs: object) -> object:
            return fake_session

        manager.create_session = _fake_create_session  # type: ignore[method-assign]
        manager.remove_session = lambda _connection_id: None  # type: ignore[method-assign]
        try:
            await backend_service_socket(fake_ws)
        finally:
            manager.create_session = original_create_session  # type: ignore[method-assign]
            manager.remove_session = original_remove_session  # type: ignore[method-assign]

        self.assertGreaterEqual(len(fake_ws.sent_payloads), 1)
        self.assertEqual(fake_ws.sent_payloads[0]["type"], "simulation_status")
        self.assertEqual(fake_ws.sent_payloads[0]["status"], "offline")


if __name__ == "__main__":
    unittest.main()
