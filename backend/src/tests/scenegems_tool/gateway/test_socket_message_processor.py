"""SocketMessageProcessor: each helper request is dispatched to the right session call, with errors reported, and nothing else is taken."""

import json
from typing import List, Tuple, get_args, get_type_hints

import pytest

from scenegems_tool.gateway.protocol import ClientMessage
from scenegems_tool.gateway.socket_message_processor import SocketMessageProcessor
from tests.scenegems_tool.gateway.conftest import settle

pytestmark = pytest.mark.anyio

# The messages of the former live session on the control node; a simulation is a job on a worker node now
LIVE_SESSION_MESSAGES = ("connect_to_mqtt_broker", "disconnect_from_mqtt_broker", "initialize_simulation", "start_simulation", "reset_simulation", "initialize_monitor", "shut_down_monitor")


class RecordingSession:
    """Stands in for SocketSession: records every call and error."""

    def __init__(self) -> None:
        self.calls: List[Tuple[str, dict]] = []
        self.errors: List[str] = []
        self.fail_with: Exception | None = None

    def _record(self, name: str, kwargs: dict) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append((name, kwargs))

    def send_runtime_error(self, message: str) -> None:
        self.errors.append(message)

    def set_scenario_session(self, **kwargs) -> None:
        self._record("set_scenario_session", kwargs)

    def generate_simulation_models(self, config) -> None:
        self._record("generate_simulation_models", {"config": config})

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
    "connectionsByAgentId": {"0": {"context": "simulation", "controlMode": "autonomous", "agentName": "os", "topic": "t"}},
}
LOAD = {"type": "load_scenario_file", "scenarioId": "s1", "fileName": "a.json", "filePath": "/a.json", "fileContent": "{}"}


def known_message_types() -> List[str]:
    return [get_args(get_type_hints(annotation)["type"])[0] for annotation in get_args(ClientMessage)]


class TestDispatch:
    async def test_load_scenario_file(self, setup):
        session, processor = setup
        await send(processor, LOAD)
        assert session.calls == [("set_scenario_session", {"scenario_id": "s1", "file_name": "a.json", "file_path": "/a.json", "file_content": "{}"})]

    async def test_generate_simulation_models_converts_the_body_to_a_typed_configuration(self, setup):
        session, processor = setup
        await send(processor, {"type": "generate_simulation_models", **SIMULATION_BODY})
        ((name, kwargs),) = session.calls
        assert name == "generate_simulation_models"
        assert kwargs["config"].simulation_layer.value == "ardupilot_sim"

    async def test_an_invalid_simulation_body_is_reported_and_not_forwarded(self, setup):
        session, processor = setup
        await send(processor, {"type": "generate_simulation_models", **SIMULATION_BODY, "simulatorType": "Webots"})
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
        for message in (LOAD, {"type": "query_stack_options"}, LOAD):
            await processor.inbound_queue.put(message)
        await settle()
        assert session.names() == ["set_scenario_session", "send_payload", "set_scenario_session"]

    def test_the_gateway_takes_three_helper_requests(self):
        assert sorted(known_message_types()) == ["generate_simulation_models", "load_scenario_file", "query_stack_options"]

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

    @pytest.mark.parametrize("message_type", LIVE_SESSION_MESSAGES)
    async def test_an_old_live_session_message_is_refused(self, setup, message_type):
        """The control node runs no live session: it connects no broker and starts no simulation or monitor."""
        session, processor = setup
        await send(processor, {"type": message_type, **SIMULATION_BODY})
        assert session.calls == []
        assert session.errors == [f"Unknown message type: {message_type}"]

    async def test_malformed_scenario_json_is_reported(self, setup):
        session, processor = setup
        session.fail_with = json.JSONDecodeError("bad", "{", 0)
        await send(processor, {**LOAD, "fileContent": "{"})
        assert session.errors == ["Invalid scene file JSON."]

    async def test_scenario_value_errors_are_reported_with_their_text(self, setup):
        session, processor = setup
        session.fail_with = ValueError("no vessels")
        await send(processor, LOAD)
        assert session.errors == ["Failed to load scene: no vessels"]

    @pytest.mark.parametrize("message_type", ["generate_scene", "generate_trajectories", "stop_scene_generation", "stop_trajectory_generation", "monitor_scene"])
    async def test_generation_messages_are_unknown_since_the_cluster_runs_them(self, setup, message_type):
        session, processor = setup
        await send(processor, {"type": message_type})
        assert session.errors == [f"Unknown message type: {message_type}"]

    async def test_a_message_without_its_fields_does_not_stop_the_worker(self, setup):
        session, processor = setup
        await send(processor, {"type": "load_scenario_file"})
        assert session.errors and session.errors[0].startswith("Unhandled message processing error")
        await send(processor, {"type": "query_stack_options"})
        assert session.names() == ["send_payload"]

    async def test_cancel_stops_the_worker(self, setup):
        session, processor = setup
        processor.cancel()
        await settle()
        assert processor.worker_task.cancelled()
        await processor.inbound_queue.put({"type": "query_stack_options"})
        await settle()
        assert session.calls == []
