import unittest
from types import SimpleNamespace

from scenegems_tool.backend_service.protocol import SimulationStatus
from scenegems_tool.backend_service.session import SocketSession


class TestSocketSessionStatus(unittest.TestCase):
    def test_get_simulation_status_returns_offline_when_not_connected(self):
        socket_session = SocketSession(connection_id="test-connection")

        self.assertEqual(socket_session.get_simulation_status(), SimulationStatus.OFFLINE)

    def test_get_simulation_status_returns_ready_or_preparing_when_connected(self):
        socket_session = SocketSession(connection_id="test-connection")
        socket_session.waraps_session = SimpleNamespace(
            is_connected=True,
            get_simulation_status=lambda: SimulationStatus.READY_TO_START,
        )

        self.assertEqual(socket_session.get_simulation_status(), SimulationStatus.READY_TO_START)

        socket_session.waraps_session = SimpleNamespace(
            is_connected=True,
            get_simulation_status=lambda: SimulationStatus.AGENTS_ARE_PREPARING,
        )

        self.assertEqual(socket_session.get_simulation_status(), SimulationStatus.AGENTS_ARE_PREPARING)


if __name__ == "__main__":
    unittest.main()
