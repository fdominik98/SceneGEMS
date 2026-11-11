import json
import logging
import multiprocessing
import queue
import threading
import time
from multiprocessing import Process, Queue
from multiprocessing.synchronize import Event
from typing import Any, Dict, List, Optional

import paho.mqtt.client as mqtt

from scenegems_tool.messaging.mqtt_client import MqttClient, MQttConnectionInfo, service_topic
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import (  # noqa: F401 (re-exported names)
    MAX_TRAJECTORY_GENERATION_WORKERS,
    TRAJECTORY_GENERATION_SERVICE_NAME,
    TRAJECTORY_GENERATION_SERVICE_TOPIC,
    MqttTrajectoryGenerationTask,
    TrajectoryGenerationParams,
)
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_worker import run_trajectory_generation_worker
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

_logger = logging.getLogger(__name__)


class MqttTrajectoryGenerationService(MqttClient):
    def __init__(self, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence, max_workers: int = MAX_TRAJECTORY_GENERATION_WORKERS, name: str = TRAJECTORY_GENERATION_SERVICE_NAME):
        self.info_update_rate = 1.0
        self.max_workers = max_workers
        super().__init__(name, service_topic(mqtt_connection.topic_root, name), mqtt_connection, reference_geofence)
        self.task_queue: Queue[MqttTrajectoryGenerationTask] = Queue()
        self.preview_queue: Queue = Queue()
        self.result_queue: Queue = Queue()
        self.current_tasks: List[MqttTrajectoryGenerationTask] = []  # queued and running, in arrival order
        self._cancel_events: Dict[str, Event] = {}  # by task uuid: each search stops on its own event only
        self._tasks_lock = threading.Lock()
        self._active_workers: List[Process] = []
        self._worker_pool_stop_event = threading.Event()
        self._worker_pool_thread: Optional[threading.Thread] = None
        self._publisher_thread: Optional[threading.Thread] = None

    def start_runtime(self) -> None:
        self._worker_pool_stop_event.clear()
        self._worker_pool_thread = threading.Thread(target=self._manage_worker_pool, name="trajectory_generation_worker_pool", daemon=True)
        self._worker_pool_thread.start()
        self._publisher_thread = threading.Thread(target=self._poll_worker_output, name="trajectory_generation_publisher", daemon=True)
        self._publisher_thread.start()

    def stop_runtime(self) -> None:
        with self._tasks_lock:
            for event in self._cancel_events.values():
                event.set()
        self._worker_pool_stop_event.set()
        self._terminate_active_workers()
        if self._worker_pool_thread is not None:
            self._worker_pool_thread.join(timeout=2.0)
            self._worker_pool_thread = None
        if self._publisher_thread is not None:
            self._publisher_thread.join(timeout=2.0)
            self._publisher_thread = None
        with self._tasks_lock:
            self.current_tasks.clear()
            self._cancel_events.clear()
        self._drain_task_queue()

    def _on_message(self, msg: mqtt.MQTTMessage, payload: Any):
        if payload["execution-unit"] != self.name:
            return
        if payload["command"] == "start-task" and payload["task"]["name"] == "generate-trajectories":
            task_params = payload["task"]["params"]
            task = MqttTrajectoryGenerationTask(
                sender=self.name,
                task_uuid=payload["task-uuid"],
                request_id=task_params["request-id"],
                scenario_content=task_params["scenario-content"],
                colregs_constraints_content=task_params["colregs-constraints-content"],
                params=TrajectoryGenerationParams.from_task_params(task_params.get("params", {})),
                seed=task_params.get("seed"),
            )
            with self._tasks_lock:
                if self.max_workers == 1:
                    # Single worker: a new request supersedes whatever the pool holds. On a worker node the slot
                    # table allows one lease at a time, so that is only ever a search whose job has ended.
                    for event in self._cancel_events.values():
                        event.set()
                    self._drain_task_queue()
                    self.current_tasks = []
                    self._cancel_events = {}
                # With more workers, requests queue for the next free one.
                self.current_tasks.append(task)
                self._cancel_events[task.task_uuid] = multiprocessing.Event()
            self.task_queue.put_nowait(task)
        elif payload["command"] == "signal-task" and payload.get("signal", {}).get("name") == "cancel":
            self.cancel_request(payload["signal"].get("request-id"))

    def cancel_request(self, request_id: Optional[str]) -> None:
        """Stop the searches of one request: a running one ends with its best partial result, a queued one never starts."""
        if not request_id:
            _logger.warning("Ignored a cancel that names no request")
            return
        with self._tasks_lock:
            events = [self._cancel_events[task.task_uuid] for task in self.current_tasks if task.request_id == request_id and task.task_uuid in self._cancel_events]
        if not events:
            _logger.info("Cancel for request %s, which this pool does not hold", request_id)
            return
        for event in events:
            event.set()

    @property
    def listen_topics(self) -> List[str]:
        return [self.exec_command_topic]

    def publish_heartbeat_and_sensor_info(self):
        heartbeat_command = {
            "name": self.name,
            "agent-type": "virtual",
            "agent-description": "Trajectory Generation Subsystem",
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
            "sensor-data-provided": ["planned_trajectory", "planned_trajectory_preview"],
            "stamp": time.time(),
            "type": "SensorInfo",
        }
        self.client.publish(self.sensor_info_topic, json.dumps(sensor_info_command), qos=1)

        tasks_executing = [{"name": "generate-trajectories", "uuid": task.task_uuid} for task in self.current_tasks]
        direct_execution_info_command = {
            "name": self.name,
            "rate": self.info_update_rate,
            "type": "DirectExecutionInfo",
            "stamp": time.time(),
            "tasks-available": [{"name": "generate-trajectories", "signals": ["cancel"]}],
            "tasks-executing": tasks_executing,
        }
        self.client.publish(self.direct_execution_topic, json.dumps(direct_execution_info_command), qos=1)

    def publish_preview(self, task: MqttTrajectoryGenerationTask, trajectory_data: dict) -> None:
        command = {
            "stamp": time.time(),
            "task_sender": task.sender,
            "task-uuid": task.task_uuid,
            "request-id": task.request_id,
            "trajectory-data": trajectory_data,
        }
        self.client.publish(self.planned_trajectory_preview_topic, json.dumps(command), qos=1)

    def publish_result(self, task: MqttTrajectoryGenerationTask, trajectory_data: Optional[dict], valid: bool, error_message: Optional[str], complete: bool = False) -> None:
        command = {
            "stamp": time.time(),
            "task_sender": task.sender,
            "task-uuid": task.task_uuid,
            "request-id": task.request_id,
            "trajectory-data": trajectory_data,
            "valid": bool(valid),
            "complete": bool(complete),  # a complete plan; false for the best partial path, which is still valid
            "error-message": error_message,
        }
        self.client.publish(self.planned_trajectory_topic, json.dumps(command), qos=1)

    def _manage_worker_pool(self) -> None:
        while not self._worker_pool_stop_event.is_set():
            self._active_workers = [worker for worker in self._active_workers if worker.is_alive()]
            if len(self._active_workers) >= self.max_workers:
                time.sleep(0.1)
                continue
            try:
                task = self.task_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self._start_worker(task)

    def _start_worker(self, task: MqttTrajectoryGenerationTask) -> None:
        with self._tasks_lock:
            cancel_event = self._cancel_events.get(task.task_uuid)
            if cancel_event is None or cancel_event.is_set():
                # Cancelled or superseded while it queued: it never starts and publishes nothing.
                self._forget(task)
                return
        worker = Process(
            target=run_trajectory_generation_worker,
            args=(task, self.preview_queue, self.result_queue, cancel_event),
            name=f"trajectory_generation_worker_{task.request_id}",
            daemon=True,
        )
        worker.start()
        self._active_workers.append(worker)

    def _poll_worker_output(self) -> None:
        while not self._worker_pool_stop_event.is_set():
            if not self._publish_next_output(preview_timeout=0.2):
                time.sleep(0.05)

    def _publish_next_output(self, preview_timeout: float) -> bool:
        """Publish the next preview and the next result the workers queued; False when there was neither."""
        published = False
        try:
            task, trajectory_data = self.preview_queue.get(timeout=preview_timeout) if preview_timeout > 0 else self.preview_queue.get_nowait()
            if self.is_connected:
                self.publish_preview(task, trajectory_data)
            published = True
        except queue.Empty:
            pass
        try:
            task, trajectory_data, valid, complete, error_message = self.result_queue.get_nowait()
            if self.is_connected:
                self.publish_result(task, trajectory_data, valid, error_message, complete)
            with self._tasks_lock:
                self._forget(task)
            published = True
        except queue.Empty:
            pass
        return published

    def _forget(self, task: MqttTrajectoryGenerationTask) -> None:
        """Drop a task that ended or never started; the caller holds _tasks_lock."""
        self.current_tasks = [t for t in self.current_tasks if t.task_uuid != task.task_uuid]
        self._cancel_events.pop(task.task_uuid, None)

    def _terminate_active_workers(self) -> None:
        for worker in self._active_workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=2.0)
            if worker.is_alive():
                worker.kill()
                worker.join(timeout=1.0)
        self._active_workers.clear()

    def _drain_task_queue(self) -> None:
        while True:
            try:
                self.task_queue.get_nowait()
            except queue.Empty:
                break
