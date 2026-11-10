"""Wire messages shared with the frontend: builders, and the simulation-models body to the typed configuration and back."""

import copy

import numpy as np
import pytest

from scenegems_tool.gateway.protocol import (
    SimulationStatus,
    make_error_message,
    make_generated_scene_message,
    make_initial_state_message,
    make_monitor_status_message,
    make_mqtt_broker_status_message,
    make_preview_chunk_message,
    make_run_recording_message,
    make_simulation_chunk_message,
    make_simulation_models_body,
    make_simulation_models_message,
    make_simulation_status_message,
    make_trajectory_generation_preview_message,
    make_trajectory_generation_result_message,
    simulation_config_from_body,
)
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentContext

BODY = {
    "simulatorType": "ArduPilot Sim",
    "windVector": [0.0, 0.0, 0.0],
    "wave": {"amplitude": 0.0, "period": 0.0, "steepness": 0.0, "direction": [0.0, 0.0]},
    "simulationSpeed": 2,
    "connectionsByAgentId": {
        "0": {"context": "simulation", "controlMode": "autonomous", "agentName": "os", "topic": "waraps/unit/surface/os", "port": 14550, "gazeboVesselModel": None},
        "1": {"context": "simulation", "controlMode": "external", "agentName": "ts", "topic": "waraps/unit/surface/ts", "port": 14560},
        "2": {"context": "real", "controlMode": "external", "agentName": "real", "topic": "waraps/unit/surface/real", "port": None},
    },
}


@pytest.fixture
def body():
    return copy.deepcopy(BODY)


class TestMessageBuilders:
    def test_simulation_status_values_are_the_wire_strings(self):
        assert {status.name: status.value for status in SimulationStatus} == {
            "NOT_INITIALIZED": "not initialized",
            "INITIALIZING": "initializing",
            "AGENTS_ARE_PREPARING": "agents are preparing",
            "READY_TO_START": "ready to start",
            "STARTING": "starting",
            "RUNNING": "running",
        }

    def test_simulation_status_message(self):
        assert make_simulation_status_message(SimulationStatus.RUNNING) == {"type": "simulation_status", "status": "running"}

    def test_simulation_status_message_carries_the_ground_control_ports(self):
        message = make_simulation_status_message(SimulationStatus.READY_TO_START, {"1": 49154, "0": 49153})
        assert message["groundControlPortsByAgentId"] == {"0": 49153, "1": 49154}
        assert "groundControlPortsByAgentId" not in make_simulation_status_message(SimulationStatus.RUNNING, {})

    def test_mqtt_broker_and_monitor_status_messages(self):
        assert make_mqtt_broker_status_message(status="connected", control_node_broker="cluster-broker:1883") == {
            "type": "mqtt_broker_status",
            "status": "connected",
            "controlNodeBroker": "cluster-broker:1883",
        }
        assert make_mqtt_broker_status_message(status="disconnected", control_node_broker=None)["controlNodeBroker"] is None
        assert make_monitor_status_message(status="disconnected") == {"type": "monitor_status", "status": "disconnected"}

    def test_error_message_carries_the_text(self, capsys):
        assert make_error_message("boom") == {"type": "error", "message": "boom"}
        assert "Error message: boom" in capsys.readouterr().out

    def test_error_message_survives_a_console_that_cannot_print_it(self, monkeypatch):
        printed = []

        def fussy_print(text):
            if any(ord(char) > 127 for char in text):
                raise UnicodeEncodeError("cp1252", text, 0, 1, "cannot encode")
            printed.append(text)

        monkeypatch.setattr("builtins.print", fussy_print)
        message = make_error_message("go → north")
        assert message["message"] == "go → north"
        assert printed == ["Error message: go ? north"]

    def test_initial_state_message_always_carries_the_scenario_id(self):
        assert make_initial_state_message("s1", 2, 100) == {"type": "initial_state", "scenarioId": "s1", "timeStep": 2, "trajectoryLength": 100}

    def test_generated_scene_message(self):
        assert make_generated_scene_message("r1", {"a": 1}, {"b": 2}, True) == {"type": "generated_scene", "requestId": "r1", "scene": {"a": 1}, "evaluationData": {"b": 2}, "valid": True}

    def test_trajectory_generation_messages(self):
        assert make_trajectory_generation_preview_message("r1", {"t": 1}) == {"type": "trajectory_generation_preview", "requestId": "r1", "trajectoryData": {"t": 1}}
        result = make_trajectory_generation_result_message("r1", None, 0, "failed")
        assert result == {"type": "trajectory_generation_result", "requestId": "r1", "trajectoryData": None, "valid": False, "errorMessage": "failed"}

    def test_trajectory_generation_result_carries_complete_only_when_given(self):
        partial = make_trajectory_generation_result_message("r1", {"t": 1}, True, None, complete=False)
        assert partial == {"type": "trajectory_generation_result", "requestId": "r1", "trajectoryData": {"t": 1}, "valid": True, "complete": False, "errorMessage": None}
        assert make_trajectory_generation_result_message("r1", {"t": 1}, True, None, complete=True)["complete"] is True
        assert "complete" not in make_trajectory_generation_result_message("r1", {"t": 1}, True, None)

    def test_run_recording_messages_have_the_fields_the_browser_parses(self):
        # frontend/src/domain/simulation/protocol.ts runRecordingSchema: every field present, ids and message nullable
        assert make_run_recording_message("saved", "entry-1", 4, "judged") == {"type": "run_recording", "status": "saved", "campaignId": "entry-1", "caseId": 4, "message": "judged"}
        assert make_run_recording_message("unavailable") == {"type": "run_recording", "status": "unavailable", "campaignId": None, "caseId": None, "message": None}

    def test_chunk_messages(self):
        assert make_preview_chunk_message("s", 0, 9, [{"f": 1}]) == {"type": "preview_trajectory_chunk", "scenarioId": "s", "fromTimestamp": 0, "toTimestamp": 9, "frames": [{"f": 1}]}
        assert make_simulation_chunk_message("s", 10, 19, [])["type"] == "simulation_trajectory_chunk"


class TestSimulationConfigFromBody:
    def test_vessels_become_typed_configurations(self, body):
        config = simulation_config_from_body(body)
        assert config.simulation_layer == SimulationLayerId.ARDUPILOT_SIM
        assert config.speedup == 2
        assert set(config.vessels) == {"0", "1", "2"}
        first = config.vessels["0"]
        assert (first.stack.asv_software, first.stack.control_layer) == (AsvSoftwareId.REPLAY, ControlLayerId.ARDUPILOT)
        assert first.connection.agent_name == "os" and first.connection.port == 14550
        assert first.adapter_ids == ("replay_arduagent_follower",)

    def test_with_a_real_vessel_every_vessel_runs_through_arduagent(self, body):
        assert simulation_config_from_body(body).vessels["1"].adapter_ids == ("mission_planner_mavlink_port",)

    def test_simulated_vessels_alone_use_the_registry_defaults(self, body):
        del body["connectionsByAgentId"]["2"]
        config = simulation_config_from_body(body)
        assert [config.vessels[agent_id].adapter_ids for agent_id in ("0", "1")] == [(), ()]

    def test_asv_software_and_control_layer_choose_the_stack(self, body):
        body["simulatorType"] = "Gazebo"
        body["connectionsByAgentId"]["0"].update(asvSoftware="usv_navigation", controlLayer="custom")
        del body["connectionsByAgentId"]["0"]["controlMode"]
        stack = simulation_config_from_body(body).vessels["0"].stack
        assert (stack.asv_software, stack.control_layer, stack.simulation_layer) == (AsvSoftwareId.USV_NAVIGATION, ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO)

    def test_kinematic_vessels_default_to_no_control_layer(self, body):
        body["simulatorType"] = "Kinematic"
        assert simulation_config_from_body(body).vessels["0"].stack.control_layer == ControlLayerId.NONE

    def test_real_vessel_may_omit_its_port(self, body):
        real = simulation_config_from_body(body).vessels["2"]
        assert real.context == AgentContext.REAL
        assert real.connection.port is None
        assert not real.is_simulated

    def test_a_real_vessel_runs_on_its_own_layers_whatever_the_simulator(self, body):
        real = simulation_config_from_body(body).vessels["2"]
        assert (real.stack.asv_software, real.stack.control_layer, real.stack.simulation_layer) == (AsvSoftwareId.MISSION_PLANNER, ControlLayerId.REAL_VESSEL, SimulationLayerId.REAL_VESSEL)
        assert real.adapter_ids == ()

    def test_a_real_vessel_may_leave_the_steering_to_its_on_board_software(self, body):
        body["connectionsByAgentId"]["2"].update(asvSoftware="on_board", controlLayer="real_vessel")
        assert simulation_config_from_body(body).vessels["2"].stack.asv_software == AsvSoftwareId.ON_BOARD

    def test_a_real_vessel_cannot_name_another_control_layer(self, body):
        body["connectionsByAgentId"]["2"]["controlLayer"] = "ardupilot"
        with pytest.raises(ValueError, match="A real vessel's control layer is its own autopilot"):
            simulation_config_from_body(body)

    def test_simulated_vessel_needs_a_port(self, body):
        body["connectionsByAgentId"]["1"]["port"] = None
        with pytest.raises(ValueError, match="Missing port for agent with context 'simulation'"):
            simulation_config_from_body(body)

    def test_unknown_context_is_rejected_with_the_choices(self, body):
        body["connectionsByAgentId"]["0"]["context"] = "hardware"
        with pytest.raises(ValueError, match="Unknown agent context 'hardware'; expected one of simulation, real"):
            simulation_config_from_body(body)

    def test_unknown_simulator_type_is_rejected(self, body):
        body["simulatorType"] = "Webots"
        with pytest.raises(ValueError, match="Unknown simulatorType 'Webots'"):
            simulation_config_from_body(body)

    def test_unknown_control_mode_is_rejected(self, body):
        body["connectionsByAgentId"]["0"]["controlMode"] = "manual"
        with pytest.raises(ValueError, match="Unknown controlMode 'manual'"):
            simulation_config_from_body(body)

    @pytest.mark.parametrize("wind", [[1.0, 2.0], [1.0, 2.0, 3.0, 4.0], []])
    def test_wind_vector_needs_three_components(self, body, wind):
        body["windVector"] = wind
        with pytest.raises(ValueError, match="windVector must have 3 components"):
            simulation_config_from_body(body)

    def test_wind_and_wave_become_numpy_values(self, body):
        body["windVector"] = [1, 2, 0]
        body["wave"] = {"amplitude": 0.5, "period": 5, "steepness": 0.1, "direction": [1, 0]}
        environment = simulation_config_from_body(body).environment
        assert environment.wind_vector.dtype == float
        np.testing.assert_array_equal(environment.wind_vector, [1.0, 2.0, 0.0])
        assert environment.wave.amplitude == 0.5 and environment.waves_requested

    def test_speed_defaults_to_real_time(self, body):
        del body["simulationSpeed"]
        assert simulation_config_from_body(body).speedup == 1

    def test_a_provided_vessel_model_is_kept(self, body):
        body["connectionsByAgentId"]["0"]["gazeboVesselModel"] = "<sdf/>"
        assert simulation_config_from_body(body).vessels["0"].gazebo_vessel_model == "<sdf/>"


class TestRoundTrip:
    def test_body_to_config_and_back_keeps_the_wire_fields(self, body):
        config = simulation_config_from_body(body)
        again = make_simulation_models_body(config)
        assert again["simulatorType"] == "ArduPilot Sim"
        assert again["simulationSpeed"] == 2
        assert again["windVector"] == [0.0, 0.0, 0.0]
        for agent_id, connection in body["connectionsByAgentId"].items():
            sent = again["connectionsByAgentId"][agent_id]
            assert sent["context"] == connection["context"]
            assert sent["controlMode"] == connection["controlMode"]
            assert sent["controlLayer"] == ("real_vessel" if connection["context"] == "real" else "ardupilot")
            assert sent["asvSoftware"] == {"autonomous": "replay", "external": "mission_planner"}[connection["controlMode"]]
            assert sent["agentName"] == connection["agentName"]
            assert sent["topic"] == connection["topic"]
            assert sent["port"] == connection["port"]

    def test_message_adds_the_type(self, body):
        message = make_simulation_models_message(simulation_config_from_body(body))
        assert message["type"] == "simulation_models"
        assert message["simulatorType"] == "ArduPilot Sim"

    def test_generated_vessel_model_is_sent_back(self, body):
        config = simulation_config_from_body(body)
        config.vessels["0"].gazebo_vessel_model = "<sdf/>"
        assert make_simulation_models_body(config)["connectionsByAgentId"]["0"]["gazeboVesselModel"] == "<sdf/>"

    def test_every_stack_survives_the_round_trip(self, body):
        """The scenario execution worker gets the body back, so a kinematic or USV Navigation instance must read back the same."""
        del body["connectionsByAgentId"]["2"]
        body["simulatorType"] = "Kinematic"
        body["connectionsByAgentId"]["0"].update(asvSoftware="usv_navigation", controlLayer="none")
        config = simulation_config_from_body(body)
        again = simulation_config_from_body(make_simulation_models_body(config))
        assert again.simulation_layer == SimulationLayerId.KINEMATIC
        assert {agent_id: (vessel.stack, vessel.adapter_ids) for agent_id, vessel in again.vessels.items()} == {
            agent_id: (vessel.stack, vessel.adapter_ids) for agent_id, vessel in config.vessels.items()
        }
        assert "controlMode" not in make_simulation_models_body(config)["connectionsByAgentId"]["0"], "ArduAgent has no mode for USV Navigation"
