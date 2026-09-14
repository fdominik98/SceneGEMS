import copy
import json
import time
import uuid
from typing import Any, Callable, Dict, List

import paho.mqtt.client as mqtt

from concrete_level.models.concrete_scene import ConcreteScene
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from scenegems_tool.backend_service.protocol import ServerMessage, make_generated_scene_message
from scenegems_tool.waraps_integration.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.waraps_integration.sim_utils import Geofence

# (request_id, scene, evaluation_data, valid)
GeneratedSceneHandler = Callable[[str, ConcreteScene, Dict[str, Any], bool], None]


class MqttScenarioGenerationClient(MqttClient):
    def __init__(
        self,
        mqtt_connection: MQttConnectionInfo,
        topic: str,
        reference_geofence: Geofence,
        parent_service_name: str,
        send_payload: Callable[[ServerMessage], None],
        on_generated_scene: GeneratedSceneHandler,
    ):
        super().__init__(name="scenario_generation_client", topic=topic, mqtt_connection=mqtt_connection, reference_geofence=reference_geofence)
        self.parent_service_name = parent_service_name
        self.send_payload = send_payload
        self.on_generated_scene = on_generated_scene
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
                self._on_generated_scene_payload(payload)
            case self.heartbeat_topic:
                self.last_heartbeat_timestamp = time.time()

    def _on_generated_scene_payload(self, payload: Any) -> None:
        """Hand the generated scene to the monitor, which sends it to the frontend.

        Falls back to forwarding the unmonitored frame when the scene cannot be rebuilt,
        so a scene generation request never waits on a scene that was dropped.
        """
        request_id = payload["request-id"]
        evaluation_data = payload["evaluation-data"]
        valid = bool(payload["valid"])
        try:
            scene = EvaluationData.from_dict(copy.deepcopy(evaluation_data)).best_scene
        except Exception as exc:
            print(f"Could not rebuild generated scene {request_id} for monitoring: {exc}")
            self.send_payload(make_generated_scene_message(request_id=request_id, scene=payload["generated-frame"], evaluation_data=evaluation_data, valid=valid))
            return
        self.on_generated_scene(request_id, scene, evaluation_data, valid)

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
