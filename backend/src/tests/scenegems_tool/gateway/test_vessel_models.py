"""The Gazebo vessel models the gateway generates for a workbench setup: one per simulated vessel that needs one and has none."""

import dataclasses

import pytest

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.gateway.vessel_models import generate_vessel_models
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentContext, VesselStackConfig
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_generator import generate_vessel_model, hull_mesh_filename, steering_topic, thrust_topic
from tests.scenegems_tool.vessel_stack.scenarios import ENCOUNTER_TARGETS, SPEED, encounter_scene, make_vessel, stack_instance
from tests.scenegems_tool.vessel_stack.sdf import child_text, names, parse_sdf, plugins


def steered_scene(own_steering: str, target_steering: str) -> ConcreteScene:
    """The head-on encounter with a steering type for each vessel."""
    own = dataclasses.replace(make_vessel(0, True), _steering_type=own_steering)
    target = dataclasses.replace(make_vessel(1, False), _steering_type=target_steering)
    return ConcreteScene({own: ActorState(0.0, 0.0, SPEED, 0.0), target: ENCOUNTER_TARGETS["head_on"]})


def test_every_simulated_vessel_on_a_modelled_control_layer_gets_a_model():
    config = stack_instance(SimulationLayerId.GAZEBO, [0, 1])
    assert generate_vessel_models(encounter_scene("head_on"), config) is config
    models = [vessel.gazebo_vessel_model for vessel in config.vessels.values()]
    assert all(isinstance(model, str) and "<sdf" in model for model in models)
    assert "agent_0" in models[0] and "agent_1" in models[1], "a model is named after its vessel"


def test_a_vessel_from_a_scene_without_a_steering_type_gets_the_skid_steered_model():
    config = stack_instance(SimulationLayerId.GAZEBO, [0, 1])
    generate_vessel_models(encounter_scene("head_on"), config)
    for agent_id in ("0", "1"):
        root = parse_sdf(config.vessels[agent_id].gazebo_vessel_model)
        assert [child_text(system, "joint_name") for system in plugins(root, "gz-sim-thruster-system")] == ["motor_port_joint", "motor_stbd_joint"]
        assert "steering_joint" not in names(root, "joint")


@pytest.mark.parametrize("control_layer", [ControlLayerId.ARDUPILOT, ControlLayerId.CUSTOM], ids=lambda layer: layer.value)
def test_each_vessel_gets_the_model_of_its_own_steering_type(control_layer):
    """A rudder for the own ship and vectored thrust for the target: one thruster each, with the steering gear the type has."""
    scene = steered_scene("rudder", "vectored_thrust")
    config = stack_instance(SimulationLayerId.GAZEBO, [0, 1], control_layer=control_layer)
    generate_vessel_models(scene, config)
    own, target = (parse_sdf(config.vessels[agent_id].gazebo_vessel_model) for agent_id in ("0", "1"))
    for agent_name, root in (("agent_0", own), ("agent_1", target)):
        assert [child_text(system, "joint_name") for system in plugins(root, "gz-sim-thruster-system")] == ["motor_center_joint"]
        assert "steering_joint" in names(root, "joint")
        (helm,) = plugins(root, "gz-sim-joint-position-controller-system")
        assert child_text(helm, "topic") == steering_topic(agent_name)
        assert thrust_topic(agent_name, "center") in config.vessels[agent_name[-1]].gazebo_vessel_model
        (uri,) = [element.text for element in root.iter("uri")]
        assert uri == hull_mesh_filename(agent_name), "the hull surface is a file the simulation job writes next to the model"
    assert len(plugins(own, "gz-sim-hydrodynamics-system")) == 2, "the rudder has a force of its own"
    assert len(plugins(target, "gz-sim-hydrodynamics-system")) == 1


def test_the_gateways_model_is_the_one_the_simulation_job_generates():
    scene = steered_scene("rudder", "skid")
    config = stack_instance(SimulationLayerId.GAZEBO, [0, 1], control_layer=ControlLayerId.CUSTOM)
    generate_vessel_models(scene, config)
    for agent_id in ("0", "1"):
        vessel = scene.get_by_id(agent_id)
        assert config.vessels[agent_id].gazebo_vessel_model == generate_vessel_model(vessel, f"agent_{agent_id}", ControlLayerId.CUSTOM, config.environment)


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
