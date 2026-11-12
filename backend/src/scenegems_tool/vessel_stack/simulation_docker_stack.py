"""Simulation instance builder for Docker-based stacks: a thin caller of the adapter registry.

The instance is resolved first, so an unavailable stack or an unsupported environment is
rejected before anything is generated. Then every layer brings its own containers: the
simulation layer one simulator for the scenario, and per vessel the control layer its
controller and the ASV system adapter its ASV system (contracts/docker_stack.py).

The stack is always part of something that runs it and names its containers: a simulation job
(cluster/worker_node/jobs/simulation_runners/vessel_job_stack.py) or a calibration run. Its
network is the caller's to name, so the compose document declares it without one.
"""

import json
import logging
import os
from typing import List, Optional, Tuple

from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.trajectories import Trajectories
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.docker_stack import DockerAsvSystem, DockerControlLayer, DockerSimulationLayer, DockerStackArtifacts, DockerStackRequest
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.roles import LayerRef
from scenegems_tool.vessel_stack.contracts.stack_services import STACK_NETWORK
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig
from scenegems_tool.vessel_stack.registry.adapter_registry import AdapterRegistry
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.vessel_stack.registry.resolver import StackUnavailableError
from utils.file_system_utils import GAZEBO_GEN_MOUNT, SIMULATION_GEN_FOLDER, docker_volume_path, merge_compose_volumes

_logger = logging.getLogger(__name__)


def _contributor(registry: AdapterRegistry, spec_id: str, kind: type) -> Optional[object]:
    """The spec's contributor to the stack; None for a spec that runs in no container of its own."""
    contributor_class = registry.docker(spec_id)
    if contributor_class is None:
        return None
    if not issubclass(contributor_class, kind):
        raise StackUnavailableError([f"the Docker stack class of {spec_id} is no {kind.__name__}"])
    return contributor_class()


def build_simulation_docker_stack_artifacts(
    simulation_config: SimulationInstanceConfig,
    trajectories: Trajectories,
    mqtt_connection: MQttConnectionInfo,
    reference_geofence: Geofence,
    *,
    headless: bool = True,
    gen_folder: str = SIMULATION_GEN_FOLDER,
) -> Tuple[List[Tuple[str, str]], dict]:
    """The files to write and the compose services of one instance. gen_folder must lie on the runtime assets volume."""
    resolver = default_resolver()
    resolution = resolver.require_instance(simulation_config)
    for warning in resolution.warnings:
        _logger.warning("Simulation stack: %s", warning)

    request = DockerStackRequest(
        simulation=simulation_config,
        trajectories=trajectories,
        mqtt_connection=mqtt_connection,
        reference_geofence=reference_geofence,
        headless=headless,
        gen_folder=gen_folder,
        mounted_gen_folder=GAZEBO_GEN_MOUNT if gen_folder == SIMULATION_GEN_FOLDER else docker_volume_path(gen_folder),
    )
    artifacts = DockerStackArtifacts()
    registry = resolver.registry
    simulation_ref = LayerRef.of(simulation_config.simulation_layer)
    simulation_layer = _contributor(registry, str(simulation_ref), DockerSimulationLayer)
    if simulation_layer is None:
        raise StackUnavailableError([f"{simulation_ref} has no Docker stack adapter"])
    for agent_id, vessel_config in simulation_config.vessels.items():
        vessel = trajectories.initial_scene.get_by_id(agent_id)
        if not isinstance(vessel, ConcreteVessel):
            raise ValueError(f"Vessel {vessel} is not a ConcreteVessel.")
        if not vessel_config.is_simulated:
            continue
        state = trajectories.initial_scene[vessel]
        asv_adapter = resolution.chains[agent_id].asv_adapter
        contributors = (
            simulation_layer,
            _contributor(registry, str(LayerRef.of(vessel_config.stack.control_layer)), DockerControlLayer),
            _contributor(registry, asv_adapter.id, DockerAsvSystem) if asv_adapter is not None else None,
        )
        for contributor in contributors:
            if contributor is not None:
                contributor.add_vessel(artifacts, request, vessel_config, vessel, state)
    simulation_layer.finish(artifacts, request)
    # The trajectories go with the generated files.
    artifacts.pending_writes.append((f"{gen_folder}/trajectories.json", json.dumps(trajectories.to_dict())))

    docker_compose = {"services": artifacts.services, "networks": {STACK_NETWORK: {"driver": "bridge"}}}
    if any(service.get("volumes") for service in artifacts.services.values()):
        # Only a stack with a simulator that reads generated files needs the runtime assets volume where it runs;
        # a kinematic stack declares none, so a worker node without that volume runs it.
        docker_compose = merge_compose_volumes(docker_compose)
    return artifacts.pending_writes, docker_compose


def write_simulation_gen_files(pending_writes: List[Tuple[str, str]], gen_folder: str = SIMULATION_GEN_FOLDER) -> None:
    os.makedirs(gen_folder, exist_ok=True)
    for path, content in pending_writes:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as file:
            file.write(content)
