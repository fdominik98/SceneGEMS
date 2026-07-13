import json
import time
import uuid
from typing import Any, Callable, List

import paho.mqtt.client as mqtt

from scenegems_tool.backend_service.protocol import ServerMessage, make_generated_scene_message
from scenegems_tool.waraps_integration.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.waraps_integration.sim_utils import Geofence


class MqttScenarioGenerationClient(MqttClient):
    def __init__(
        self,
        mqtt_connection: MQttConnectionInfo,
        topic: str,
        reference_geofence: Geofence,
        parent_service_name: str,
        send_payload: Callable[[ServerMessage], None],
    ):
        super().__init__(name="scenario_generation_client", topic=topic, mqtt_connection=mqtt_connection, reference_geofence=reference_geofence)
        self.parent_service_name = parent_service_name
        self.send_payload = send_payload
        self.last_heartbeat_timestamp = 0.0
        self.timeout_sec = 10.0
        self.heartbeat_interval_sec = 5.0

    @property
    def listen_topics(self) -> List[str]:
        return [
            self.generated_scene_topic,
            self.exec_feedback_topic,
            self.exec_response_topic,
            self.heartbeat_topic,
        ]

    def _on_message(self, msg: mqtt.MQTTMessage, payload: Any):
        match msg.topic:
            case self.generated_scene_topic:
                if payload["task_sender"] != self.parent_service_name:
                    return
                self.send_payload(
                    make_generated_scene_message(
                        request_id=payload["request-id"],
                        scene=payload["generated-frame"],
                        evaluation_data=payload["evaluation-data"],
                        valid=payload["valid"],
                    )
                )
            case self.heartbeat_topic:
                self.last_heartbeat_timestamp = time.time()

    @property
    def is_heartbeat_valid(self) -> bool:
        return time.time() - self.last_heartbeat_timestamp < self.heartbeat_interval_sec

    def wait_for_heartbeat(self) -> None:
        start_time = time.time()
        while not self.is_heartbeat_valid or not self.is_connected:
            time.sleep(0.1)
            if time.time() - start_time > self.timeout_sec:
                raise ValueError("Timeout: Failed to connect to scenario generation service")

    def publish_generate_scene_command(
        self,
        request_id: str,
        functional_scenario_content: str,
        colregs_constraints_content: str,
        vessel_types_content: str,
        obstacle_types_content: str,
        timeout: int,
    ):
        self.wait_for_heartbeat()

        generate_scene_command = {
            "stamp": time.time(),
            "task_sender": self.name,
            "task-uuid": str(uuid.uuid4()),
            "command": "start-task",
            "execution-unit": self.parent_service_name,
            "task": {
                "name": "generate-scene",
                "params": {
                    "request-id": request_id,
                    "functional-scenario-content": functional_scenario_content,
                    "colregs-constraints-content": colregs_constraints_content,
                    "vessel-types-content": vessel_types_content,
                    "obstacle-types-content": obstacle_types_content,
                    "timeout": timeout,
                },
            },
        }
        str_generated_scene_command = json.dumps(generate_scene_command)
        self.client.publish(self.exec_command_topic, str_generated_scene_command, qos=1)
