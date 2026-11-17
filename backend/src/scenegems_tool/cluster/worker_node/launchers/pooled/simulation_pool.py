"""The simulation pool: the simulation MQTT service, whose tasks start and remove the pods of their runs.

It is the one pooled service that creates objects in the cluster, so its pod runs under the simulation subsystem's
service account (SIMULATION_SERVICE_ACCOUNT, whose role the chart gives), with the worker node's runtime folder of
its node mounted where the image has its runtime assets folder (a run's files are there, and a run's pod mounts the
same folder), and the names its runs are built with in its environment: the worker node's ids, the namespace, the
node and the runtime folder's path on the node, the image tag and every image override the daemon was started with.
"""

import os
from typing import Any, Dict, Optional

from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope
from scenegems_tool.cluster.worker_node.launchers.kubernetes_api import ClusterPlace, KubernetesApi
from scenegems_tool.cluster.worker_node.launchers.pooled.pooled_service import SERVICE_CPUS, PooledService, PoolNames
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.subsystems.simulation.simulation_types import (
    CONTROL_NODE_VARIABLE,
    KUBERNETES_NAMESPACE_VARIABLE,
    KUBERNETES_NODE_VARIABLE,
    RUNTIME_HOST_PATH_VARIABLE,
    SIMULATION_SERVICE_NAME,
    WORKER_NODE_VARIABLE,
)
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from utils.file_system_utils import IMAGE_RUNTIME_ASSETS_FOLDER
from utils.image_names import IMAGE_TAG_VARIABLE

SIMULATION_SERVICE_ACCOUNT = "simulation-subsystem"  # the chart's service account with the rights a run's pod needs
RUNTIME_VOLUME = "runtime"  # the pod's volume of the runtime folder
IMAGE_OVERRIDE_SUFFIX = "_IMAGE"  # SIMULATION_IMAGE, SITL_IMAGE, GAZEBO_IMAGE, ...: an image a run uses instead of the release's


def image_overrides(environment: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """The image overrides and the image tag of the launcher's environment, which the runs of the pool's tasks have to be built with as well."""
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
        cluster: ClusterPlace,
        api: KubernetesApi,
        service_name: Optional[str] = None,
    ) -> "SimulationPool":
        return cls(
            PoolNames.for_scope(scope),
            mqtt_connection,
            reference_geofence,
            control_node_id=scope.control_node_id,
            worker_node_id=scope.worker_node_id,
            # The tasks' work is in their runs' pods; a worker waits for its runner and relays
            cpus=SERVICE_CPUS + workers,
            workers=workers,
            cluster=cluster,
            api=api,
            service_name=service_name,
        )

    def environment(self) -> Dict[str, str]:
        return {
            **super().environment(),
            **image_overrides(),
            CONTROL_NODE_VARIABLE: self.control_node_id,
            WORKER_NODE_VARIABLE: self.worker_node_id,
            KUBERNETES_NAMESPACE_VARIABLE: self.cluster.namespace,
            KUBERNETES_NODE_VARIABLE: self.cluster.node,
            RUNTIME_HOST_PATH_VARIABLE: self.cluster.runtime_host_path,
        }

    def pod_spec(self) -> Dict[str, Any]:
        spec = super().pod_spec()
        spec["serviceAccountName"] = SIMULATION_SERVICE_ACCOUNT
        spec["automountServiceAccountToken"] = True  # it creates its runs' pods
        spec["volumes"] = [{"name": RUNTIME_VOLUME, "hostPath": {"path": self.cluster.runtime_host_path, "type": "DirectoryOrCreate"}}]
        # At the folder's path in the image: where the subsystem writes a run's files, whatever the path is on the node
        spec["containers"][0]["volumeMounts"] = [{"name": RUNTIME_VOLUME, "mountPath": IMAGE_RUNTIME_ASSETS_FOLDER}]
        return spec
