"""Where the simulation stack's generated files go: the workbench folder by default, a per-job folder on request."""

import math

import pytest

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.roles import SimulationLayerId
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_lockstep_runner import mavlink_replay_instance
from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts
from utils.file_system_utils import GAZEBO_GEN_MOUNT, RUNTIME_ASSETS_FOLDER, SIMULATION_GEN_FOLDER, docker_volume_path


@pytest.fixture
def trajectories():
    vessels = [
        ConcreteActor.from_dict(
            {
                "id": vessel_id,
                "type": "PassengerShip",
                "length": 30.0,
                "breadth": 10.0,
                "safety_radius": 120.0,
                "is_vessel": True,
                "_is_os": vessel_id == 0,
                "_max_speed": 20.0,
                "_max_angular_speed": 0.05,
                "_max_acceleration": 0.4,
            }
        )
        for vessel_id in (0, 1)
    ]
    scene = ConcreteScene({vessels[0]: ActorState(0.0, 0.0, 8.0, 0.0), vessels[1]: ActorState(3000.0, 0.0, 8.0, math.pi)})
    return TrajectoryBuilder.default_trajectory_from_scene(scene, 1, 30)


def build(trajectories, **options):
    instance = mavlink_replay_instance(trajectories, SimulationLayerId.GAZEBO)
    connection = MQttConnectionInfo("user", "secret", "broker", "localhost", 1883, False, False)
    return build_simulation_docker_stack_artifacts(instance, trajectories, connection, Geofence(57.7, 11.9, 2000.0), **options)


def test_the_default_gen_folder_is_the_shared_simulation_folder(trajectories):
    pending_writes, compose = build(trajectories)
    assert {path.rsplit("/", 1)[0] for path, _ in pending_writes} == {SIMULATION_GEN_FOLDER}
    world = next(content for path, content in pending_writes if path.endswith("ocean_world.sdf"))
    assert f"{GAZEBO_GEN_MOUNT}/os_model.sdf" in world


def test_custom_gen_folder_receives_every_file(trajectories):
    gen_folder = f"{RUNTIME_ASSETS_FOLDER}/instances/scenegems-m1-n1-job-x-1/gen"
    pending_writes, compose = build(trajectories, gen_folder=gen_folder)
    assert {path.rsplit("/", 1)[0] for path, _ in pending_writes} == {gen_folder}
    world = next(content for path, content in pending_writes if path.endswith("ocean_world.sdf"))
    assert f"{docker_volume_path(gen_folder)}/os_model.sdf" in world
    assert compose["services"]["gazebo"]["environment"]["WORLD_SDF"] == docker_volume_path(f"{gen_folder}/ocean_world.sdf")
