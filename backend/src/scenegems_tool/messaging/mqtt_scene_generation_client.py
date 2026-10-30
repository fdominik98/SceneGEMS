import copy
import json
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import paho.mqtt.client as mqtt

from concrete_level.models.concrete_scene import ConcreteScene
from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from scenegems_tool.gateway.protocol import ServerMessage, make_generated_scene_message
from scenegems_tool.messaging.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

# (request_id, scene, evaluation_data, valid)
GeneratedSceneHandler = Callable[[str, ConcreteScene, Dict[str, Any], bool], None]
# (request_id, evaluation_data, valid, final): every generated scene as the service sent it.
# A worker streams its samples while it searches; only its last one is final.
SceneResultHandler = Callable[[str, Dict[str, Any], bool, bool], None]


class MqttSceneGenerationClient(MqttClient):
    def __init__(
        self,
        mqtt_connection: MQttConnectionInfo,
        topic: str,
        reference_geofence: Geofence,
        parent_service_name: str,
        send_payload: Callable[[ServerMessage], None],
        on_generated_scene: GeneratedSceneHandler,
        on_scene_result: Optional[SceneResultHandler] = None,
    ):
        super().__init__(name="scene_generation_client", topic=topic, mqtt_connection=mqtt_connection, reference_geofence=reference_geofence)
        self.parent_service_name = parent_service_name
        self.send_payload = send_payload
        self.on_generated_scene = on_generated_scene
        self.on_scene_result = on_scene_result  # when set, it gets every scene instead of the monitor path (cluster jobs)
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
                if self.on_scene_result is not None:
                    # A service from before the final flag sends one scene per task.
                    self.on_scene_result(payload["request-id"], payload["evaluation-data"], bool(payload["valid"]), bool(payload.get("final", True)))
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
                raise ValueError("Timeout: Failed to connect to scene generation service")

    def publish_generate_scene_command(
        self,
        request_id: str,
        functional_scenario_content: str,
        colregs_constraints_content: str,
        vessel_types_content: str,
        obstacle_types_content: str,
        timeout: int,
        enforce_low_tcpa: bool = False,
        seed: Optional[int] = None,
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
                    "enforce-low-tcpa": bool(enforce_low_tcpa),
                    **({"seed": int(seed)} if seed is not None else {}),
                },
            },
        }
        str_generated_scene_command = json.dumps(generate_scene_command)
        self.client.publish(self.exec_command_topic, str_generated_scene_command, qos=1)

    def publish_cancel_command(self, request_id: str) -> Optional[mqtt.MQTTMessageInfo]:
        """Ask the pool to stop the generation of this request only; the returned info confirms the publish."""
        command = {
            "stamp": time.time(),
            "task_sender": self.name,
            "task-uuid": str(uuid.uuid4()),
            "command": "signal-task",
            "execution-unit": self.parent_service_name,
            "signal": {"name": "cancel", "request-id": request_id},
        }
        return self.client.publish(self.exec_command_topic, json.dumps(command), qos=1)
