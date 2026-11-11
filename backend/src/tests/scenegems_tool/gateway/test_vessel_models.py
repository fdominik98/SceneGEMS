"""The Gazebo vessel models the gateway generates for a workbench setup: one per simulated vessel that needs one and has none."""

import pytest

from scenegems_tool.gateway.vessel_models import generate_vessel_models
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentContext, VesselStackConfig
from tests.scenegems_tool.vessel_stack.scenarios import encounter_scene, stack_instance


def test_every_simulated_vessel_on_a_modelled_control_layer_gets_a_model():
    config = stack_instance(SimulationLayerId.GAZEBO, [0, 1])
    assert generate_vessel_models(encounter_scene("head_on"), config) is config
    models = [vessel.gazebo_vessel_model for vessel in config.vessels.values()]
    assert all(isinstance(model, str) and "<sdf" in model for model in models)
    assert "agent_0" in models[0] and "agent_1" in models[1], "a model is named after its vessel"


def test_a_vessel_that_brings_its_own_model_keeps_it():
    config = stack_instance(SimulationLayerId.GAZEBO, [0, 1])
    config.vessels["0"].gazebo_vessel_model = "<sdf>mine</sdf>"
    generate_vessel_models(encounter_scene("head_on"), config)
    assert config.vessels["0"].gazebo_vessel_model == "<sdf>mine</sdf>" and config.vessels["1"].gazebo_vessel_model != "<sdf>mine</sdf>"


def test_a_kinematic_vessel_and_a_real_vessel_have_no_model():
    kinematic = stack_instance(SimulationLayerId.KINEMATIC, [0, 1], control_layer=ControlLayerId.NONE)
    generate_vessel_models(encounter_scene("head_on"), kinematic)
    assert [vessel.gazebo_vessel_model for vessel in kinematic.vessels.values()] == [None, None]

    with_real = stack_instance(SimulationLayerId.GAZEBO, [0, 1])
    with_real.vessels["1"].context = AgentContext.REAL
    with_real.vessels["1"].stack = VesselStackConfig(AsvSystemId.ON_BOARD, ControlLayerId.REAL_VESSEL, SimulationLayerId.REAL_VESSEL)
    generate_vessel_models(encounter_scene("head_on"), with_real)
    assert with_real.vessels["0"].gazebo_vessel_model is not None and with_real.vessels["1"].gazebo_vessel_model is None


def test_a_setup_for_a_vessel_the_scene_does_not_have_is_refused():
    config = stack_instance(SimulationLayerId.GAZEBO, [0, 7])
    with pytest.raises(ValueError, match="Vessel with id 7 not found"):
        generate_vessel_models(encounter_scene("head_on"), config)
