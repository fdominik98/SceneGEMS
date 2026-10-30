"""The simulator image tags, read from the vessel stack containers as job_images reads them for the simulation job types."""

from scenegems_tool.vessel_stack.control_layers.ardupilot.ardupilot_specs import SITL_CONTAINER
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_specs import GAZEBO_CONTAINER

SITL_IMAGE = SITL_CONTAINER.default_image
GAZEBO_IMAGE = GAZEBO_CONTAINER.default_image
