"""The requester's side of a subsystem on the broker: send a request or a signal, hear the tasks' states, progress and streams.

The worker node daemon uses one client per job (cluster/worker_node/jobs/pool_client.py). The client
listens below the subsystem's base topic (messaging/mqtt_pool_service.py) and hands on only what that
subsystem sent; whoever uses it picks its own request by the request id every message carries.
"""

import json
import time
import traceback
import uuid
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import paho.mqtt.client as mqtt

from scenegems_tool.messaging.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.subsystems.pool.pool_task import TaskState
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

# (request id, state, why it failed, the task's seed)
StateHandler = Callable[[str, TaskState, Optional[str], Optional[int]], None]
# (stream, the message as the subsystem published it)
StreamHandler = Callable[[str, Mapping[str, Any]], None]
# (request id, the feedback message)
FeedbackHandler = Callable[[str, Mapping[str, Any]], None]

HEARTBEAT_VALID_S = 5.0  # a subsystem heartbeats once a second; older than this and it counts as gone


class MqttPoolClient(MqttClient):
    def __init__(
        self,
        mqtt_connection: MQttConnectionInfo,
        topic: str,
        reference_geofence: Geofence,
        service_name: str,
        *,
        streams: Sequence[str] = (),
        on_state: Optional[StateHandler] = None,
        on_stream: Optional[StreamHandler] = None,
        on_feedback: Optional[FeedbackHandler] = None,
        name: str = "pool_client",
        clock: Callable[[], float] = time.time,
    ):
        super().__init__(name=name, topic=topic, mqtt_connection=mqtt_connection, reference_geofence=reference_geofence)
        self.service_name = service_name
        self.streams = tuple(streams)
        self.on_state = on_state
        self.on_stream = on_stream
        self.on_feedback = on_feedback
        self._clock = clock
        self.last_heartbeat_timestamp: Optional[float] = None

    def stream_topic(self, stream: str) -> str:
        return f"{self.sensor_topic}/{stream}"

    @property
    def listen_topics(self) -> List[str]:
        return [self.exec_response_topic, self.exec_feedback_topic, self.heartbeat_topic, *(self.stream_topic(stream) for stream in self.streams)]

    @property
    def is_heartbeat_valid(self) -> bool:
        return self.last_heartbeat_timestamp is not None and self._clock() - self.last_heartbeat_timestamp < HEARTBEAT_VALID_S

    def on_message(self, client, userdata, msg: mqtt.MQTTMessage) -> None:
        """Every message goes to _on_message; the base class's own bookkeeping of responses is not used here."""
        try:
            self._on_message(msg, self._parse_message(msg))
        except Exception:
            print(traceback.format_exc())

    def _on_message(self, msg: mqtt.MQTTMessage, payload: Any) -> None:
        if msg.topic == self.heartbeat_topic:
            self.last_heartbeat_timestamp = self._clock()
            return
        if not isinstance(payload, dict) or payload.get("task_sender") != self.service_name:
            return
        request_id = str(payload.get("request-id", ""))
        if msg.topic == self.exec_response_topic:
            self._on_response(request_id, payload)
        elif msg.topic == self.exec_feedback_topic:
            if self.on_feedback is not None:
                self.on_feedback(request_id, payload)
        elif self.on_stream is not None:
            for stream in self.streams:
                if msg.topic == self.stream_topic(stream):
                    self.on_stream(stream, payload)
                    return

    def _on_response(self, request_id: str, payload: Mapping[str, Any]) -> None:
        try:
            state = TaskState(payload.get("response"))
        except ValueError:
            return  # a response of another vocabulary
        if self.on_state is not None:
            seed = payload.get("seed")
            self.on_state(request_id, state, payload.get("fail-reason"), None if seed is None else int(seed))

    def publish_start_task(self, task_name: str, request_id: str, params: Mapping[str, Any], seed: int) -> str:
        """Send a request: its inputs with the request id and the seed in the task's params. Returns the task-uuid it was given."""
        task_uuid = str(uuid.uuid4())
        command = {
            **self._command("start-task", task_uuid),
            "task": {"name": task_name, "params": {**params, "request-id": request_id, "seed": int(seed)}},
        }
        self.client.publish(self.exec_command_topic, json.dumps(command), qos=1)
        return task_uuid

    def publish_signal(self, signal_name: str, request_id: str, data: Any = None) -> Optional[mqtt.MQTTMessageInfo]:
        """Send a signal to the tasks of a request; the returned info confirms the publish."""
        signal: Dict[str, Any] = {"name": signal_name, "request-id": request_id}
        if data is not None:
            signal["data"] = data
        command = {**self._command("signal-task", str(uuid.uuid4())), "signal": signal}
        return self.client.publish(self.exec_command_topic, json.dumps(command), qos=1)

    def publish_cancel(self, request_id: str) -> Optional[mqtt.MQTTMessageInfo]:
        """Ask the subsystem to stop the tasks of this request only."""
        return self.publish_signal("cancel", request_id)

    def _command(self, command: str, task_uuid: str) -> Dict[str, Any]:
        return {"stamp": time.time(), "task_sender": self.name, "task-uuid": task_uuid, "command": command, "execution-unit": self.service_name}
