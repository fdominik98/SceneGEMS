from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Sequence

from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.gateway.protocol import ServerMessage
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.messaging.mqtt_monitor_client import MqttMonitorClient
from scenegems_tool.messaging.mqtt_scenegems_service import MqttSceneGEMSService
from scenegems_tool.subsystems.monitoring.monitor_session import MonitorSession
from scenegems_tool.subsystems.monitoring.monitors import ExternalMonitor, InternalMonitor, MonitorBase


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

        if scope == "external":
            # An external monitor is someone else's agent: it listens on the unscoped WARA-PS topics.
            mqtt_connection = mqtt_connection.with_topic_prefix("")
        self.client = MqttMonitorClient(
            mqtt_connection,
            topic,
            name,
            parent_client.reference_geofence,
            parent_client.name,
            send_payload,
        )
        self.monitor = self._get_monitor(scope, self.client, colregs_constraints_content)
        self._destroyed = False
        self._step_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="monitor_step")
        self.client.connect()

    def step_preview_monitor_batch(
        self,
        scenario_id: str,
        scenes: Sequence[ConcreteScene],
        timestamps: Sequence[int],
        time_step: int,
    ) -> None:
        self._enqueue_step(scenario_id, scenes, timestamps, time_step, is_simulation_frame=False)

    def step_simulation_monitor_batch(
        self,
        scenario_id: str,
        scenes: Sequence[ConcreteScene],
        timestamps: Sequence[int],
        time_step: int,
    ) -> None:
        self._enqueue_step(scenario_id, scenes, timestamps, time_step, is_simulation_frame=True)

    def _enqueue_step(
        self,
        scenario_id: str,
        scenes: Sequence[ConcreteScene],
        timestamps: Sequence[int],
        time_step: int,
        *,
        is_simulation_frame: bool,
    ) -> None:
        if not scenes:
            return
        scene_list = list(scenes)
        timestamp_list = list(timestamps)
        if self._destroyed:
            self.send_unmonitored_chunk(scenario_id, scene_list, timestamp_list, time_step, is_simulation_frame=is_simulation_frame)
            return
        try:
            self._step_executor.submit(self._run_step, scenario_id, scene_list, timestamp_list, time_step, is_simulation_frame)
        except RuntimeError:
            self.send_unmonitored_chunk(scenario_id, scene_list, timestamp_list, time_step, is_simulation_frame=is_simulation_frame)

    def _run_step(
        self,
        scenario_id: str,
        scenes: Sequence[ConcreteScene],
        timestamps: Sequence[int],
        time_step: int,
        is_simulation_frame: bool,
    ) -> None:
        if self._destroyed:
            return
        try:
            self.client.publish_step_monitor_batch_command(
                scenario_id=scenario_id,
                scenes=scenes,
                timestamps=timestamps,
                time_step=time_step,
                is_simulation_frame=is_simulation_frame,
            )
        except Exception as exc:
            kind = "simulation" if is_simulation_frame else "preview"
            print(f"Monitor unavailable for {kind} frames, sending them unmonitored: {exc}")
            if not self._destroyed:
                self.send_unmonitored_chunk(scenario_id, scenes, timestamps, time_step, is_simulation_frame=is_simulation_frame)

    def _destroy(self) -> None:
        self._destroyed = True
        self._step_executor.shutdown(wait=False, cancel_futures=True)
        self.client.disconnect()
        self.monitor.destroy()

    def _get_monitor(self, scope: str, client: MqttMonitorClient, colregs_constraints_content: str) -> MonitorBase:
        match scope:
            case "internal":
                return InternalMonitor(
                    colregs_constraints_content,
                    client.mqtt_connection,
                    client.reference_geofence,
                    client.agent_name,
                    client.topic,
                )
            case "external":
                return ExternalMonitor()
            case _:
                raise ValueError(f"Invalid monitor scope: {scope}")

    @property
    def is_connected(self) -> bool:
        return self.client.is_connected and self.client.is_heartbeat_valid
