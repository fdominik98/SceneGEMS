"""SocketMessageProcessor: each client message type is dispatched to the right session call, with errors reported."""

import json
from types import SimpleNamespace
from typing import List, Tuple, get_args, get_type_hints

import pytest

from scenegems_tool.gateway.protocol import ClientMessage
from scenegems_tool.gateway.socket_message_processor import LIVE_SESSION_MESSAGES, SocketMessageProcessor
from tests.scenegems_tool.gateway.conftest import settle

pytestmark = pytest.mark.anyio


class RecordingSession:
    """Stands in for SocketSession: records every call and error."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, dict]] = []
        self.errors: List[str] = []
        self.fail_with: Exception | None = None
        integration = SimpleNamespace()
        integration.simulation_session = SimpleNamespace(start_simulation_runtime=lambda: self._record("start_simulation_runtime", {}))
        integration.reset_simulation_session_async = self._async("reset_simulation_session_async")
        self.subsystem_integration_session = integration

    def _record(self, name: str, kwargs: dict) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append((name, kwargs))

    def _async(self, name: str):
        async def call() -> None:
            self._record(name, {})

        return call

    def send_runtime_error(self, message: str) -> None:
        self.errors.append(message)

    def set_scenario_session(self, **kwargs) -> None:
        self._record("set_scenario_session", kwargs)

    async def connect_to_mqtt_broker(self, **kwargs) -> None:
        self._record("connect_to_mqtt_broker", kwargs)

    def disconnect_from_mqtt_broker(self) -> None:
        self._record("disconnect_from_mqtt_broker", {})

    def set_simulation_session(self, config) -> None:
        self._record("set_simulation_session", {"config": config})

    def generate_simulation_models(self, config) -> None:
        self._record("generate_simulation_models", {"config": config})

    def set_monitor_session(self, *args) -> None:
        self._record("set_monitor_session", {"args": args})

    def shut_down_monitor(self) -> None:
        self._record("shut_down_monitor", {})

    def send_payload(self, payload) -> None:
        self._record("send_payload", payload)

    def names(self) -> List[str]:
        return [name for name, _ in self.calls]


@pytest.fixture
async def setup():
    session = RecordingSession()
    processor = SocketMessageProcessor(session)  # type: ignore[arg-type]
    yield session, processor
    processor.cancel()


async def send(processor: SocketMessageProcessor, message: dict) -> None:
    await processor.inbound_queue.put(message)
    await settle()


SIMULATION_BODY = {
    "simulatorType": "ArduPilot Sim",
    "windVector": [0, 0, 0],
    "wave": {"amplitude": 0, "period": 0, "steepness": 0, "direction": [0, 0]},
    "simulationSpeed": 1,
    "connectionsByAgentId": {"0": {"context": "simulation", "controlMode": "autonomous", "agentName": "os", "topic": "t", "port": 14550}},
}


def known_message_types() -> List[str]:
    return [get_args(get_type_hints(annotation)["type"])[0] for annotation in get_args(ClientMessage)]


class TestDispatch:
    async def test_load_scenario_file(self, setup):
        session, processor = setup
        await send(processor, {"type": "load_scenario_file", "scenarioId": "s1", "fileName": "a.json", "filePath": "/a.json", "fileContent": "{}"})
        assert session.calls == [("set_scenario_session", {"scenario_id": "s1", "file_name": "a.json", "file_path": "/a.json", "file_content": "{}"})]

    async def test_connect_to_mqtt_broker_builds_the_geofence(self, setup):
        session, processor = setup
        await send(
            processor,
            {
                "type": "connect_to_mqtt_broker",
                "user": "u",
                "password": "p",
                "agent_broker": "ab",
                "client_broker": "cb",
                "port": 8883,
                "tls_connection": True,
                "allow_certificates": False,
                "geofence": {"latitude": 57.7, "longitude": 16.6, "radius_meters": 2000},
            },
        )
        ((name, kwargs),) = session.calls
        assert name == "connect_to_mqtt_broker"
        assert (kwargs["user"], kwargs["port"], kwargs["tls_connection"]) == ("u", 8883, True)
        assert (kwargs["reference_geofence"].latitude, kwargs["reference_geofence"].radius_meters) == (57.7, 2000.0)
        assert kwargs["use_master_broker"] is False

    async def test_connect_to_the_master_broker(self, setup):
        session, processor = setup
        await send(
            processor,
            {
                "type": "connect_to_mqtt_broker",
                "user": "",
                "password": "",
                "agent_broker": "",
                "client_broker": "",
                "port": 1883,
                "tls_connection": False,
                "allow_certificates": False,
                "geofence": {"latitude": 57.7, "longitude": 16.6, "radius_meters": 2000},
                "use_master_broker": True,
            },
        )
        ((name, kwargs),) = session.calls
        assert name == "connect_to_mqtt_broker"
        assert kwargs["use_master_broker"] is True

    async def test_disconnect_and_monitor_commands(self, setup):
        session, processor = setup
        await send(processor, {"type": "disconnect_from_mqtt_broker"})
        await send(processor, {"type": "initialize_monitor", "name": "m", "topic": "t", "scope": "s", "colregsConstraintsContent": "c"})
        await send(processor, {"type": "shut_down_monitor"})
        assert session.names() == ["disconnect_from_mqtt_broker", "set_monitor_session", "shut_down_monitor"]
        assert session.calls[1][1]["args"] == ("m", "t", "s", "c")

    async def test_start_simulation_goes_to_the_simulation_session(self, setup):
        session, processor = setup
        await send(processor, {"type": "start_simulation"})
        assert session.names() == ["start_simulation_runtime"]

    async def test_reset_simulation_runs_in_the_background(self, setup):
        session, processor = setup
        await send(processor, {"type": "reset_simulation"})
        assert session.names() == ["reset_simulation_session_async"]

    async def test_initialize_simulation_converts_the_body_to_a_typed_configuration(self, setup):
        session, processor = setup
        await send(processor, {"type": "initialize_simulation", **SIMULATION_BODY})
        ((name, kwargs),) = session.calls
        assert name == "set_simulation_session"
        assert kwargs["config"].simulation_layer.value == "ardupilot_sim"

    async def test_generate_simulation_models_converts_the_body_too(self, setup):
        session, processor = setup
        await send(processor, {"type": "generate_simulation_models", **SIMULATION_BODY})
        assert session.names() == ["generate_simulation_models"]

    @pytest.mark.parametrize("message_type", ["initialize_simulation", "generate_simulation_models"])
    async def test_invalid_simulation_bodies_are_reported_and_not_forwarded(self, setup, message_type):
        session, processor = setup
        await send(processor, {"type": message_type, **SIMULATION_BODY, "simulatorType": "Webots"})
        assert session.calls == []
        assert session.errors == ["Invalid simulation configuration: Unknown simulatorType 'Webots'; expected one of Gazebo, ArduPilot Sim, Kinematic."]

    async def test_the_stack_options_are_answered_from_the_resolver(self, setup):
        session, processor = setup
        await send(processor, {"type": "query_stack_options"})
        ((name, payload),) = session.calls
        assert name == "send_payload" and payload["type"] == "stack_options"
        assert len(payload["combinations"]) == 64
        assert "Real vessel" not in payload["simulatorTypes"]

    async def test_messages_are_handled_in_order(self, setup):
        session, processor = setup
        for message_type in ("disconnect_from_mqtt_broker", "shut_down_monitor", "disconnect_from_mqtt_broker"):
            await processor.inbound_queue.put({"type": message_type})
        await settle()
        assert session.names() == ["disconnect_from_mqtt_broker", "shut_down_monitor", "disconnect_from_mqtt_broker"]

    @pytest.mark.parametrize("message_type", known_message_types())
    async def test_every_client_message_type_is_known_to_the_processor(self, setup, message_type):
        session, processor = setup
        await send(processor, {"type": message_type})
        assert not any(error.startswith("Unknown message type") for error in session.errors), message_type


class TestErrors:
    async def test_unknown_message_types_are_reported(self, setup):
        session, processor = setup
        await send(processor, {"type": "make_coffee"})
        assert session.errors == ["Unknown message type: make_coffee"]

    async def test_malformed_scenario_json_is_reported(self, setup):
        session, processor = setup
        session.fail_with = json.JSONDecodeError("bad", "{", 0)
        await send(processor, {"type": "load_scenario_file", "scenarioId": "s", "fileName": "f", "filePath": "p", "fileContent": "{"})
        assert session.errors == ["Invalid scene file JSON."]

    async def test_scenario_value_errors_are_reported_with_their_text(self, setup):
        session, processor = setup
        session.fail_with = ValueError("no vessels")
        await send(processor, {"type": "load_scenario_file", "scenarioId": "s", "fileName": "f", "filePath": "p", "fileContent": "{}"})
        assert session.errors == ["Failed to load scene: no vessels"]

    async def test_a_failed_broker_connection_names_the_broker_and_the_reason(self, setup):
        session, processor = setup
        session.fail_with = TimeoutError("No CONNACK")
        await send(
            processor,
            {
                "type": "connect_to_mqtt_broker",
                "user": "u",
                "password": "p",
                "agent_broker": "a",
                "client_broker": "broker.example",
                "port": 1883,
                "tls_connection": False,
                "allow_certificates": False,
                "geofence": {"latitude": 0, "longitude": 0, "radius_meters": 1},
            },
        )
        assert session.errors == ["Failed to connect to MQTT broker broker.example:1883. No CONNACK"]

    @pytest.mark.parametrize("message_type", ["generate_scene", "generate_trajectories", "stop_scene_generation", "stop_trajectory_generation", "monitor_scene"])
    async def test_generation_messages_are_unknown_since_the_cluster_runs_them(self, setup, message_type):
        session, processor = setup
        await send(processor, {"type": message_type})
        assert session.errors == [f"Unknown message type: {message_type}"]

    async def test_background_command_failures_are_reported(self, setup):
        session, processor = setup
        session.fail_with = RuntimeError("down")
        await send(processor, {"type": "reset_simulation"})
        assert session.errors == ["Failed to reset simulation: down"]

    async def test_a_message_without_its_fields_does_not_stop_the_worker(self, setup):
        session, processor = setup
        await send(processor, {"type": "load_scenario_file"})
        assert session.errors and session.errors[0].startswith("Unhandled message processing error")
        await send(processor, {"type": "disconnect_from_mqtt_broker"})
        assert session.names() == ["disconnect_from_mqtt_broker"]

    async def test_cancel_stops_the_worker(self, setup):
        session, processor = setup
        processor.cancel()
        await settle()
        assert processor.worker_task.cancelled()
        await processor.inbound_queue.put({"type": "disconnect_from_mqtt_broker"})
        await settle()
        assert session.calls == []


class TestLiveSessionsOff:
    @pytest.fixture
    async def off(self):
        session = RecordingSession()
        processor = SocketMessageProcessor(session, live_sessions=False)  # type: ignore[arg-type]
        yield session, processor
        processor.cancel()

    @pytest.mark.parametrize("message_type", sorted(LIVE_SESSION_MESSAGES))
    async def test_the_messages_that_start_containers_are_refused_with_the_reason(self, off, message_type):
        session, processor = off
        await send(processor, {"type": message_type})
        assert session.calls == []
        (error,) = session.errors
        assert error.startswith("Live sessions are off on this master") and message_type in error and "docker-compose.live-sessions.yml" in error

    async def test_everything_else_still_works(self, off):
        session, processor = off
        await send(processor, {"type": "load_scenario_file", "scenarioId": "s1", "fileName": "a.json", "filePath": "/a.json", "fileContent": "{}"})
        await send(processor, {"type": "query_stack_options"})
        assert session.names() == ["set_scenario_session", "send_payload"] and session.errors == []

    def test_the_refused_messages_are_client_messages(self):
        assert LIVE_SESSION_MESSAGES <= set(known_message_types())
