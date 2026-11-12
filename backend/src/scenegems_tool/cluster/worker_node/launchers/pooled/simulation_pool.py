"""The simulation pool: the simulation MQTT service, whose tasks start and remove the vessel stacks of their runs.

It is the one pooled service that starts containers, so its container gets what the worker node's daemon has for
that: the Docker socket, the runtime assets volume (the compose files and the generated simulator files of its
stacks, which SITL and Gazebo mount too) and the names its stacks are built with: the worker node's ids, the
network the cluster's broker is reached on, the runtime volume, the image tag and every image override the
daemon was started with. A stack it starts sits next to it in the worker node's compose project.
"""

import os
from typing import Dict, Optional

from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope
from scenegems_tool.cluster.worker_node.launchers.pooled.pooled_service import SERVICE_CPUS, PooledService, PoolNames
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.subsystems.simulation.simulation_types import BROKER_NETWORK_VARIABLE, CONTROL_NODE_VARIABLE, SIMULATION_SERVICE_NAME, WORKER_NODE_VARIABLE
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from utils.docker_compose_network import scenegems_broker_network_name
from utils.file_system_utils import RUNTIME_ASSETS_VOLUME, runtime_assets_volume_mount
from utils.image_names import IMAGE_TAG_VARIABLE

_SERVICE_KEY = "simulation"
DOCKER_SOCKET = "/var/run/docker.sock"
RUNTIME_VOLUME_VARIABLE = "SCENEGEMS_RUNTIME_VOLUME"
IMAGE_OVERRIDE_SUFFIX = "_IMAGE"  # SIMULATION_IMAGE, SITL_IMAGE, GAZEBO_IMAGE, ...: an image a stack runs instead of the release's


def image_overrides(environment: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """The image overrides and the image tag of the launcher's environment, which the stacks of the pool's tasks have to be built with as well."""
    environment = dict(os.environ) if environment is None else environment
    passed = {name: value for name, value in environment.items() if name.endswith(IMAGE_OVERRIDE_SUFFIX) and value.strip()}
    if environment.get(IMAGE_TAG_VARIABLE, "").strip():
        passed[IMAGE_TAG_VARIABLE] = environment[IMAGE_TAG_VARIABLE]
    return passed


class SimulationPool(PooledService):
    default_service_name = SIMULATION_SERVICE_NAME
    subsystem = Subsystem.SIMULATION

    def __init__(self, names: PoolNames, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence, *, control_node_id: str, worker_node_id: str, **options):
        self.control_node_id = control_node_id
        self.worker_node_id = worker_node_id
        super().__init__(names, mqtt_connection, reference_geofence, **options)

    @classmethod
    def for_scope(
        cls,
        scope: InstanceScope,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        workers: int,
        broker_network: Optional[str] = None,
        service_name: Optional[str] = None,
    ) -> "SimulationPool":
        return cls(
            PoolNames.for_scope(scope, _SERVICE_KEY),
            mqtt_connection,
            reference_geofence,
            control_node_id=scope.control_node_id,
            worker_node_id=scope.worker_node_id,
            # The tasks' work is in their stacks' containers; a worker waits for its runner and relays
            cpus=SERVICE_CPUS + workers,
            workers=workers,
            broker_network=broker_network,
            service_name=service_name,
        )

    def build_compose(self) -> dict:
        compose = super().build_compose()
        service = compose["services"][self.names.service_key]
        service["environment"] = {
            **service["environment"],
            **image_overrides(),
            CONTROL_NODE_VARIABLE: self.control_node_id,
            WORKER_NODE_VARIABLE: self.worker_node_id,
            BROKER_NETWORK_VARIABLE: self.broker_network or scenegems_broker_network_name(),
            RUNTIME_VOLUME_VARIABLE: RUNTIME_ASSETS_VOLUME,
        }
        service["volumes"] = [f"{DOCKER_SOCKET}:{DOCKER_SOCKET}", runtime_assets_volume_mount()]
        return compose
