import json
import threading
import time
from dataclasses import dataclass
from queue import Queue
from typing import Any, List, Sequence, Union

import paho.mqtt.client as mqtt

from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredSceneWithResults
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.backend_service.serialization import serialize_monitored_frame
from scenegems_tool.waraps_integration.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.waraps_integration.sim_utils import Geofence


@dataclass(frozen=True)
class MqttMonitoringTask:
    sender: str
    task_uuid: str
    scenario_id: str
    scene: ConcreteScene
    scene_timestamp: int
    time_step: int
    is_simulation_frame: bool

    @property
    def trajectory_id(self) -> str:
        return f"{self.sender}-{self.scenario_id}-{str(self.is_simulation_frame)}"


@dataclass(frozen=True)
class MqttMonitoringBatchTask:
    sender: str
    task_uuid: str
    scenario_id: str
    scenes: Sequence[ConcreteScene]
    scene_timestamps: Sequence[int]
    time_step: int
    is_simulation_frame: bool

    @property
    def trajectory_id(self) -> str:
        return f"{self.sender}-{self.scenario_id}-{str(self.is_simulation_frame)}"


class MqttMonitorService(MqttClient):
    def __init__(self, mqtt_connection: MQttConnectionInfo, topic: str, agent_name: str, reference_geofence: Geofence):
        super().__init__(name=agent_name, topic=topic, mqtt_connection=mqtt_connection, reference_geofence=reference_geofence)
        self.info_update_rate = 1.0
        self.monitoring_task_queue: Queue[Union[MqttMonitoringTask, MqttMonitoringBatchTask]] = Queue()
        self._ready_event = threading.Event()

    @property
    def listen_topics(self) -> List[str]:
        return [self.exec_command_topic]

    @property
    def base_topic(self) -> str:
        return self.topic

    @property
    def monitored_scene_topic(self) -> str:
        return f"{self.sensor_topic}/monitored-scene"

    @property
    def is_ready(self) -> bool:
        # Ready means we are connected and on_connect has run, which performs topic subscriptions.
        return self._ready_event.is_set() and self.is_connected

    def on_connect(self, client, userdata, flags, rc):
        super().on_connect(client, userdata, flags, rc)
        if rc == 0:
            self._ready_event.set()

    def on_disconnect(self, client, userdata, rc):
        self._ready_event.clear()
        super().on_disconnect(client, userdata, rc)

    def _on_message(self, msg: mqtt.MQTTMessage, payload: Any):
        if payload["execution-unit"] != self.name:
            return
        if payload["command"] != "start-task":
            return
        match payload["task"]["name"]:
            case "step-monitor":
                self._on_step_monitor_task(payload)
            case "step-monitor-batch":
                self._on_step_monitor_batch_task(payload)

    def _on_step_monitor_task(self, payload: Any):
        scenario_id = payload["task"]["params"]["scenario-id"]
        scene = ConcreteScene.from_dict(payload["task"]["params"]["scene"])
        scene_timestamp = payload["task"]["params"]["scene-timestamp"]
        time_Step = payload["task"]["params"]["time-step"]
        is_simulation_frame = bool(payload["task"]["params"]["is-simulation-frame"])
        self.monitoring_task_queue.put(
            MqttMonitoringTask(
                sender=self.name,
                task_uuid=payload["task-uuid"],
                scenario_id=scenario_id,
                scene=scene,
                scene_timestamp=scene_timestamp,
                time_step=time_Step,
                is_simulation_frame=is_simulation_frame,
            )
        )

    def _on_step_monitor_batch_task(self, payload: Any) -> None:
        params = payload["task"]["params"]
        scenes = [ConcreteScene.from_dict(scene_dict) for scene_dict in params["scenes"]]
        self.monitoring_task_queue.put(
            MqttMonitoringBatchTask(
                sender=self.name,
                task_uuid=payload["task-uuid"],
                scenario_id=params["scenario-id"],
                scenes=scenes,
                scene_timestamps=params["scene-timestamps"],
                time_step=params["time-step"],
                is_simulation_frame=bool(params["is-simulation-frame"]),
            )
        )

    def publish_monitored_scene(self, task: MqttMonitoringTask, monitored_scene: MonitoredSceneWithResults):
        monitored_scene_command = {
            "stamp": time.time(),
            "task_sender": task.sender,
            "task-uuid": task.task_uuid,
            "monitored-frame": serialize_monitored_frame(scenario_id=task.scenario_id, monitored_scene=monitored_scene, timestamp=task.scene_timestamp, time_step=task.time_step),
            "is-simulation-frame": task.is_simulation_frame,
        }
        str_monitored_scene_command = json.dumps(monitored_scene_command)
        self.client.publish(self.monitored_scene_topic, str_monitored_scene_command, qos=1)

    def publish_monitored_scene_batch(
        self,
        batch_task: MqttMonitoringBatchTask,
        monitored_results: Sequence[tuple[MqttMonitoringTask, MonitoredSceneWithResults]],
    ) -> None:
        monitored_frames = [
            serialize_monitored_frame(
                scenario_id=task.scenario_id,
                monitored_scene=monitored_scene,
                timestamp=task.scene_timestamp,
                time_step=task.time_step,
            )
            for task, monitored_scene in monitored_results
        ]
        if not monitored_frames:
            return
        monitored_scene_command = {
            "stamp": time.time(),
            "task_sender": batch_task.sender,
            "task-uuid": batch_task.task_uuid,
            "monitored-frames": monitored_frames,
            "is-simulation-frame": batch_task.is_simulation_frame,
        }
        self.client.publish(self.monitored_scene_topic, json.dumps(monitored_scene_command), qos=1)

    def publish_heartbeat_and_sensor_info(self, current_tasks: List[MqttMonitoringTask]):
        heartbeat_command = {
            "name": self.name,
            "agent-type": "virtual",
            "agent-description": "COLREGS Monitor",
            "agent-uuid": self.uuid,
            "levels": ["sensor", "direct execution"],
            "rate": self.info_update_rate,
            "stamp": time.time(),
            "type": "HeartBeat",
        }
        str_heartbeat_command = json.dumps(heartbeat_command)
        self.client.publish(self.heartbeat_topic, str_heartbeat_command, qos=1)
        sensor_info_command = {"name": self.name, "rate": self.info_update_rate, "sensor-data-provided": ["monitored-scene"], "stamp": time.time(), "type": "SensorInfo"}

        str_sensor_info_command = json.dumps(sensor_info_command)
        self.client.publish(self.sensor_info_topic, str_sensor_info_command, qos=1)

        tasks_executing = [{"name": "step-monitor", "uuid": current_task.task_uuid} for current_task in current_tasks]
        direct_execution_info_command = {
            "name": self.name,
            "rate": self.info_update_rate,
            "type": "DirectExecutionInfo",
            "stamp": time.time(),
            "tasks-available": [{"name": "step-monitor", "signals": []}],
            "tasks-executing": tasks_executing,
        }

        str_direct_execution_info_command = json.dumps(direct_execution_info_command)
        self.client.publish(self.direct_execution_topic, str_direct_execution_info_command, qos=1)
