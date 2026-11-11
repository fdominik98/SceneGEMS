"""The pooled services of one worker node: started on first use, sized by the worker node's slots, removed together.

On MQTT a pool is named after its subsystem and the number the control node gave the worker node
(instance_scope.pooled_service_name), so the pools of a cluster never share a topic.
"""

import threading
from typing import Callable, Dict, Optional

from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope, pooled_service_name
from scenegems_tool.cluster.worker_node.launchers.pooled.pooled_service import PooledService
from scenegems_tool.cluster.worker_node.launchers.pooled.scene_generation_pool import SceneGenerationPool
from scenegems_tool.cluster.worker_node.launchers.pooled.trajectory_generation_pool import TrajectoryGenerationPool
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

_POOL_CLASSES = {
    Subsystem.SCENE_GENERATION: SceneGenerationPool,
    Subsystem.TRAJECTORY_GENERATION: TrajectoryGenerationPool,
}


class ServicePools:
    def __init__(
        self,
        control_node_id: str,
        worker_node_id: str,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        workers: Callable[[Subsystem], int],
        broker_network: Optional[str] = None,
        instance_number: Callable[[], int] = lambda: 1,
    ):
        self.control_node_id = control_node_id
        self.worker_node_id = worker_node_id
        self.mqtt_connection = mqtt_connection
        self.reference_geofence = reference_geofence
        self.workers = workers
        self.broker_network = broker_network
        self.instance_number = instance_number  # read when a pool starts, after the control node's Welcome
        self._pools: Dict[Subsystem, PooledService] = {}
        self._lock = threading.Lock()

    def scope(self, subsystem: Subsystem) -> InstanceScope:
        return InstanceScope.pooled(self.control_node_id, self.worker_node_id, subsystem.value)

    def service_name(self, subsystem: Subsystem) -> str:
        return pooled_service_name(subsystem.value, self.instance_number())

    def get(self, subsystem: Subsystem) -> PooledService:
        """The subsystem's running pool, started with the worker node's worker count the first time it is asked for."""
        with self._lock:
            pool = self._pools.get(subsystem)
            if pool is None:
                pool = _POOL_CLASSES[subsystem].for_scope(
                    self.scope(subsystem), self.mqtt_connection, self.reference_geofence, self.workers(subsystem), self.broker_network, self.service_name(subsystem)
                )
                self._pools[subsystem] = pool
            return pool

    def shutdown(self) -> None:
        with self._lock:
            pools = list(self._pools.values())
            self._pools.clear()
        for pool in pools:
            pool.destroy()
