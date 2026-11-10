"""The trajectory generation pool: the trajectory generation MQTT service with its planner workers."""

from typing import Optional

from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope
from scenegems_tool.cluster.worker_node.launchers.pooled.pooled_service import SERVICE_CPUS, PooledService, PoolNames
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

_SERVICE_KEY = "trajectory_generation"


class TrajectoryGenerationPool(PooledService):
    subsystem = Subsystem.TRAJECTORY_GENERATION

    @classmethod
    def for_scope(
        cls,
        scope: InstanceScope,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        workers: int,
        broker_network: Optional[str] = None,
    ) -> "TrajectoryGenerationPool":
        return cls(
            PoolNames.for_scope(scope, _SERVICE_KEY),
            mqtt_connection,
            reference_geofence,
            cpus=workers + SERVICE_CPUS,
            workers=workers,
            broker_network=broker_network,
        )
