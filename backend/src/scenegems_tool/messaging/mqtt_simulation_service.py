import json
import threading
import time
from dataclasses import dataclass
from queue import Queue
from typing import Any, Dict, List, Optional

import paho.mqtt.client as mqtt

from scenegems_tool.gateway.protocol import SimulationStatus
from scenegems_tool.messaging.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

SIMULATION_SERVICE_NAME = "simulation_service"
SIMULATION_SERVICE_TOPIC = f"waraps/service/virtual/real/{SIMULATION_SERVICE_NAME}"


@dataclass(frozen=True)
class MqttStartSimulationTask:
    sender: str
    task_uuid: str


class MqttSimulationService(MqttClient):
    def __init__(self, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence):
        self.info_update_rate = 1.0
        super().__init__(SIMULATION_SERVICE_NAME, SIMULATION_SERVICE_TOPIC, mqtt_connection, reference_geofence)
        self.task_queue: Queue[MqttStartSimulationTask] = Queue()
        self._ready_event = threading.Event()
        self._current_tasks: List[MqttStartSimulationTask] = []
        self._current_tasks_lock = threading.Lock()

    @property
    def listen_topics(self) -> List[str]:
        return [self.exec_command_topic]

    @property
    def simulation_state_topic(self) -> str:
        return f"{self.sensor_topic}/simulation-state"

    @property
    def is_ready(self) -> bool:
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
        if payload["task"]["name"] != "start-simulation":
            return
        self.task_queue.put(
            MqttStartSimulationTask(
                sender=payload["task_sender"],
                task_uuid=payload["task-uuid"],
            )
        )

    def publish_simulation_state(
        self,
        status: SimulationStatus,
        clock: float,
        scene: Optional[Dict[str, Any]] = None,
    ) -> None:
        simulation_state_command = {
            "stamp": time.time(),
            "task_sender": self.name,
            "status": status.value,
            "clock": clock,
            "scene": scene,
        }
        self.client.publish(self.simulation_state_topic, json.dumps(simulation_state_command), qos=1)

    def publish_heartbeat_and_sensor_info(self) -> None:
        heartbeat_command = {
            "name": self.name,
            "agent-type": "virtual",
            "agent-description": "Simulation Subsystem",
            "agent-uuid": self.uuid,
            "levels": ["sensor", "direct execution"],
            "rate": self.info_update_rate,
            "stamp": time.time(),
            "type": "HeartBeat",
        }
        self.client.publish(self.heartbeat_topic, json.dumps(heartbeat_command), qos=1)
        sensor_info_command = {
            "name": self.name,
            "rate": self.info_update_rate,
            "sensor-data-provided": ["simulation-state"],
            "stamp": time.time(),
            "type": "SensorInfo",
        }
        self.client.publish(self.sensor_info_topic, json.dumps(sensor_info_command), qos=1)
        with self._current_tasks_lock:
            current_tasks = list(self._current_tasks)
        tasks_executing = [{"name": "start-simulation", "uuid": task.task_uuid} for task in current_tasks]
        direct_execution_info_command = {
            "name": self.name,
            "rate": self.info_update_rate,
            "type": "DirectExecutionInfo",
            "stamp": time.time(),
            "tasks-available": [{"name": "start-simulation", "signals": []}],
            "tasks-executing": tasks_executing,
        }
        self.client.publish(self.direct_execution_topic, json.dumps(direct_execution_info_command), qos=1)

    def track_task(self, task: MqttStartSimulationTask) -> None:
        with self._current_tasks_lock:
            self._current_tasks.append(task)

    def untrack_task(self, task: MqttStartSimulationTask) -> None:
        with self._current_tasks_lock:
            if task in self._current_tasks:
                self._current_tasks.remove(task)
