import asyncio
import unittest

from scenegems_tool.waraps_integration.mqtt_session import OldWARAPSSession


class TestMqttSessionTaskLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_stop_runtime_tasks_keeps_status_polling_alive(self):
        session = OldWARAPSSession.__new__(OldWARAPSSession)
        session.control_task = asyncio.create_task(asyncio.sleep(60))
        session.stream_task = asyncio.create_task(asyncio.sleep(60))
        session.status_task = asyncio.create_task(asyncio.sleep(60))
        session.live_trajectory_builder = object()

        status_task = session.status_task
        session.stop_runtime_tasks()

        self.assertIsNone(session.control_task)
        self.assertIsNone(session.stream_task)
        self.assertIs(status_task, session.status_task)
        self.assertFalse(session.status_task.done())
        self.assertIsNone(session.live_trajectory_builder)

        status_task.cancel()
        try:
            await status_task
        except asyncio.CancelledError:
            pass

    def test_start_scenario_raises_if_agents_not_ready(self):
        class DummyAgentClient:
            def __init__(self, vessel):
                self.vessel = vessel
                self.initial_state = type("InitialState", (), {"speed": 3.0})()
                self.follow_path_calls = 0

            def publish_follow_path(self, _waypoints, _speed):
                self.follow_path_calls += 1

        vessel = object()
        client = DummyAgentClient(vessel=vessel)
        parser = type("Parser", (), {"agent_clients": [client], "waypoint_map": {vessel: [{"latitude": 0.0, "longitude": 0.0}]}})()

        session = OldWARAPSSession.__new__(OldWARAPSSession)
        session.simulation_parser = parser
        session.are_agents_at_start_pos = lambda: False

        with self.assertRaises(RuntimeError):
            session.start_scenario()

        self.assertEqual(client.follow_path_calls, 0)

    def test_start_scenario_publishes_paths_if_agents_ready(self):
        class DummyAgentClient:
            def __init__(self, vessel):
                self.vessel = vessel
                self.initial_state = type("InitialState", (), {"speed": 4.5})()
                self.follow_path_calls = 0

            def publish_follow_path(self, _waypoints, _speed):
                self.follow_path_calls += 1

        vessel_1 = object()
        vessel_2 = object()
        client_1 = DummyAgentClient(vessel=vessel_1)
        client_2 = DummyAgentClient(vessel=vessel_2)
        parser = type(
            "Parser",
            (),
            {
                "agent_clients": [client_1, client_2],
                "waypoint_map": {
                    vessel_1: [{"latitude": 1.0, "longitude": 1.0}],
                    vessel_2: [{"latitude": 2.0, "longitude": 2.0}],
                },
            },
        )()

        session = OldWARAPSSession.__new__(OldWARAPSSession)
        session.simulation_parser = parser
        session.are_agents_at_start_pos = lambda: True

        session.start_scenario()

        self.assertEqual(client_1.follow_path_calls, 1)
        self.assertEqual(client_2.follow_path_calls, 1)

    def test_abort_simulation_only_aborts_running_commands(self):
        session = OldWARAPSSession.__new__(OldWARAPSSession)
        calls = []
        session.simulation_parser = object()
        session.abort_all = lambda: calls.append("abort_all")
        session.go_to_start_point = lambda: calls.append("go_to_start")

        session.abort_simulation()

        self.assertEqual(calls, ["abort_all"])

    def test_reset_simulation_aborts_and_goes_to_start(self):
        session = OldWARAPSSession.__new__(OldWARAPSSession)
        calls = []
        session.simulation_parser = object()
        session.abort_all = lambda: calls.append("abort_all")
        session.go_to_start_point = lambda: calls.append("go_to_start")

        session.reset_simulation()

        self.assertEqual(calls, ["abort_all", "go_to_start"])


if __name__ == "__main__":
    unittest.main()
