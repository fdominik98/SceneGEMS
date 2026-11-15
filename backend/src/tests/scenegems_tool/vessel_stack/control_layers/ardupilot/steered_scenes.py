"""Encounters whose vessels have a given steering type, and the stacks generated for them."""

import dataclasses
from typing import Dict, Mapping, Tuple

from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_scene, mqtt_connection


def steered_encounter(steering_types: Mapping[int, str], timespan: int = 60) -> Trajectories:
    """The head-on encounter with the steering type of each vessel id; a vessel not named keeps its own (skid)."""
    scene = encounter_scene("head_on")
    steered = {dataclasses.replace(vessel, _steering_type=steering_types.get(vessel.id, vessel.steering_type.value)): state for vessel, state in scene.sorted_actor_states}
    return TrajectoryBuilder.default_trajectory_from_scene(ConcreteScene(steered), 1, timespan)


def build_steered_stack(instance: SimulationInstanceConfig, steering_types: Mapping[int, str]) -> Tuple[Dict[str, str], dict]:
    """(generated files by name, compose document) of the instance on the head-on encounter with these steering types."""
    writes, compose = build_simulation_docker_stack_artifacts(instance, steered_encounter(steering_types), mqtt_connection(), GEOFENCE, headless=True)
    return {path.rsplit("/", 1)[-1]: content for path, content in writes}, compose
