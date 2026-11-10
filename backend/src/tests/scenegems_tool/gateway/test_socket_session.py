"""SocketSession: the per-connection state of the workbench gateway, with empty (offline) subsystem sessions.

Ported from the old test_socket_session_status.py, which tested SocketSession.get_simulation_status of
scenegems_tool.backend_service.session. The session no longer polls a status: the simulation session
pushes `simulation_status` messages, so the checks are on the messages and on the session objects.
"""

import asyncio
import json
from types import SimpleNamespace

import pytest

from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from scenegems_tool.assurance.pipeline.case_machine import RecordedRun
from scenegems_tool.gateway.live_run_recorder import OpenedEntry
from scenegems_tool.gateway.protocol import SimulationStatus
from scenegems_tool.gateway.socket_session import NO_TRAJECTORIES_MESSAGE, SocketSession, control_node_broker, control_node_broker_label
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentContext, VesselStackConfig
from scenegems_tool.workbench.empty_subsystem_integration_session import EmptySubsystemIntegrationSession
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


class TestInitialState:
    async def test_starts_with_empty_offline_sessions(self, session):
        assert isinstance(session.subsystem_integration_session, EmptySubsystemIntegrationSession)
        assert not session.subsystem_integration_session.is_connected
        assert not session.scenario_session.is_initialized

    async def test_simulation_is_not_initialized_while_offline(self, session):
        assert session.subsystem_integration_session.simulation_session.status == SimulationStatus.NOT_INITIALIZED

    async def test_the_initial_simulation_status_is_the_first_message_sent(self, session, websocket):
        await settle()
        assert websocket.sent[0] == {"type": "simulation_status", "status": "not initialized"}

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

    async def test_status_and_chunk_messages_are_not_logged(self, session, capsys):
        for message_type in ("simulation_status", "monitor_status", "mqtt_broker_status", "preview_trajectory_chunk", "simulation_trajectory_chunk"):
            session.log_payload("outgoing", {"type": message_type})
        assert capsys.readouterr().out == ""

    async def test_other_messages_are_logged_with_direction_and_type(self, session, capsys):
        session.log_payload("incoming", {"type": "start_simulation"})
        assert f"[ws][incoming] session_id={session.connection_id} type=start_simulation" in capsys.readouterr().out


class TestOfflineBehaviour:
    async def test_disconnect_reports_disconnected_and_keeps_an_empty_session(self, session, websocket):
        session.disconnect_from_mqtt_broker()
        await settle()
        assert {"type": "mqtt_broker_status", "status": "disconnected", "controlNodeBroker": None} in websocket.sent
        assert isinstance(session.subsystem_integration_session, EmptySubsystemIntegrationSession)

    async def test_initializing_the_monitor_while_offline_is_an_error(self, session, websocket):
        session.set_monitor_session("monitor", "topic", "scope", "constraints")
        await settle()
        assert {"type": "error", "message": "No MQTT broker is connected: connect one on the Connections page"} in websocket.sent

    async def test_shutting_down_the_monitor_reports_it(self, session, websocket):
        session.shut_down_monitor()
        await settle()
        assert {"type": "monitor_status", "status": "disconnected"} in websocket.sent

    async def test_a_simulation_needs_a_loaded_scenario(self, session, websocket):
        session.set_simulation_session(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0]))
        session.generate_simulation_models(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0]))
        await settle()
        assert [payload["message"] for payload in websocket.sent if payload["type"] == "error"] == ["No scenario loaded", "No scenario loaded"]

    async def test_the_control_node_broker_is_refused_when_the_server_has_none(self, session, monkeypatch):
        monkeypatch.delenv("SCENEGEMS_BROKER_HOST", raising=False)
        with pytest.raises(ValueError, match="no control node broker"):
            await session.connect_to_mqtt_broker("", "", "", "", 1883, False, False, Geofence(57.7, 11.9, 1000.0), use_control_node_broker=True)
        assert isinstance(session.subsystem_integration_session, EmptySubsystemIntegrationSession)

    async def test_the_status_names_the_control_node_broker(self, session, monkeypatch):
        monkeypatch.setenv("SCENEGEMS_BROKER_HOST", "cluster-broker")
        monkeypatch.setenv("SCENEGEMS_BROKER_PORT", "1884")
        assert session.mqtt_broker_status_message() == {"type": "mqtt_broker_status", "status": "disconnected", "controlNodeBroker": "cluster-broker:1884"}


class TestControlNodeBroker:
    def test_the_control_node_broker_comes_from_the_control_node_settings(self):
        assert control_node_broker({"SCENEGEMS_BROKER_HOST": "cluster-broker"}) == ("cluster-broker", 1883)
        assert control_node_broker({"SCENEGEMS_BROKER_HOST": " cluster-broker ", "SCENEGEMS_BROKER_PORT": "1999"}) == ("cluster-broker", 1999)

    def test_without_a_host_there_is_no_control_node_broker(self):
        assert control_node_broker({}) is None
        assert control_node_broker({"SCENEGEMS_BROKER_HOST": "  ", "SCENEGEMS_BROKER_PORT": "1883"}) is None
        assert control_node_broker_label({}) is None


class FakeIntegrationSession:
    """Records how the socket session builds the live session, without a broker."""

    created = []

    def __init__(self, mqtt_connection, reference_geofence, send_payload, session_scope):
        self.mqtt_connection = mqtt_connection
        self.session_scope = session_scope
        self.cancelled = False
        FakeIntegrationSession.created.append(self)

    async def start(self):
        pass

    def cancel(self):
        self.cancelled = True


class TestLiveSessionScope:
    @pytest.fixture(autouse=True)
    def fake_sessions(self, monkeypatch):
        from scenegems_tool.gateway import socket_session

        FakeIntegrationSession.created = []
        monkeypatch.setattr(socket_session, "LiveSubsystemIntegrationSession", FakeIntegrationSession)
        monkeypatch.setenv("SCENEGEMS_CONTROL_NODE_ID", "m1")
        monkeypatch.setenv("SCENEGEMS_BROKER_HOST", "cluster-broker")

    async def test_on_the_control_node_broker_the_session_topics_carry_its_scope(self, session):
        await session.connect_to_mqtt_broker("", "", "", "", 1883, False, False, Geofence(57.7, 11.9, 1000.0), use_control_node_broker=True)
        (live,) = FakeIntegrationSession.created
        assert live.session_scope.control_node_id == "m1" and live.session_scope.worker_node_id == "workbench"
        assert live.mqtt_connection.topic_prefix == live.session_scope.topic_prefix
        assert live.mqtt_connection.topic_prefix.startswith("scenegems/m1/workbench/live-")

    async def test_another_broker_keeps_the_unscoped_wara_ps_topics_but_the_stack_is_still_the_sessions(self, session):
        await session.connect_to_mqtt_broker("user", "secret", "broker.waraps.org", "broker.waraps.org", 8883, True, False, Geofence(57.7, 11.9, 1000.0))
        (live,) = FakeIntegrationSession.created
        assert live.mqtt_connection.topic_prefix == ""
        assert live.session_scope.compose_project.startswith("scenegems-m1-workbench-live-")

    async def test_every_connection_is_a_session_of_its_own(self, session, websocket):
        other = SocketSession(websocket)
        try:
            await session.connect_to_mqtt_broker("", "", "", "", 1883, False, False, Geofence(57.7, 11.9, 1000.0), use_control_node_broker=True)
            await other.connect_to_mqtt_broker("", "", "", "", 1883, False, False, Geofence(57.7, 11.9, 1000.0), use_control_node_broker=True)
            first, second = FakeIntegrationSession.created
            assert first.session_scope != second.session_scope
            assert first.mqtt_connection.topic_prefix != second.mqtt_connection.topic_prefix
            assert not first.cancelled, "the second browser's session leaves the first one running"
        finally:
            other.cancel()


class TestSimulationConfigValidation:
    @pytest.fixture
    async def loaded(self, session, monkeypatch):
        """A session whose scenario counts as loaded and whose simulation session records what it is given."""
        trajectories = encounter_trajectories("head_on", 20)
        session.scenario_session = SimpleNamespace(is_initialized=True, has_trajectories=True, trajectories=trajectories)
        calls = SimpleNamespace(initialized=[], models=[])
        monkeypatch.setattr(session.subsystem_integration_session, "set_simulation_session", lambda **kwargs: calls.initialized.append(kwargs))
        monkeypatch.setattr(session.subsystem_integration_session.simulation_session, "generate_vessel_models", lambda scene, config: calls.models.append((scene, config)))
        return calls

    async def test_an_accepted_configuration_starts_the_simulation_session(self, session, loaded, websocket):
        config = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"])
        session.set_simulation_session(config)
        assert len(loaded.initialized) == 1
        assert loaded.initialized[0]["simulation_config"] is config
        await settle()
        assert not [payload for payload in websocket.sent if payload["type"] == "error"]

    async def test_a_rejected_configuration_sends_the_reason_and_starts_nothing(self, session, loaded, websocket):
        session.set_simulation_session(stack_instance(SimulationLayerId.GAZEBO, [0], control_layer=ControlLayerId.NONE))
        await settle()
        assert loaded.initialized == []
        (error,) = [payload["message"] for payload in websocket.sent if payload["type"] == "error"]
        assert error.startswith("Simulation configuration rejected: ")
        assert "Gazebo needs actuator commands" in error

    async def test_with_a_real_vessel_usv_navigation_is_refused_since_arduagent_cannot_drive_it(self, session, loaded, websocket):
        config = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], asv_system=AsvSystemId.USV_NAVIGATION)
        config.vessels["1"].context = AgentContext.REAL
        config.vessels["1"].stack = VesselStackConfig(AsvSystemId.ON_BOARD, ControlLayerId.REAL_VESSEL, SimulationLayerId.REAL_VESSEL)
        session.set_simulation_session(config)
        await settle()
        assert loaded.initialized == []
        (error,) = [payload["message"] for payload in websocket.sent if payload["type"] == "error"]
        assert "ArduAgent drives every simulated vessel, and it cannot drive vessel 0 (usv_navigation, ardupilot, ardupilot_sim)" in error

    async def test_simulated_vessels_alone_may_run_any_available_stack(self, session, loaded, websocket):
        session.set_simulation_session(stack_instance(SimulationLayerId.GAZEBO, [0, 1], asv_system=AsvSystemId.USV_NAVIGATION, control_layer=ControlLayerId.CUSTOM))
        await settle()
        assert len(loaded.initialized) == 1
        assert not [payload for payload in websocket.sent if payload["type"] == "error"]

    async def test_vessel_models_are_generated_for_the_initial_scene(self, session, loaded):
        config = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"])
        session.generate_simulation_models(config)
        assert len(loaded.models) == 1
        assert loaded.models[0][1] is config
        assert loaded.models[0][0] is session.scenario_session.trajectories.initial_scene

    async def test_a_rejected_configuration_generates_no_models(self, session, loaded, websocket):
        session.generate_simulation_models(stack_instance(SimulationLayerId.GAZEBO, [0], control_layer=ControlLayerId.NONE))
        await settle()
        assert loaded.models == []
        assert any(payload["type"] == "error" and "rejected" in payload["message"] for payload in websocket.sent)

    async def test_a_scenario_without_an_initial_scene_is_reported(self, session, loaded, websocket):
        session.scenario_session = SimpleNamespace(is_initialized=True, trajectories=SimpleNamespace(initial_scene=None))
        session.generate_simulation_models(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0], adapter_ids=["replay_arduagent_follower"]))
        await settle()
        assert {"type": "error", "message": "No initial scene found"} in websocket.sent

    async def test_warnings_are_printed_not_sent(self, session, loaded, websocket, capsys):
        session.set_simulation_session(stack_instance(SimulationLayerId.GAZEBO, [0], speedup=3))
        await settle()
        assert "Simulation configuration warning:" in capsys.readouterr().out
        assert len(loaded.initialized) == 1


class TestScenarioWithoutTrajectories:
    """A bare scene loaded into the workbench has its initial scene only: the simulation is refused, never fed invented trajectories."""

    @pytest.fixture
    async def bare(self, session, websocket, monkeypatch):
        calls = SimpleNamespace(initialized=[], models=[])
        monkeypatch.setattr(session.subsystem_integration_session, "set_simulation_session", lambda **kwargs: calls.initialized.append(kwargs))
        content = json.dumps(EvaluationData(best_scene=encounter_scene("head_on"), timeout=1, random_seed=3).to_dict())
        session.set_scenario_session("s1", "scene.json", "scene.json", content)  # replaces the simulation session
        monkeypatch.setattr(session.subsystem_integration_session.simulation_session, "generate_vessel_models", lambda scene, config: calls.models.append((scene, config)))
        await settle()
        return calls

    def errors(self, websocket):
        return [payload["message"] for payload in websocket.sent if payload["type"] == "error"]

    async def test_the_scene_is_loaded_without_trajectories(self, session, bare):
        assert session.scenario_session.is_initialized
        assert not session.scenario_session.has_trajectories

    async def test_initializing_the_simulation_is_refused_with_the_reason(self, session, bare, websocket):
        session.set_simulation_session(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"]))
        await settle()
        assert bare.initialized == []
        assert self.errors(websocket) == [NO_TRAJECTORIES_MESSAGE]
        assert "generate trajectories first" in NO_TRAJECTORIES_MESSAGE and "monitor-guided planner or straight" in NO_TRAJECTORIES_MESSAGE

    async def test_the_refusal_comes_before_the_configuration_is_judged(self, session, bare, websocket):
        session.set_simulation_session(stack_instance(SimulationLayerId.GAZEBO, [0], control_layer=ControlLayerId.NONE))
        await settle()
        assert self.errors(websocket) == [NO_TRAJECTORIES_MESSAGE]

    async def test_vessel_models_can_still_be_generated_from_the_initial_scene(self, session, bare, websocket):
        config = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"])
        session.generate_simulation_models(config)
        await settle()
        assert [(scene, given) for scene, given in bare.models] == [(session.scenario_session.trajectories.initial_scene, config)]
        assert self.errors(websocket) == []

    async def test_loading_trajectories_afterwards_allows_the_simulation(self, session, bare, websocket):
        content = json.dumps(
            {"trajectories": encounter_trajectories("head_on", 30).to_dict(), "algorithm_desc": "straight"},
        )
        session.set_scenario_session("s2", "planned.json", "planned.json", content)
        await settle()
        assert session.scenario_session.has_trajectories
        session.set_simulation_session(stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"]))
        assert len(bare.initialized) == 1


class TestCancel:
    async def test_cancel_stops_the_background_tasks(self, websocket):
        session = SocketSession(websocket)
        session.cancel()
        await settle()
        assert session.outbound_task.cancelled()
        assert session.mqtt_broker_status_task.cancelled()


class FakeLiveSimulation:
    """The part of a LiveSimulationSession the socket session wires the recording into."""

    time_step = 1

    def __init__(self):
        self.listener = None

    def set_run_listener(self, listener):
        self.listener = listener

    def destroy(self):
        pass

    def teardown(self):
        pass


class FakeRunRecorder:
    def __init__(self):
        self.stopped = []

    async def open_entry(self, setup):
        return OpenedEntry("entry-9", {"sha256": "0" * 64})

    async def record_run(self, entry, setup, states, durations_s=None):
        return RecordedRun(entry.campaign_id, 3, 30, "campaign:entry-9:case:3:monitor:0")

    async def stop_entry(self, campaign_id):
        self.stopped.append(campaign_id)


class TestLiveRunRecording:
    @pytest.fixture
    async def live(self, session, monkeypatch):
        """A loaded scenario whose simulation session is a live one."""
        session.scenario_session = SimpleNamespace(
            is_initialized=True, has_trajectories=True, trajectories=encounter_trajectories("head_on", 20), file_name="head_on.json", scenario_id="s1", time_step=1
        )
        simulation = FakeLiveSimulation()

        def set_simulation_session(**_):
            session.subsystem_integration_session.simulation_session = simulation

        monkeypatch.setattr(session.subsystem_integration_session, "set_simulation_session", set_simulation_session)
        return simulation

    def config(self):
        return stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], adapter_ids=["replay_arduagent_follower"])

    def recordings(self, websocket):
        return [payload for payload in websocket.sent if payload["type"] == "run_recording"]

    async def test_the_live_session_is_followed_with_what_it_runs(self, session, live):
        config = self.config()
        session.set_simulation_session(config)
        setup = live.listener.setup
        assert (setup.scenario_name, setup.trajectories, setup.simulation_config, setup.time_step) == ("head_on.json", session.scenario_session.trajectories, config, 1)
        assert live.listener.loop is session.loop

    async def test_without_the_control_node_a_run_is_reported_unavailable(self, session, live, websocket):
        session.set_simulation_session(self.config())
        live.listener.run_started()
        await settle()
        (message,) = self.recordings(websocket)
        assert (message["status"], message["campaignId"], message["caseId"]) == ("unavailable", None, None)

    async def test_with_the_control_node_a_run_is_recorded_and_saved(self, session, live, websocket):
        session.run_recorder = FakeRunRecorder()
        session.set_simulation_session(self.config())
        live.listener.run_started()
        live.listener.state_simulated(0.0, session.scenario_session.trajectories.initial_scene)
        live.listener.run_ended()
        (run,) = live.listener.recordings
        await asyncio.wrap_future(run.future)
        await settle()
        assert [(message["status"], message["campaignId"], message["caseId"]) for message in self.recordings(websocket)] == [
            ("recording", None, None),
            ("recording", "entry-9", None),
            ("saved", "entry-9", 3),
        ]

    async def test_an_empty_simulation_session_is_not_followed(self, session, websocket, monkeypatch):
        session.scenario_session = SimpleNamespace(is_initialized=True, has_trajectories=True, trajectories=encounter_trajectories("head_on", 20))
        monkeypatch.setattr(session.subsystem_integration_session, "set_simulation_session", lambda **_: None)
        session.set_simulation_session(self.config())
        await settle()
        assert self.recordings(websocket) == []
