"""The vessel model presets the gateway offers per vessel of a scenario, and a setup that names one."""

import dataclasses
import json

import pytest

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from scenegems_tool.gateway.protocol import make_simulation_models_body, simulation_config_from_body
from scenegems_tool.gateway.socket_message_processor import SocketMessageProcessor
from scenegems_tool.gateway.socket_session import SocketSession
from scenegems_tool.gateway.vessel_models import check_vessel_model_presets, generate_vessel_models, vessel_model_presets_message
from scenegems_tool.vessel_stack.contracts.roles import SimulationLayerId
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_catalog import VesselOutOfPresetBounds
from tests.scenegems_tool.gateway.conftest import settle
from tests.scenegems_tool.vessel_stack.scenarios import ENCOUNTER_TARGETS, SPEED, make_vessel, stack_instance
from tests.scenegems_tool.vessel_stack.sdf import child_text, parse_sdf, plugins

PANAMAX = {"length": 266.0, "breadth": 35.5, "draft": 12.2, "height": 30.5, "_steering_type": "rudder", "_block_coefficient": 0.65, "_max_speed": 12.86, "_max_angular_speed": 0.007}


def panamax_scene() -> ConcreteScene:
    """A Panamax container ship with a rudder (vessel 0) meeting the small skid steered vessel of the test scenarios (vessel 1)."""
    own = dataclasses.replace(make_vessel(0, True), **PANAMAX)
    return ConcreteScene({own: ActorState(0.0, 0.0, SPEED, 0.0), make_vessel(1, False): ENCOUNTER_TARGETS["head_on"]})


def setup_body(preset=None) -> dict:
    body = dict(make_simulation_models_body(stack_instance(SimulationLayerId.GAZEBO, [0, 1])))
    if preset is not None:
        body["connectionsByAgentId"]["0"]["vesselModelPreset"] = preset
    return body


class TestPresetsMessage:
    def test_every_vessel_has_an_entry_with_the_presets_it_can_take(self):
        message = vessel_model_presets_message("s1", panamax_scene())
        assert (message["type"], message["scenarioId"]) == ("vessel_model_presets", "s1")
        assert set(message["presetsByAgentId"]) == {"0", "1"}
        assert "hanjin_pretoria" in [preset["id"] for preset in message["presetsByAgentId"]["0"]]
        assert message["presetsByAgentId"]["1"] == [], "a small skid steered vessel is within no ship's bounds"

    def test_a_preset_is_described_for_the_console(self):
        offered = {preset["id"]: preset for preset in vessel_model_presets_message("s1", panamax_scene())["presetsByAgentId"]["0"]}
        pretoria = offered["hanjin_pretoria"]
        assert pretoria["steeringType"] == "rudder" and pretoria["name"].startswith("Hanjin Pretoria")
        assert pretoria["bounds"]["length"] == [226.0, 306.0] and pretoria["particulars"]["breadth"] == 32.2
        json.dumps(pretoria)

    def test_a_preset_of_another_steering_type_is_not_offered(self):
        own = dataclasses.replace(make_vessel(0, True), **{**PANAMAX, "_steering_type": "skid"})
        scene = ConcreteScene({own: ActorState(0.0, 0.0, SPEED, 0.0)})
        assert vessel_model_presets_message("s1", scene)["presetsByAgentId"]["0"] == []


class TestSetupBody:
    def test_a_setup_without_a_preset_reads_as_before(self):
        config = simulation_config_from_body(setup_body())
        assert config.vessels["0"].vessel_model_preset is None
        assert "vesselModelPreset" not in make_simulation_models_body(config)["connectionsByAgentId"]["0"]

    def test_a_chosen_preset_survives_the_round_trip(self):
        config = simulation_config_from_body(setup_body("hanjin_pretoria"))
        assert config.vessels["0"].vessel_model_preset == "hanjin_pretoria" and config.vessels["1"].vessel_model_preset is None
        connections = make_simulation_models_body(config)["connectionsByAgentId"]
        assert connections["0"]["vesselModelPreset"] == "hanjin_pretoria" and "vesselModelPreset" not in connections["1"]

    def test_a_null_preset_is_the_automatic_model(self):
        body = setup_body()
        body["connectionsByAgentId"]["0"]["vesselModelPreset"] = None
        assert simulation_config_from_body(body).vessels["0"].vessel_model_preset is None


class TestGeneratedModels:
    def test_a_vessel_with_a_preset_gets_the_presets_model(self):
        """The Hanjin Pretoria's rudder is larger than the automatic one, so the rudder's force coefficient differs."""
        scene = panamax_scene()
        automatic = generate_vessel_models(scene, simulation_config_from_body(setup_body())).vessels["0"].gazebo_vessel_model
        preset = generate_vessel_models(scene, simulation_config_from_body(setup_body("hanjin_pretoria"))).vessels["0"].gazebo_vessel_model

        def rudder_coefficient(model: str) -> float:
            rudder = next(system for system in plugins(parse_sdf(model), "gz-sim-hydrodynamics-system") if child_text(system, "link_name") == "steering_link")
            return float(child_text(rudder, "yVabsU"))

        assert rudder_coefficient(preset) / rudder_coefficient(automatic) == pytest.approx(0.02353 / 0.02, rel=1e-3)
        assert "block coefficient 0.817" in preset and "block coefficient 0.65" in automatic

    def test_the_other_vessel_keeps_its_automatic_model(self):
        scene = panamax_scene()
        with_preset = generate_vessel_models(scene, simulation_config_from_body(setup_body("hanjin_pretoria"))).vessels["1"].gazebo_vessel_model
        without = generate_vessel_models(scene, simulation_config_from_body(setup_body())).vessels["1"].gazebo_vessel_model
        assert with_preset == without

    def test_a_preset_the_vessel_is_outside_of_is_refused(self):
        config = simulation_config_from_body(setup_body("otter_usv"))
        with pytest.raises(VesselOutOfPresetBounds, match="otter_usv"):
            check_vessel_model_presets(panamax_scene(), config)

    def test_an_unknown_preset_is_refused(self):
        with pytest.raises(ValueError, match="unknown vessel model preset 'titanic'"):
            check_vessel_model_presets(panamax_scene(), simulation_config_from_body(setup_body("titanic")))

    def test_a_setup_without_presets_passes_the_check(self):
        check_vessel_model_presets(panamax_scene(), simulation_config_from_body(setup_body()))


@pytest.mark.anyio
class TestGatewayRequests:
    @pytest.fixture
    async def session(self, websocket):
        session = SocketSession(websocket)
        yield session
        session.cancel()

    @staticmethod
    def load(session: SocketSession) -> None:
        session.set_scenario_session("s1", "scene.json", "scene.json", json.dumps(EvaluationData(best_scene=panamax_scene(), timeout=1, random_seed=3).to_dict()))

    async def test_the_presets_of_the_loaded_scenario_are_sent(self, session, websocket):
        self.load(session)
        session.send_vessel_model_presets()
        await settle()
        answer = next(payload for payload in websocket.sent if payload["type"] == "vessel_model_presets")
        assert answer["scenarioId"] == "s1" and "hanjin_pretoria" in [preset["id"] for preset in answer["presetsByAgentId"]["0"]]

    async def test_without_a_scenario_the_request_is_an_error(self, session, websocket):
        session.send_vessel_model_presets()
        await settle()
        assert [payload["message"] for payload in websocket.sent if payload["type"] == "error"] == ["No scenario loaded"]

    async def test_the_processor_routes_the_request(self, session, websocket):
        self.load(session)
        processor = SocketMessageProcessor(session)
        try:
            processor.inbound_queue.put_nowait({"type": "query_vessel_model_presets"})
            await settle()
        finally:
            processor.cancel()
        assert "vessel_model_presets" in [payload["type"] for payload in websocket.sent]

    async def test_generating_models_with_a_preset_out_of_bounds_is_rejected(self, session, websocket):
        self.load(session)
        session.generate_simulation_models(simulation_config_from_body(setup_body("otter_usv")))
        await settle()
        messages = [payload["message"] for payload in websocket.sent if payload["type"] == "error"]
        assert len(messages) == 1 and messages[0].startswith("Simulation configuration rejected: vessel 0") and "otter_usv" in messages[0]
        assert "simulation_models" not in [payload["type"] for payload in websocket.sent]

    async def test_generating_models_with_a_preset_answers_with_the_preset_named(self, session, websocket):
        self.load(session)
        session.generate_simulation_models(simulation_config_from_body(setup_body("hanjin_pretoria")))
        await settle()
        answer = next(payload for payload in websocket.sent if payload["type"] == "simulation_models")
        assert answer["connectionsByAgentId"]["0"]["vesselModelPreset"] == "hanjin_pretoria"
        assert "block coefficient 0.817" in answer["connectionsByAgentId"]["0"]["gazeboVesselModel"]
