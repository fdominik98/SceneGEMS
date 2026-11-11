"""A subsystem on the broker: it takes requests, runs them as tasks in its pool and publishes what the tasks produce.

Every subsystem is one PoolService. Below its base topic (<root>/service/virtual/real/<name>) it

    listens on  exec/command       start-task with its task name: a request, with its inputs and its seed in task.params
                                   signal-task: cancel, or one of the subsystem's own signals, for the tasks of a request
    publishes   exec/response      every state a task goes through (pool_task.TaskState), with the reason of a failure
                exec/feedback      progress of a running task
                sensor/<stream>    the tasks' messages: previews and results, in the subsystem's own form
                heartbeat, sensor/sensor_info, direct_execution    once a second: alive, and what it runs and what waits

A subclass names its task, its streams and its worker, turns a request into tasks (make_tasks) and
gives a stream message its form (stream_message). The queue and the pool are subsystems/pool/task_pool.py.
A subsystem with more than one kind of request names them all (task_names) and is told which one a
request is (make_tasks_of); its one pool runs the tasks of all of them, and its worker tells them apart.

A request that names no seed gets one drawn here, so every task has a seed and every response says
which. A request the subsystem cannot run is answered as failed, with the reason, and never queued.
"""

import json
import logging
import time
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import paho.mqtt.client as mqtt

from scenegems_tool.messaging.mqtt_client import MqttClient, MQttConnectionInfo, service_topic
from scenegems_tool.subsystems.pool.pool_task import OUTPUT_FEEDBACK, PoolTask, TaskOutput, TaskState, draw_seed
from scenegems_tool.subsystems.pool.task_pool import TaskPool
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

_logger = logging.getLogger(__name__)
CANCEL_SIGNAL = "cancel"


class PoolService(MqttClient):
    description = "Subsystem"  # the agent description in the heartbeat
    task_name = ""  # the start-task name of the subsystem's request
    task_names: Tuple[str, ...] = ()  # every start-task name, for a subsystem with more than one kind of request; (task_name,) unless given
    signals: Tuple[str, ...] = ()  # the signals its tasks take besides cancel
    streams: Tuple[str, ...] = ()  # the sensor/<stream> topics its tasks publish on
    worker: Callable[[PoolTask, Any], None]  # runs one task in a process of its own; a module-level function

    def __init__(self, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence, max_workers: int, name: str, *, pool_factory: Callable[..., TaskPool] = TaskPool):
        self.info_update_rate = 1.0
        self.max_workers = max_workers
        # The name tells this instance from every other on the broker; the connection knows the broker's first topic level
        super().__init__(name, service_topic(mqtt_connection.topic_root, name), mqtt_connection, reference_geofence)
        self.pool = pool_factory(type(self).worker, max_workers, self._on_state, self._on_output)

    # What a subclass says

    def make_tasks(self, task_uuid: str, request_id: str, seed: int, params: Mapping[str, Any]) -> List[PoolTask]:
        """The tasks of a request; KeyError, TypeError or ValueError for a request the subsystem cannot run."""
        raise NotImplementedError

    def make_tasks_of(self, name: str, task_uuid: str, request_id: str, seed: int, params: Mapping[str, Any]) -> List[PoolTask]:
        """The tasks of a request with this start-task name; make_tasks unless the subsystem has more than one kind of request."""
        return self.make_tasks(task_uuid, request_id, seed, params)

    def task_name_of(self, task: PoolTask) -> str:
        """The start-task name a task came from, as the heartbeat lists it."""
        return self.task_name

    @property
    def requests(self) -> Tuple[str, ...]:
        """Every start-task name the subsystem takes."""
        return self.task_names or (self.task_name,)

    def stream_message(self, task: PoolTask, stream: str, payload: Any, final: bool) -> Dict[str, Any]:
        """The fields of a stream message besides the task's identity, which every message carries."""
        return {"payload": payload, "final": bool(final)}

    # The runtime of the container

    def start_runtime(self) -> None:
        self.pool.start()

    def stop_runtime(self) -> None:
        self.pool.stop()

    @property
    def listen_topics(self) -> List[str]:
        return [self.exec_command_topic]

    @property
    def current_tasks(self) -> List[PoolTask]:
        """The tasks the pool holds, queued and running, in arrival order."""
        return self.pool.tasks()

    # Intake

    def _on_message(self, msg: mqtt.MQTTMessage, payload: Any) -> None:
        if not isinstance(payload, dict) or payload.get("execution-unit") != self.name:
            return
        command = payload.get("command")
        if command == "start-task" and (payload.get("task") or {}).get("name") in self.requests:
            self._take_request(payload)
        elif command == "signal-task":
            self._take_signal(payload.get("signal") or {})

    def _take_request(self, payload: Mapping[str, Any]) -> None:
        task_uuid = str(payload.get("task-uuid", ""))
        params = payload["task"].get("params") or {}
        request_id = str(params.get("request-id") or "")
        try:
            if not task_uuid or not request_id:
                raise ValueError("a request names its task-uuid and, in its params, its request-id")
            seed = draw_seed() if params.get("seed") is None else int(params["seed"])
            tasks = self.make_tasks_of(payload["task"]["name"], task_uuid, request_id, seed, params)
        except (KeyError, TypeError, ValueError) as error:
            reason = f"missing {error}" if isinstance(error, KeyError) else str(error)
            _logger.warning("Refused request %s: %s", request_id or task_uuid, reason)
            self.publish_response(task_uuid, request_id, TaskState.FAILED, f"the request was refused: {reason}")
            return
        for task in tasks:
            self._on_state(task, TaskState.RECEIVED, None)
            self.pool.submit(task)

    def _take_signal(self, signal: Mapping[str, Any]) -> None:
        name, request_id = signal.get("name"), signal.get("request-id")
        if not request_id:
            _logger.warning("Ignored a signal that names no request")
            return
        if name == CANCEL_SIGNAL:
            if self.pool.cancel_request(request_id) == 0:
                _logger.info("Cancel for request %s, which this pool does not hold", request_id)
        elif name in self.signals:
            if self.pool.signal(request_id, name, signal.get("data")) == 0:
                _logger.info("Signal %s for request %s, which this pool does not hold", name, request_id)
        else:
            _logger.warning("Ignored the unknown signal %r for request %s", name, request_id)

    # What the pool reports, from its own thread

    def _on_state(self, task: PoolTask, state: TaskState, reason: Optional[str]) -> None:
        self.publish_response(task.task_uuid, task.request_id, state, reason, task.seed)

    def _on_output(self, task: PoolTask, output: TaskOutput) -> None:
        if output.kind == OUTPUT_FEEDBACK:
            self._publish(self.exec_feedback_topic, {**self._identity(task.task_uuid, task.request_id), "status": TaskState.RUNNING.value, **(output.payload or {})})
            return
        if output.stream not in self.streams:
            _logger.warning("A task of %s wrote to the unknown stream %r", self.name, output.stream)
            return
        message = {**self._identity(task.task_uuid, task.request_id), **self.stream_message(task, output.stream, output.payload, output.final)}
        self._publish(self.stream_topic(output.stream), message)

    # Publishing

    def stream_topic(self, stream: str) -> str:
        return f"{self.sensor_topic}/{stream}"

    def publish_response(self, task_uuid: str, request_id: str, state: TaskState, reason: Optional[str] = None, seed: Optional[int] = None) -> None:
        self._publish(self.exec_response_topic, {**self._identity(task_uuid, request_id), "response": state.value, "fail-reason": reason, "seed": seed})

    def _identity(self, task_uuid: str, request_id: str) -> Dict[str, Any]:
        return {"stamp": time.time(), "task_sender": self.name, "task-uuid": task_uuid, "request-id": request_id}

    def _publish(self, topic: str, message: Mapping[str, Any]) -> None:
        if self.is_connected:
            self.client.publish(topic, json.dumps(message), qos=1)

    def publish_heartbeat_and_sensor_info(self) -> None:
        stamp = time.time()
        heartbeat = {
            "name": self.name,
            "agent-type": "virtual",
            "agent-description": self.description,
            "agent-uuid": self.uuid,
            "levels": ["sensor", "direct execution"],
            "rate": self.info_update_rate,
            "stamp": stamp,
            "type": "HeartBeat",
        }
        self.client.publish(self.heartbeat_topic, json.dumps(heartbeat), qos=1)
        sensor_info = {"name": self.name, "rate": self.info_update_rate, "sensor-data-provided": list(self.streams), "stamp": stamp, "type": "SensorInfo"}
        self.client.publish(self.sensor_info_topic, json.dumps(sensor_info), qos=1)
        direct_execution = {
            "name": self.name,
            "rate": self.info_update_rate,
            "type": "DirectExecutionInfo",
            "stamp": stamp,
            "tasks-available": [{"name": name, "signals": [CANCEL_SIGNAL, *self.signals]} for name in self.requests],
            "tasks-executing": [{"name": self.task_name_of(task), "uuid": task.task_uuid} for task in self.pool.tasks(TaskState.RUNNING)],
            "tasks-queued": [{"name": self.task_name_of(task), "uuid": task.task_uuid} for task in self.pool.tasks(TaskState.QUEUED)],
            "pool-size": self.max_workers,
        }
        self.client.publish(self.direct_execution_topic, json.dumps(direct_execution), qos=1)
