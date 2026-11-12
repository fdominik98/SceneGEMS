"""The Gazebo model of every vessel of a workbench setup that has none yet, for the console to show and edit.

A helper of the gateway: it generates text and starts nothing. The simulation job generates the
same models for the vessels a setup leaves without one.
"""

from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_generator import GAZEBO_MODEL_CONTROL_LAYERS, generate_vessel_model


def generate_vessel_models(scene: ConcreteScene, simulation_config: SimulationInstanceConfig) -> SimulationInstanceConfig:
    """Fills in the model of each simulated vessel on a control layer that has a Gazebo model; a vessel that brings its own keeps it."""
    for vessel_config in simulation_config.vessels.values():
        if vessel_config.gazebo_vessel_model is not None or not vessel_config.is_simulated:
            continue
        if vessel_config.stack.control_layer not in GAZEBO_MODEL_CONTROL_LAYERS:
            continue  # a kinematic vessel has no Gazebo model
        vessel = scene.get_by_id(vessel_config.agent_id)
        if not isinstance(vessel, ConcreteVessel):
            continue
        vessel_config.gazebo_vessel_model = generate_vessel_model(vessel, vessel_config.require_connection().agent_name, vessel_config.stack.control_layer, simulation_config.environment)
    return simulation_config
