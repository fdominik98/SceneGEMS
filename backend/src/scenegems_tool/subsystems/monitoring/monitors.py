from abc import ABC, abstractmethod

from scenegems_tool.cluster.worker_node.launchers.pooled.monitor_service import MonitorService
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence


class MonitorBase(ABC):
    @abstractmethod
    def destroy(self):
        pass


class ExternalMonitor(MonitorBase):
    def destroy(self) -> None:
        pass


class InternalMonitor(MonitorBase):
    def __init__(
        self,
        colregs_constraints_content: str,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        agent_name: str,
        topic: str,
    ):
        self._container = MonitorService.for_workbench(
            mqtt_connection=mqtt_connection,
            reference_geofence=reference_geofence,
            agent_name=agent_name,
            topic=topic,
            colregs_constraints_content=colregs_constraints_content,
        )

    def destroy(self) -> None:
        self._container.destroy()
