"""The subsystems a node runs, with the image each one runs in."""

import os
from enum import Enum

from utils.image_names import tagged


class Subsystem(str, Enum):
    SCENE_GENERATION = "scene_generation"
    TRAJECTORY_GENERATION = "trajectory_generation"
    MONITORING = "monitoring"
    SCENARIO_EXECUTION = "scenario_execution"


_DEFAULT_IMAGES = {
    Subsystem.SCENE_GENERATION: tagged("scenegems-scene-generation-subsystem"),
    Subsystem.TRAJECTORY_GENERATION: tagged("scenegems-trajectory-generation-subsystem"),
    Subsystem.MONITORING: tagged("scenegems-monitoring-subsystem"),
    Subsystem.SCENARIO_EXECUTION: tagged("scenegems-scenario-execution-subsystem"),
}
# Environment variables that replace a default image, for the workbench and the node alike.
IMAGE_ENVIRONMENT_VARIABLES = {
    Subsystem.SCENE_GENERATION: "SCENE_GENERATION_IMAGE",
    Subsystem.TRAJECTORY_GENERATION: "TRAJECTORY_GENERATION_IMAGE",
    Subsystem.MONITORING: "MONITORING_IMAGE",
    Subsystem.SCENARIO_EXECUTION: "SCENARIO_EXECUTION_IMAGE",
}


def subsystem_image(subsystem: Subsystem) -> str:
    """The image a subsystem runs in: the environment override when set and not empty, else the default with SCENEGEMS_IMAGE_TAG."""
    return os.environ.get(IMAGE_ENVIRONMENT_VARIABLES[subsystem], "").strip() or _DEFAULT_IMAGES[subsystem]
