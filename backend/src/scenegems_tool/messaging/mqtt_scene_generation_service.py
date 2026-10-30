import json
import logging
import multiprocessing
import queue
import threading
import time
from multiprocessing import Process, Queue
from multiprocessing.synchronize import Event
from typing import Any, Dict, List, Optional, Tuple

import paho.mqtt.client as mqtt

from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from scenegems_tool.gateway.serialization import serialize_frame
from scenegems_tool.messaging.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.subsystems.scene_generation.scene_generation_types import (  # noqa: F401 (re-exported names)
    MAX_SCENE_GENERATION_WORKERS,
    SCENE_GENERATION_SERVICE_NAME,
    SCENE_GENERATION_SERVICE_TOPIC,
    MqttSceneGenerationTask,
)
from scenegems_tool.subsystems.scene_generation.scene_generation_worker import run_scene_generation_worker
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

_logger = logging.getLogger(__name__)


class MqttSceneGenerationService(MqttClient):
    def __init__(self, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence, max_workers: int = MAX_SCENE_GENERATION_WORKERS):
        self.info_update_rate = 1.0
        self.max_workers = max_workers
        super().__init__(SCENE_GENERATION_SERVICE_NAME, SCENE_GENERATION_SERVICE_TOPIC, mqtt_connection, reference_geofence)
        self.scene_generation_task_queue: Queue[MqttSceneGenerationTask] = Queue()
        self.generated_scene_queue: Queue[Tuple[MqttSceneGenerationTask, EvaluationData, bool]] = Queue()  # task, scene, final
        self.current_tasks: List[MqttSceneGenerationTask] = []  # queued and running, in arrival order
        self._cancel_events: Dict[str, Event] = {}  # by task uuid: each search stops on its own event only
        self._tasks_lock = threading.Lock()
        self._active_workers: List[Tuple[Process, MqttSceneGenerationTask]] = []
        self._worker_pool_stop_event = threading.Event()
        self._worker_pool_thread: Optional[threading.Thread] = None
        self._publisher_thread: Optional[threading.Thread] = None

    def start_runtime(self) -> None:
        self._worker_pool_stop_event.clear()
        self._worker_pool_thread = threading.Thread(target=self._manage_worker_pool, name="scene_generation_worker_pool", daemon=True)
        self._worker_pool_thread.start()
        self._publisher_thread = threading.Thread(target=self._poll_generated_scenes, name="scene_generation_publisher", daemon=True)
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
        if payload["command"] == "start-task" and payload["task"]["name"] == "generate-scene":
            task = MqttSceneGenerationTask(
                sender=self.name,
                task_uuid=payload["task-uuid"],
                request_id=payload["task"]["params"]["request-id"],
                functional_scenario_content=payload["task"]["params"]["functional-scenario-content"],
                colregs_constraints_content=payload["task"]["params"]["colregs-constraints-content"],
                vessel_types_content=payload["task"]["params"]["vessel-types-content"],
                obstacle_types_content=payload["task"]["params"]["obstacle-types-content"],
                timeout=payload["task"]["params"]["timeout"],
                enforce_low_tcpa=bool(payload["task"]["params"].get("enforce-low-tcpa", False)),
                seed=payload["task"]["params"].get("seed"),
            )
            with self._tasks_lock:
                self.current_tasks.append(task)
                self._cancel_events[task.task_uuid] = multiprocessing.Event()
            self.scene_generation_task_queue.put_nowait(task)
        elif payload["command"] == "signal-task" and payload.get("signal", {}).get("name") == "cancel":
            self.cancel_request(payload["signal"].get("request-id"))

    def cancel_request(self, request_id: Optional[str]) -> None:
        """Stop the generations of one request: a running one ends without a scene, a queued one never starts."""
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
        return [
            self.exec_command_topic,
        ]

    def publish_heartbeat_and_sensor_info(self):
        heartbeat_command = {
            "name": self.name,
            "agent-type": "virtual",
            "agent-description": "Scene Generation Subsystem",
            "agent-uuid": self.uuid,
            "levels": [
                "sensor",
                "direct execution",
            ],
            "rate": self.info_update_rate,
            "stamp": time.time(),
            "type": "HeartBeat",
        }
        str_heartbeat_command = json.dumps(heartbeat_command)
        self.client.publish(self.heartbeat_topic, str_heartbeat_command, qos=1)
        sensor_info_command = {
            "name": self.name,
            "rate": self.info_update_rate,
            "sensor-data-provided": ["generated_scene"],
            "stamp": time.time(),
            "type": "SensorInfo",
        }

        str_sensor_info_command = json.dumps(sensor_info_command)
        self.client.publish(self.sensor_info_topic, str_sensor_info_command, qos=1)

        tasks_executing = [
            {
                "name": "generate-scene",
                "uuid": task.task_uuid,
            }
            for task in self.current_tasks
        ]
        direct_execution_info_command = {
            "name": self.name,
            "rate": self.info_update_rate,
            "type": "DirectExecutionInfo",
            "stamp": time.time(),
            "tasks-available": [
                {
                    "name": "generate-scene",
                    "signals": ["cancel"],
                }
            ],
            "tasks-executing": tasks_executing,
        }
        str_direct_execution_info_command = json.dumps(direct_execution_info_command)
        self.client.publish(self.direct_execution_topic, str_direct_execution_info_command, qos=1)

    def publish_generated_scene(self, task: MqttSceneGenerationTask, evaluation_data: EvaluationData, final: bool = True):
        generated_scene_command = {
            "stamp": time.time(),
            "task_sender": task.sender,
            "task-uuid": task.task_uuid,
            "request-id": task.request_id,
            "generated-frame": serialize_frame(scenario_id=task.request_id, scene=evaluation_data.best_scene, timestamp=0, time_step=1),
            "evaluation-data": evaluation_data.to_dict(),
            "valid": bool(evaluation_data.is_valid),
            "final": bool(final),  # the worker's last scene for the task; earlier ones are search progress
        }
        str_generated_scene_command = json.dumps(generated_scene_command)
        self.client.publish(self.generated_scene_topic, str_generated_scene_command, qos=1)

    def _manage_worker_pool(self) -> None:
        while not self._worker_pool_stop_event.is_set():
            self._reap_workers()
            if len(self._active_workers) >= self.max_workers:
                time.sleep(0.1)
                continue
            try:
                task = self.scene_generation_task_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self._start_worker(task)

    def _start_worker(self, task: MqttSceneGenerationTask) -> None:
        with self._tasks_lock:
            cancel_event = self._cancel_events.get(task.task_uuid)
            if cancel_event is None or cancel_event.is_set():
                # Cancelled while it queued: it never starts and publishes nothing.
                self._forget(task)
                return
        worker = Process(
            target=run_scene_generation_worker,
            args=(task, self.generated_scene_queue, cancel_event),
            name=f"scene_generation_worker_{task.request_id}",
            daemon=True,
        )
        worker.start()
        self._active_workers.append((worker, task))

    def _reap_workers(self) -> None:
        """Forget the tasks of workers that ended; a cancelled worker publishes no final scene, so this is what frees its task."""
        ended = [(worker, task) for worker, task in self._active_workers if not worker.is_alive()]
        if not ended:
            return
        self._active_workers = [entry for entry in self._active_workers if entry not in ended]
        with self._tasks_lock:
            for _, task in ended:
                self._forget(task)

    def _poll_generated_scenes(self) -> None:
        while not self._worker_pool_stop_event.is_set():
            self._publish_next_scene(timeout=0.5)

    def _publish_next_scene(self, timeout: float) -> bool:
        """Publish the next scene a worker queued; False when there was none."""
        try:
            task, eval_data, final = self.generated_scene_queue.get(timeout=timeout) if timeout > 0 else self.generated_scene_queue.get_nowait()
        except queue.Empty:
            return False
        if self.is_connected:
            self.publish_generated_scene(task, eval_data, final)
        if final:
            with self._tasks_lock:
                self._forget(task)
        return True

    def _forget(self, task: MqttSceneGenerationTask) -> None:
        """Drop a task that ended or never started; the caller holds _tasks_lock."""
        self.current_tasks = [t for t in self.current_tasks if t.task_uuid != task.task_uuid]
        self._cancel_events.pop(task.task_uuid, None)

    def _terminate_active_workers(self) -> None:
        for worker, _ in self._active_workers:
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
                self.scene_generation_task_queue.get_nowait()
            except queue.Empty:
                break
