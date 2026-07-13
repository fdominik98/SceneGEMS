import json
import logging
import multiprocessing
import queue
import threading
import time
from multiprocessing import Process, Queue
from typing import Any, List, Optional, Tuple

import paho.mqtt.client as mqtt

from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from scenegems_tool.backend_service.serialization import serialize_frame
from scenegems_tool.scenario_generation.scenario_generation_types import MqttSceneGenerationTask
from scenegems_tool.scenario_generation.scene_generation_worker import run_scene_generation_worker
from scenegems_tool.waraps_integration.mqtt_client import MqttClient, MQttConnectionInfo
from scenegems_tool.waraps_integration.sim_utils import Geofence

_logger = logging.getLogger(__name__)
MAX_SCENE_GENERATION_WORKERS = 5
SCENARIO_GENERATION_SERVICE_NAME = "scenario_generation_service"
SCENARIO_GENERATION_SERVICE_TOPIC = f"waraps/service/virtual/real/{SCENARIO_GENERATION_SERVICE_NAME}"


class MqttScenarioGenerationService(MqttClient):
    def __init__(self, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence):
        self.info_update_rate = 1.0
        super().__init__(SCENARIO_GENERATION_SERVICE_NAME, SCENARIO_GENERATION_SERVICE_TOPIC, mqtt_connection, reference_geofence)
        self.scene_generation_task_queue: Queue[MqttSceneGenerationTask] = Queue()
        self.generated_scene_queue: Queue[Tuple[MqttSceneGenerationTask, EvaluationData]] = Queue()
        self.terminate_last_generation_event = multiprocessing.Event()
        self.current_tasks: List[MqttSceneGenerationTask] = []
        self._active_workers: List[Process] = []
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
        self.terminate_last_generation_event.set()
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
            )
            self.scene_generation_task_queue.put_nowait(task)
            self.current_tasks.append(task)

    @property
    def listen_topics(self) -> List[str]:
        return [
            self.exec_command_topic,
        ]

    def publish_heartbeat_and_sensor_info(self):
        heartbeat_command = {
            "name": self.name,
            "agent-type": "virtual",
            "agent-description": "Scenario Generation Subsystem",
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
                    "signals": [],
                }
            ],
            "tasks-executing": tasks_executing,
        }
        str_direct_execution_info_command = json.dumps(direct_execution_info_command)
        self.client.publish(self.direct_execution_topic, str_direct_execution_info_command, qos=1)

    def publish_generated_scene(self, task: MqttSceneGenerationTask, evaluation_data: EvaluationData):
        generated_scene_command = {
            "stamp": time.time(),
            "task_sender": task.sender,
            "task-uuid": task.task_uuid,
            "request-id": task.request_id,
            "generated-frame": serialize_frame(scenario_id=task.request_id, scene=evaluation_data.best_scene, timestamp=0, time_step=1),
            "evaluation-data": evaluation_data.to_dict(),
            "valid": bool(evaluation_data.is_valid),
        }
        str_generated_scene_command = json.dumps(generated_scene_command)
        self.client.publish(self.generated_scene_topic, str_generated_scene_command, qos=1)

    def _manage_worker_pool(self) -> None:
        while not self._worker_pool_stop_event.is_set():
            self._active_workers = [worker for worker in self._active_workers if worker.is_alive()]
            if len(self._active_workers) >= MAX_SCENE_GENERATION_WORKERS:
                time.sleep(0.1)
                continue
            try:
                task = self.scene_generation_task_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self.terminate_last_generation_event.clear()
            worker = Process(
                target=run_scene_generation_worker,
                args=(task, self.generated_scene_queue, self.terminate_last_generation_event),
                name=f"scene_generation_worker_{task.request_id}",
                daemon=True,
            )
            worker.start()
            self._active_workers.append(worker)

    def _poll_generated_scenes(self) -> None:
        while not self._worker_pool_stop_event.is_set():
            try:
                result = self.generated_scene_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if not self.is_connected:
                continue
            task, eval_data = result
            self.publish_generated_scene(task, eval_data)
            self.current_tasks = [current_task for current_task in self.current_tasks if current_task.task_uuid != task.task_uuid]

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
                self.scene_generation_task_queue.get_nowait()
            except queue.Empty:
                break
