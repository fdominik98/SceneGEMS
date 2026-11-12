"""Contract for the layers and adapters that contribute files and services to a stack's Docker Compose file.

The simulation instance builder (vessel_stack/simulation_docker_stack.py) resolves the
instance through the registry, then asks the simulation layer and, per vessel, the control
layer and the ASV system adapter for their part: each brings the containers it runs in. A
contributor is bound to its spec in the registry (registry/catalog.py, docker=); a layer that
runs in no container of its own (control layer none) has none. Services appear in the compose
file in the order they are added.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Protocol, Tuple, runtime_checkable

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.trajectories import Trajectories
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import SimulationInstanceConfig, VesselConfig
from utils.file_system_utils import GAZEBO_GEN_MOUNT, SIMULATION_GEN_FOLDER


@dataclass(frozen=True)
class DockerStackRequest:
    simulation: SimulationInstanceConfig
    trajectories: Trajectories
    mqtt_connection: MQttConnectionInfo
    reference_geofence: Geofence
    headless: bool
    # Where the generated files go: the shared folder of a calibration run, or a per-job folder. Both
    # lie on the runtime assets volume; mounted_gen_folder is the same folder as the
    # simulator containers see it.
    gen_folder: str = SIMULATION_GEN_FOLDER
    mounted_gen_folder: str = GAZEBO_GEN_MOUNT


@dataclass
class DockerStackArtifacts:
    pending_writes: List[Tuple[str, str]] = field(default_factory=list)  # (path in the gen folder, content)
    services: Dict[str, dict] = field(default_factory=dict)


@runtime_checkable
class DockerSimulationLayer(Protocol):
    def add_vessel(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None: ...

    def finish(self, artifacts: DockerStackArtifacts, request: DockerStackRequest) -> None:
        """Add the instance-wide part (world, simulator service) after every vessel."""


@runtime_checkable
class DockerControlLayer(Protocol):
    def add_vessel(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None: ...


@runtime_checkable
class DockerAsvSystem(Protocol):
    """The container of one vessel's ASV system, added by the adapter that runs it."""

    def add_vessel(self, artifacts: DockerStackArtifacts, request: DockerStackRequest, vessel_config: VesselConfig, vessel: ConcreteVessel, state: ActorState) -> None: ...
