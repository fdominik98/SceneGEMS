import json
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Sequence, Tuple

import paho.mqtt.client as mqtt

from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.backend_service.protocol import ServerMessage, make_generated_scene_message, make_preview_chunk_message, make_simulation_chunk_message
from scenegems_tool.waraps_integration.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.waraps_integration.sim_utils import Geofence

# Every generated scene is monitored under this one scenario id, so the monitor keeps a
# single runtime for them (it resets on each timestamp-0 scene) instead of one per request.
GENERATED_SCENE_SCENARIO_ID = "generated-scene"


class MqttMonitorClient(MqttClient):
    def __init__(self, mqtt_connection: MQttConnectionInfo, topic: str, agent_name: str, reference_geofence: Geofence, parent_service_name: str, send_payload: Callable[[ServerMessage], None]):
        super().__init__(name=agent_name, topic=topic, mqtt_connection=mqtt_connection, reference_geofence=reference_geofence)
        self.parent_service_name = parent_service_name
        self.send_payload = send_payload
        self.last_heartbeat_timestamp = 0.0
        self.timeout_sec = 10.0
        self.heartbeat_interval_sec = 5.0
        # request id to (evaluation data, valid), held until the monitored frame returns.
        self._pending_generated_scenes: Dict[str, Tuple[Dict[str, Any], bool]] = {}
        self._pending_lock = threading.Lock()

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
                request_id = payload.get("request-id")
                if request_id is not None:
                    self._send_monitored_generated_scene(request_id, frames[0])
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

    def _send_monitored_generated_scene(self, request_id: str, frame: Dict[str, Any]) -> None:
        with self._pending_lock:
            pending = self._pending_generated_scenes.pop(request_id, None)
        if pending is None:
            return
        evaluation_data, valid = pending
        # The monitor ran it under the shared scenario id; the frontend keys scenes by request id.
        frame["scenarioId"] = request_id
        self.send_payload(make_generated_scene_message(request_id=request_id, scene=frame, evaluation_data=evaluation_data, valid=valid))

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

    def publish_monitor_generated_scene_command(self, request_id: str, scene: ConcreteScene, evaluation_data: Dict[str, Any], valid: bool) -> None:
        """Monitor one scene as the initial scene of a trajectory.

        The monitor echoes `request-id` back, which routes the result to a
        `generated_scene` message instead of a preview chunk.
        """
        self.wait_for_heartbeat()
        with self._pending_lock:
            self._pending_generated_scenes[request_id] = (evaluation_data, valid)

        monitor_generated_scene_command = {
            "stamp": time.time(),
            "task_sender": self.parent_service_name,
            "task-uuid": str(uuid.uuid4()),
            "command": "start-task",
            "execution-unit": self.name,
            "task": {
                "name": "step-monitor-batch",
                "params": {
                    "scenario-id": GENERATED_SCENE_SCENARIO_ID,
                    "scenes": [scene.to_dict()],
                    "scene-timestamps": [0],
                    "time-step": 1,
                    "is-simulation-frame": False,
                    "request-id": request_id,
                },
            },
        }
        self.client.publish(self.exec_command_topic, json.dumps(monitor_generated_scene_command), qos=1)
