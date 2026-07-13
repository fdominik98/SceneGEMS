import json
import time
import uuid
from typing import Any, Callable, List, Sequence

import paho.mqtt.client as mqtt

from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.backend_service.protocol import ServerMessage, make_preview_chunk_message, make_simulation_chunk_message
from scenegems_tool.waraps_integration.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.waraps_integration.sim_utils import Geofence


class MqttMonitorClient(MqttClient):
    def __init__(self, mqtt_connection: MQttConnectionInfo, topic: str, agent_name: str, reference_geofence: Geofence, parent_service_name: str, send_payload: Callable[[ServerMessage], None]):
        super().__init__(name=agent_name, topic=topic, mqtt_connection=mqtt_connection, reference_geofence=reference_geofence)
        self.parent_service_name = parent_service_name
        self.send_payload = send_payload
        self.last_heartbeat_timestamp = 0.0
        self.timeout_sec = 10.0
        self.heartbeat_interval_sec = 5.0
        
    @property
    def listen_topics(self) -> List[str]:
        return [self.monitored_scene_topic, self.heartbeat_topic]

    @property
    def monitored_scene_topic(self) -> str:
        return f"{self.sensor_topic}/monitored-scene"

    def _on_message(self, msg: mqtt.MQTTMessage, payload: Any):
        match msg.topic:
            case self.monitored_scene_topic:
                if payload["task_sender"] != self.name:
                    return
                is_simulation_frame = payload["is-simulation-frame"]
                is_multi_frame = "monitored-frames" in payload
                frames = payload["monitored-frames"] if is_multi_frame else [payload["monitored-frame"]]
                if not frames:
                    return
                scenario_id = frames[0]["scenarioId"]
                from_timestamp = frames[0]["timestamp"]
                to_timestamp = frames[-1]["timestamp"]
                if is_simulation_frame:
                    self.send_payload(make_simulation_chunk_message(scenario_id=scenario_id, from_timestamp=from_timestamp, to_timestamp=to_timestamp, frames=frames))
                else:
                    self.send_payload(make_preview_chunk_message(scenario_id=scenario_id, from_timestamp=from_timestamp, to_timestamp=to_timestamp, frames=frames))
            case self.heartbeat_topic:
                self.last_heartbeat_timestamp = time.time()
                
    def wait_for_heartbeat(self) -> None:
        start_time = time.time()
        while not self.is_heartbeat_valid or not self.is_connected:
            time.sleep(0.1)
            if time.time() - start_time > self.timeout_sec:
                raise ValueError("Timeout: Failed to connect to monitor service")
      
    @property      
    def is_heartbeat_valid(self) -> bool:
        return time.time() - self.last_heartbeat_timestamp < self.heartbeat_interval_sec

    def publish_step_monitor_command(self, scenario_id: str, scene: ConcreteScene, timestamp: int, time_step: int, is_simulation_frame: bool):
        self.wait_for_heartbeat()
            
        step_monitor_command = {
            "stamp": time.time(),
            "task_sender": self.parent_service_name,
            "task-uuid": str(uuid.uuid4()),
            "command": "start-task",
            "execution-unit": self.name,
            "task": {
                "name": "step-monitor",
                "params": {"scenario-id": scenario_id, "scene": scene.to_dict(), "scene-timestamp": timestamp, "time-step": time_step, "is-simulation-frame": bool(is_simulation_frame)},
            },
        }
        str_step_monitor_command = json.dumps(step_monitor_command)
        self.client.publish(self.exec_command_topic, str_step_monitor_command, qos=1)

    def publish_step_monitor_batch_command(
        self,
        scenario_id: str,
        scenes: Sequence[ConcreteScene],
        timestamps: Sequence[int],
        time_step: int,
        is_simulation_frame: bool,
    ) -> None:
        self.wait_for_heartbeat()
        
        step_monitor_batch_command = {
            "stamp": time.time(),
            "task_sender": self.parent_service_name,
            "task-uuid": str(uuid.uuid4()),
            "command": "start-task",
            "execution-unit": self.name,
            "task": {
                "name": "step-monitor-batch",
                "params": {
                    "scenario-id": scenario_id,
                    "scenes": [scene.to_dict() for scene in scenes],
                    "scene-timestamps": list(timestamps),
                    "time-step": time_step,
                    "is-simulation-frame": bool(is_simulation_frame),
                },
            },
        }
        self.client.publish(self.exec_command_topic, json.dumps(step_monitor_batch_command), qos=1)
