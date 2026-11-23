"""The monitoring pool: the monitoring MQTT service with its monitor workers, one per series it judges at once."""

from typing import Optional

from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope
from scenegems_tool.cluster.worker_node.launchers.kubernetes_api import ClusterPlace, KubernetesApi
from scenegems_tool.cluster.worker_node.launchers.pooled.pooled_service import SERVICE_CPUS, PooledService, PoolNames
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.subsystems.monitoring.monitoring_types import MONITORING_SERVICE_NAME
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence


class MonitoringPool(PooledService):
    default_service_name = MONITORING_SERVICE_NAME
    subsystem = Subsystem.MONITORING

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
    ) -> "MonitoringPool":
        return cls(
            PoolNames.for_scope(scope),
            mqtt_connection,
            reference_geofence,
            cpus=workers + SERVICE_CPUS,
            workers=workers,
            cluster=cluster,
            api=api,
            service_name=service_name,
        )
