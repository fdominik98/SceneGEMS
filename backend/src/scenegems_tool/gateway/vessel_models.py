"""The Gazebo model of every vessel of a workbench setup that has none yet, for the console to show and edit,
and the presets of the vessel model catalog each vessel of a scenario can take.

A helper of the gateway: it generates text and starts nothing. The simulation job generates the
same models for the vessels a setup leaves without one.
"""

from typing import Optional

from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.gateway.protocol import VesselModelPresetsMessage
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_catalog import VesselModelCatalog, load_vessel_model_catalog, vessel_dynamics_overrides
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_generator import GAZEBO_MODEL_CONTROL_LAYERS, generate_vessel_model


def generate_vessel_models(scene: ConcreteScene, simulation_config: SimulationInstanceConfig) -> SimulationInstanceConfig:
    """Fills in the model of each simulated vessel on a control layer that has a Gazebo model; a vessel that brings its own keeps it.

    A vessel with a preset of the vessel model catalog gets that preset's hull and steering values.
    UnknownVesselModelPreset or VesselOutOfPresetBounds (both ValueError) for a preset the vessel cannot take.
    """
    for vessel_config in simulation_config.vessels.values():
        if vessel_config.gazebo_vessel_model is not None or not vessel_config.is_simulated:
            continue
        if vessel_config.stack.control_layer not in GAZEBO_MODEL_CONTROL_LAYERS:
            continue  # a kinematic vessel has no Gazebo model
        vessel = scene.get_by_id(vessel_config.agent_id)
        if not isinstance(vessel, ConcreteVessel):
            continue
        vessel_config.gazebo_vessel_model = generate_vessel_model(
            vessel,
            vessel_config.require_connection().agent_name,
            vessel_config.stack.control_layer,
            simulation_config.environment,
            vessel_dynamics_overrides(vessel, vessel_config.vessel_model_preset),
        )
    return simulation_config


def check_vessel_model_presets(scene: ConcreteScene, simulation_config: SimulationInstanceConfig) -> None:
    """Raises UnknownVesselModelPreset or VesselOutOfPresetBounds (both ValueError) for a vessel whose chosen preset it cannot take."""
    for vessel_config in simulation_config.vessels.values():
        if vessel_config.vessel_model_preset is None:
            continue
        vessel = scene.get_by_id(vessel_config.agent_id)
        if not isinstance(vessel, ConcreteVessel):
            raise ValueError(f"Vessel {vessel_config.agent_id} has the vessel model preset {vessel_config.vessel_model_preset}, but the scenario has no such vessel.")
        vessel_dynamics_overrides(vessel, vessel_config.vessel_model_preset)


def vessel_model_presets_message(scenario_id: str, scene: ConcreteScene, catalog: Optional[VesselModelCatalog] = None) -> VesselModelPresetsMessage:
    """The presets each vessel of the scene can take, by agent id (the vessel's id as text)."""
    catalog = catalog or load_vessel_model_catalog()
    return VesselModelPresetsMessage(
        type="vessel_model_presets",
        scenarioId=scenario_id,
        presetsByAgentId={str(actor.id): [preset.as_dict() for preset in catalog.eligible(actor)] for actor in scene.actors if isinstance(actor, ConcreteVessel)},
    )
