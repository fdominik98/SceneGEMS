"""CustomControlLayer: every vessel on the custom controller gets its own controller container in the Docker stack."""

import pytest

from scenegems_tool.vessel_stack.contracts.docker_stack import DockerControlLayer, DockerStackArtifacts
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.control_layers.custom.custom_control_layer import CustomControlLayer
from tests.scenegems_tool.vessel_stack.scenarios import stack_instance, straight_trajectories


def test_it_is_a_docker_control_layer():
    assert isinstance(CustomControlLayer(), DockerControlLayer)


def test_a_custom_vessel_adds_its_controller_container_and_no_file():
    instance = stack_instance(SimulationLayerId.GAZEBO, [0], control_layer=ControlLayerId.CUSTOM)
    trajectories = straight_trajectories()
    vessel = trajectories.initial_scene.vessels[0]
    artifacts = DockerStackArtifacts()
    CustomControlLayer().add_vessel(artifacts, None, instance.vessels["0"], vessel, trajectories.initial_scene[vessel])
    assert artifacts.pending_writes == []
    ((name, service),) = artifacts.services.items()
    assert name == "agent_0_controller"
    assert service["command"] == ["python", "-m", "scenegems_tool.vessel_stack.control_layers.custom.custom_controller_server", "--port", "11420"]
    assert service["networks"] == ["maritime_net"] and "ports" not in service and "volumes" not in service


def test_it_drives_gazebo_only():
    instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0], control_layer=ControlLayerId.CUSTOM)
    trajectories = straight_trajectories()
    vessel = trajectories.initial_scene.vessels[0]
    with pytest.raises(ValueError, match="Gazebo only"):
        CustomControlLayer().add_vessel(DockerStackArtifacts(), None, instance.vessels["0"], vessel, trajectories.initial_scene[vessel])
