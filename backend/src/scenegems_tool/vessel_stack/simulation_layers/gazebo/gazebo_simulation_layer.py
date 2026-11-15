"""Gazebo simulation layer adapter: the generated ocean world, one SDF model per vessel and the Gazebo service.

The vessels of one world are all driven by ArduPilot (SITL in lockstep with each model's
ArduPilotPlugin, the world running on its own) or all by the custom controller (the world paused
and stepped by the gz-transport actuator, gz_transport_actuator.py). One world cannot do both, so
an instance that mixes the two control layers is rejected.
"""

from typing import List, Tuple

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.contracts.docker_stack import DockerStackArtifacts, DockerStackRequest
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig, VesselConfig
from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_specs import GAZEBO_LAYER, wave_forces_enabled
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.gazebo_service_generator import generate_gazebo_service
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_catalog import vessel_dynamics_overrides
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_generator import generate_hull_mesh, generate_vessel_model, hull_mesh_filename
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.world_generator import generate_world
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_transport_actuator import DEFAULT_PORT as ACTUATOR_PORT


def externally_stepped(simulation: SimulationInstanceConfig) -> bool:
    """Whether the world is stepped by the gz-transport actuator: its vessels are on the custom control layer.

    Raises StackUnavailableError for an instance that mixes the custom and the ardupilot control layer.
    """
    layers = {vessel.stack.control_layer for vessel in simulation.simulated_vessels.values()}
    if ControlLayerId.CUSTOM in layers and len(layers) > 1:
        raise StackUnavailableError([f"a Gazebo world steps either with ArduPilot or with the custom controller, but this instance mixes {', '.join(sorted(layer.value for layer in layers))}"])
    return layers == {ControlLayerId.CUSTOM}


class GazeboWorldFiles:
    """Writes one SDF model per vessel and the world that includes them at their start poses."""

    def __init__(self):
        self._vessel_includes: List[Tuple[str, ActorState]] = []

    def add_vessel_model(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None:
        agent_name = vessel_config.require_connection().agent_name
        # The hull and steering values of the vessel's preset of the vessel model catalog, when it has one.
        overrides = vessel_dynamics_overrides(vessel, vessel_config.vessel_model_preset)
        if vessel_config.gazebo_vessel_model is not None:
            vessel_model = vessel_config.gazebo_vessel_model
        else:
            vessel_model = generate_vessel_model(vessel, agent_name, vessel_config.stack.control_layer, request.simulation.environment, overrides)
        vessel_model_filename = f"{agent_name}_model.sdf"
        artifacts.pending_writes.append((f"{request.gen_folder}/{vessel_model_filename}", vessel_model))
        # The hull surface a generated model shows, next to it. A vessel that brings its own model
        # gets the file too: a model the console generated and sent back refers to it.
        artifacts.pending_writes.append((f"{request.gen_folder}/{hull_mesh_filename(agent_name)}", generate_hull_mesh(vessel, agent_name, overrides)))
        self._vessel_includes.append((f"{request.mounted_gen_folder}/{vessel_model_filename}", state))

    def add_world(self, artifacts: DockerStackArtifacts, request: DockerStackRequest) -> str:
        os_state = request.trajectories.initial_scene.os_state
        lat_long = request.reference_geofence.to_lat_long(os_state.p)
        environment = request.simulation.environment
        world_model = generate_world(
            lat_long,
            self._vessel_includes,
            environment.wind_vector,
            environment.wave,
            request.simulation.speedup,
            headless=request.headless,
            wave_forces=wave_forces_enabled(environment),
            externally_stepped=externally_stepped(request.simulation),
        )
        world_file = f"{request.gen_folder}/ocean_world.sdf"
        artifacts.pending_writes.append((world_file, world_model))
        return world_file


class GazeboSimulationLayer:
    spec = GAZEBO_LAYER

    def __init__(self):
        self._world_files = GazeboWorldFiles()

    def add_vessel(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None:
        self._world_files.add_vessel_model(artifacts, request, vessel_config, vessel, state)

    def finish(self, artifacts: DockerStackArtifacts, request: DockerStackRequest) -> None:
        world_file = self._world_files.add_world(artifacts, request)
        # Gazebo waits for every agent name, real vessels included, exactly as before the
        # adapter framework, although a real vessel has no service (see the Phase 1 notes).
        agent_names = [vessel_config.require_connection().agent_name for vessel_config in request.simulation.vessels.values()]
        if externally_stepped(request.simulation):
            # The custom controller runs in the runner, so no vessel has a service of its own.
            services = generate_gazebo_service(world_file, [], headless=request.headless, display="host.docker.internal:0.0", verbose=4, actuator_port=ACTUATOR_PORT)
        else:
            services = generate_gazebo_service(world_file, agent_names, headless=request.headless, display="host.docker.internal:0.0", verbose=4)
        artifacts.services.update(services)
