import json
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import paho.mqtt.client as mqtt

from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.backend_service.protocol import SimulationStatus
from scenegems_tool.waraps_integration.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.waraps_integration.sim_utils import Geofence


class MqttScenarioExecutionClient(MqttClient):
    def __init__(
        self,
        mqtt_connection: MQttConnectionInfo,
        topic: str,
        reference_geofence: Geofence,
        parent_service_name: str,
        on_simulation_state: Callable[[Dict[str, Any]], None],
    ):
        super().__init__(name="scenario_execution_client", topic=topic, mqtt_connection=mqtt_connection, reference_geofence=reference_geofence)
        self.parent_service_name = parent_service_name
        self.on_simulation_state = on_simulation_state
        self.last_heartbeat_timestamp = 0.0
        self.timeout_sec = 10.0
        self.heartbeat_interval_sec = 5.0
        self.latest_simulation_state: Dict[str, Any] = {"status": SimulationStatus.INITIALIZING.value, "clock": 0.0, "scene": None}

    @property
    def listen_topics(self) -> List[str]:
        return [
            self.simulation_state_topic,
            self.heartbeat_topic,
        ]

    @property
    def simulation_state_topic(self) -> str:
        return f"{self.sensor_topic}/simulation-state"

    @property
    def latest_status(self) -> SimulationStatus:
        try:
            return SimulationStatus(self.latest_simulation_state.get("status", SimulationStatus.INITIALIZING.value))
        except ValueError:
            return SimulationStatus.INITIALIZING

    @property
    def latest_clock(self) -> float:
        return float(self.latest_simulation_state.get("clock", 0.0))

    @property
    def latest_scene(self) -> Optional[ConcreteScene]:
        scene_dict = self.latest_simulation_state.get("scene")
        if not scene_dict:
            return None
        return ConcreteScene.from_dict(scene_dict)

    @property
    def is_service_ready(self) -> bool:
        return self.is_connected and self.is_heartbeat_valid

    @property
    def is_heartbeat_valid(self) -> bool:
        return time.time() - self.last_heartbeat_timestamp < self.heartbeat_interval_sec

    def _on_message(self, msg: mqtt.MQTTMessage, payload: Any):
        match msg.topic:
            case self.simulation_state_topic:
                if payload.get("task_sender") != self.parent_service_name:
                    return
                self.latest_simulation_state = payload
                self.on_simulation_state(payload)
            case self.heartbeat_topic:
                self.last_heartbeat_timestamp = time.time()

    def wait_for_heartbeat(self) -> None:
        start_time = time.time()
        while not self.is_heartbeat_valid or not self.is_connected:
            time.sleep(0.1)
            if time.time() - start_time > self.timeout_sec:
                raise ValueError("Timeout: Failed to connect to scenario execution service")

    def publish_start_simulation_command(self) -> None:
        self.wait_for_heartbeat()
        command = {
            "stamp": time.time(),
            "task_sender": self.name,
            "task-uuid": str(uuid.uuid4()),
            "command": "start-task",
            "execution-unit": self.parent_service_name,
            "task": {"name": "start-simulation", "params": {}},
        }
        self.client.publish(self.exec_command_topic, json.dumps(command), qos=1)
