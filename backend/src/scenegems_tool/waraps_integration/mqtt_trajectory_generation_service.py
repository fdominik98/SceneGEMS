import json
import logging
import multiprocessing
import queue
import threading
import time
from multiprocessing import Process, Queue
from typing import Any, List, Optional

import paho.mqtt.client as mqtt

from scenegems_tool.trajectory_generation.trajectory_generation_types import MqttTrajectoryGenerationTask, TrajectoryGenerationParams
from scenegems_tool.trajectory_generation.trajectory_generation_worker import run_trajectory_generation_worker
from scenegems_tool.waraps_integration.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.waraps_integration.sim_utils import Geofence

_logger = logging.getLogger(__name__)

# Deliberately one worker only: RRT trajectory generation is a single long run and the
# subsystem is scoped to one request at a time (see project spec).
MAX_TRAJECTORY_GENERATION_WORKERS = 1
TRAJECTORY_GENERATION_SERVICE_NAME = "trajectory_generation_service"
TRAJECTORY_GENERATION_SERVICE_TOPIC = f"waraps/service/virtual/real/{TRAJECTORY_GENERATION_SERVICE_NAME}"


class MqttTrajectoryGenerationService(MqttClient):
    def __init__(self, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence):
        self.info_update_rate = 1.0
        super().__init__(TRAJECTORY_GENERATION_SERVICE_NAME, TRAJECTORY_GENERATION_SERVICE_TOPIC, mqtt_connection, reference_geofence)
        self.task_queue: Queue[MqttTrajectoryGenerationTask] = Queue()
        self.preview_queue: Queue = Queue()
        self.result_queue: Queue = Queue()
        self.terminate_event = multiprocessing.Event()
        self.current_tasks: List[MqttTrajectoryGenerationTask] = []
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
        self.terminate_event.set()
        self._worker_pool_stop_event.set()
        self._terminate_active_workers()
        if self._worker_pool_thread is not None:
            self._worker_pool_thread.join(timeout=2.0)
            self._worker_pool_thread = None
        if self._publisher_thread is not None:
            self._publisher_thread.join(timeout=2.0)
            self._publisher_thread = None
        self.current_tasks.clear()
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
            )
            # Single-worker subsystem: a new request supersedes whatever is running.
            self.terminate_event.set()
            self._drain_task_queue()
            self.current_tasks = [task]
            self.task_queue.put_nowait(task)
        elif payload["command"] == "signal-task" and payload.get("signal", {}).get("name") == "cancel":
            self.terminate_event.set()

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

    def publish_result(self, task: MqttTrajectoryGenerationTask, trajectory_data: Optional[dict], valid: bool, error_message: Optional[str]) -> None:
        command = {
            "stamp": time.time(),
            "task_sender": task.sender,
            "task-uuid": task.task_uuid,
            "request-id": task.request_id,
            "trajectory-data": trajectory_data,
            "valid": bool(valid),
            "error-message": error_message,
        }
        self.client.publish(self.planned_trajectory_topic, json.dumps(command), qos=1)

    def _manage_worker_pool(self) -> None:
        while not self._worker_pool_stop_event.is_set():
            self._active_workers = [worker for worker in self._active_workers if worker.is_alive()]
            if len(self._active_workers) >= MAX_TRAJECTORY_GENERATION_WORKERS:
                time.sleep(0.1)
                continue
            try:
                task = self.task_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self.terminate_event.clear()
            worker = Process(
                target=run_trajectory_generation_worker,
                args=(task, self.preview_queue, self.result_queue, self.terminate_event),
                name=f"trajectory_generation_worker_{task.request_id}",
                daemon=True,
            )
            worker.start()
            self._active_workers.append(worker)

    def _poll_worker_output(self) -> None:
        while not self._worker_pool_stop_event.is_set():
            published = False
            try:
                task, trajectory_data = self.preview_queue.get(timeout=0.2)
                if self.is_connected:
                    self.publish_preview(task, trajectory_data)
                published = True
            except queue.Empty:
                pass
            try:
                task, trajectory_data, valid, error_message = self.result_queue.get_nowait()
                if self.is_connected:
                    self.publish_result(task, trajectory_data, valid, error_message)
                self.current_tasks = [t for t in self.current_tasks if t.task_uuid != task.task_uuid]
                published = True
            except queue.Empty:
                pass
            if not published:
                time.sleep(0.05)

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
