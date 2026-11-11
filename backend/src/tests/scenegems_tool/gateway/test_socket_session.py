"""SocketSession: one console's connection to the workbench gateway, which loads a scenario and answers helper requests and runs nothing."""

import json
from types import SimpleNamespace

import pytest

from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from scenegems_tool.gateway import socket_session
from scenegems_tool.gateway.socket_session import SocketSession
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.workbench.scenario_session import ScenarioSession
from tests.scenegems_tool.gateway.conftest import settle
from tests.scenegems_tool.vessel_stack.scenarios import encounter_scene, encounter_trajectories, stack_instance

pytestmark = pytest.mark.anyio


@pytest.fixture
async def session(websocket):
    session = SocketSession(websocket)
    yield session
    session.cancel()


def types_sent(websocket):
    return [payload["type"] for payload in websocket.sent]


def errors(websocket):
    return [payload["message"] for payload in websocket.sent if payload["type"] == "error"]


def scene_file() -> str:
    return json.dumps(EvaluationData(best_scene=encounter_scene("head_on"), timeout=1, random_seed=3).to_dict())


def trajectory_file(timespan: int = 30) -> str:
    return json.dumps({"trajectories": encounter_trajectories("head_on", timespan).to_dict(), "algorithm_desc": "straight"})


class TestInitialState:
    async def test_starts_without_a_scenario_and_sends_nothing(self, session, websocket):
        await settle()
        assert session.scenario_session is None
        assert websocket.sent == [], "the gateway has no broker, simulation or monitor whose status it could report"

    async def test_the_session_holds_no_broker_or_subsystem_session(self, session):
        """The control node runs no live session: a simulation is a job on a worker node."""
        assert not hasattr(session, "subsystem_integration_session") and not hasattr(session, "run_recorder")
        assert not hasattr(session, "connect_to_mqtt_broker") and not hasattr(session, "set_simulation_session") and not hasattr(session, "set_monitor_session")

    async def test_connection_id_is_stable_and_names_the_socket(self, session, websocket):
        assert session.connection_id == str(id(websocket))

    async def test_created_at_is_a_utc_timestamp(self, session):
        assert session.created_at_utc.endswith("+00:00")


class TestSending:
    async def test_payloads_reach_the_socket_in_order(self, session, websocket):
        session.send_payload({"type": "first"})
        session.send_payload({"type": "second"})
        await settle()
        assert types_sent(websocket)[-2:] == ["first", "second"]

    async def test_runtime_errors_are_sent_as_error_messages(self, session, websocket):
        session.send_runtime_error("something failed")
        await settle()
        assert {"type": "error", "message": "something failed"} in websocket.sent

    async def test_preview_chunks_are_not_logged(self, session, capsys):
        session.log_payload("outgoing", {"type": "preview_trajectory_chunk"})
        assert capsys.readouterr().out == ""

    async def test_other_messages_are_logged_with_direction_and_type(self, session, capsys):
        session.log_payload("incoming", {"type": "load_scenario_file"})
        assert f"[ws][incoming] session_id={session.connection_id} type=load_scenario_file" in capsys.readouterr().out


class TestLoadingAScenario:
    async def test_a_trajectory_file_is_loaded_and_shown_as_a_plain_preview(self, session, websocket):
        session.set_scenario_session("s1", "planned.json", "dir/planned.json", trajectory_file(30))
        await settle()
        assert isinstance(session.scenario_session, ScenarioSession) and session.scenario_session.is_initialized
        assert websocket.sent[0]["type"] == "initial_state" and websocket.sent[0]["scenarioId"] == "s1"
        assert set(types_sent(websocket)[1:]) == {"preview_trajectory_chunk"}, "no status of a broker, a simulation or a monitor follows"
        frames = [frame for chunk in websocket.sent[1:] for frame in chunk["frames"]]
        assert len(frames) == len(session.scenario_session.trajectories)

    async def test_a_new_scenario_replaces_the_loaded_one(self, session, websocket):
        session.set_scenario_session("s1", "scene.json", "scene.json", scene_file())
        session.set_scenario_session("s2", "planned.json", "planned.json", trajectory_file(30))
        assert session.scenario_session.scenario_id == "s2" and len(session.scenario_session.trajectories) > 1

    async def test_a_file_that_is_no_scenario_raises_and_keeps_the_loaded_one(self, session):
        session.set_scenario_session("s1", "scene.json", "scene.json", scene_file())
        with pytest.raises(json.JSONDecodeError):
            session.set_scenario_session("s2", "broken.json", "broken.json", "{")
        assert session.scenario_session.scenario_id == "s1"


class TestVesselModels:
    @pytest.fixture
    async def loaded(self, session, websocket, monkeypatch):
        """A session with a loaded scene whose model generation records what it is given and marks the vessels."""
        session.set_scenario_session("s1", "scene.json", "scene.json", scene_file())
        await settle()
        websocket.sent.clear()
        calls = []

        def generate(scene, config):
            calls.append((scene, config))
            return config

        monkeypatch.setattr(socket_session, "generate_vessel_models", generate)
        return calls

    async def test_models_need_a_loaded_scenario(self, session, websocket):
        session.generate_simulation_models(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0]))
        await settle()
        assert errors(websocket) == ["No scenario loaded"]

    async def test_the_models_of_the_initial_scene_are_answered_as_the_setup(self, session, loaded, websocket):
        config = stack_instance(SimulationLayerId.GAZEBO, [0, 1])
        session.generate_simulation_models(config)
        await settle()
        assert loaded == [(session.scenario_session.trajectories.initial_scene, config)]
        (message,) = websocket.sent
        assert message["type"] == "simulation_models" and message["simulatorType"] == "Gazebo" and set(message["connectionsByAgentId"]) == {"0", "1"}
        assert "port" not in message["connectionsByAgentId"]["0"], "a vessel has no ground station port of its own any more"

    async def test_a_bare_scene_is_enough_since_models_come_from_the_initial_scene(self, session, loaded, websocket):
        assert len(session.scenario_session.trajectories) == 1
        session.generate_simulation_models(stack_instance(SimulationLayerId.GAZEBO, [0, 1], asv_system=AsvSystemId.USV_NAVIGATION, control_layer=ControlLayerId.CUSTOM))
        await settle()
        assert len(loaded) == 1 and errors(websocket) == []

    async def test_a_rejected_configuration_generates_no_models(self, session, loaded, websocket):
        session.generate_simulation_models(stack_instance(SimulationLayerId.GAZEBO, [0], control_layer=ControlLayerId.NONE))
        await settle()
        assert loaded == []
        (error,) = errors(websocket)
        assert error.startswith("Simulation configuration rejected: ") and "Gazebo needs actuator commands" in error

    async def test_a_scenario_without_an_initial_scene_is_reported(self, session, loaded, websocket):
        session.scenario_session = SimpleNamespace(is_initialized=True, trajectories=SimpleNamespace(initial_scene=None))
        session.generate_simulation_models(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0]))
        await settle()
        assert errors(websocket) == ["No initial scene found"]

    async def test_warnings_are_printed_not_sent(self, session, loaded, websocket, capsys):
        session.generate_simulation_models(stack_instance(SimulationLayerId.GAZEBO, [0], speedup=3))
        await settle()
        assert "Simulation configuration warning:" in capsys.readouterr().out
        assert len(loaded) == 1 and errors(websocket) == []


class TestCancel:
    async def test_cancel_stops_the_background_task(self, websocket):
        session = SocketSession(websocket)
        session.cancel()
        await settle()
        assert session.outbound_task.cancelled()
