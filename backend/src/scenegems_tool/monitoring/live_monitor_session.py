from typing import Callable, Sequence

from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.backend_service.protocol import ServerMessage
from scenegems_tool.monitoring.monitor_session import MonitorSession
from scenegems_tool.monitoring.monitors import ExternalMonitor, InternalMonitor, MonitorBase
from scenegems_tool.waraps_integration.mqtt_client import MQttConnectionInfo
from scenegems_tool.waraps_integration.mqtt_monitor_client import MqttMonitorClient
from scenegems_tool.waraps_integration.mqtt_scenegems_service import MqttSceneGEMSService


class LiveMonitorSession(MonitorSession):
    def __init__(
        self,
        name: str,
        topic: str,
        scope: str,
        mqtt_connection: MQttConnectionInfo,
        parent_client: MqttSceneGEMSService,
        colregs_constraints_content: str,
        send_payload: Callable[[ServerMessage], None],
    ) -> None:
        super().__init__(send_payload)

        self.client = MqttMonitorClient(
            mqtt_connection,
            topic,
            name,
            parent_client.reference_geofence,
            parent_client.name,
            send_payload,
        )
        self.monitor = self._get_monitor(scope, self.client, colregs_constraints_content)
        self.client.connect()

    def step_preview_monitor_batch(
        self,
        scenario_id: str,
        scenes: Sequence[ConcreteScene],
        timestamps: Sequence[int],
        time_step: int,
    ) -> None:
        if not scenes:
            return
        self.client.wait_for_heartbeat()
        self.client.publish_step_monitor_batch_command(
            scenario_id=scenario_id,
            scenes=scenes,
            timestamps=timestamps,
            time_step=time_step,
            is_simulation_frame=False,
        )

    def step_simulation_monitor_batch(
        self,
        scenario_id: str,
        scenes: Sequence[ConcreteScene],
        timestamps: Sequence[int],
        time_step: int,
    ) -> None:
        if not scenes:
            return
        self.client.wait_for_heartbeat()
        self.client.publish_step_monitor_batch_command(
            scenario_id=scenario_id,
            scenes=scenes,
            timestamps=timestamps,
            time_step=time_step,
            is_simulation_frame=True,
        )

    def _destroy(self) -> None:
        self.client.disconnect()
        self.monitor.destroy()

    def _get_monitor(self, scope: str, client: MqttMonitorClient, colregs_constraints_content: str) -> MonitorBase:
        match scope:
            case "internal":
                return InternalMonitor(
                    colregs_constraints_content,
                    client.mqtt_connection,
                    client.reference_geofence,
                    client.name,
                    client.topic,
                )
            case "external":
                return ExternalMonitor()
            case _:
                raise ValueError(f"Invalid monitor scope: {scope}")

    @property
    def is_connected(self) -> bool:
        return self.client.is_connected and self.client.is_heartbeat_valid
