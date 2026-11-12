"""The design space exploration pool: the exploration MQTT service with one Refinery generator process per exploration it runs at once."""

from typing import Optional

from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope
from scenegems_tool.cluster.worker_node.launchers.pooled.pooled_service import SERVICE_CPUS, PooledService, PoolNames
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.subsystems.design_space_exploration.design_space_exploration_types import DESIGN_SPACE_EXPLORATION_SERVICE_NAME
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

_SERVICE_KEY = "design_space_exploration"


class DesignSpaceExplorationPool(PooledService):
    default_service_name = DESIGN_SPACE_EXPLORATION_SERVICE_NAME
    subsystem = Subsystem.DESIGN_SPACE_EXPLORATION

    @classmethod
    def for_scope(
        cls,
        scope: InstanceScope,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        workers: int,
        broker_network: Optional[str] = None,
        service_name: Optional[str] = None,
    ) -> "DesignSpaceExplorationPool":
        return cls(
            PoolNames.for_scope(scope, _SERVICE_KEY),
            mqtt_connection,
            reference_geofence,
            cpus=workers + SERVICE_CPUS,
            workers=workers,
            broker_network=broker_network,
            service_name=service_name,
        )
