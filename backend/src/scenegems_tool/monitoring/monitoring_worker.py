import threading
import time
from typing import Dict, List, Optional, Tuple

from concrete_level.colregs_monitoring.colregs_monitor_runtime import ColregsMonitorRuntime, MonitoringTask
from concrete_level.colregs_monitoring.monitored_trajectory import MonitoredSceneWithResults
from scenegems_tool.waraps_integration.mqtt_client import MQttConnectionInfo
from scenegems_tool.waraps_integration.mqtt_monitor_service import (
    MqttMonitoringBatchTask,
    MqttMonitoringTask,
    MqttMonitorService,
)
from scenegems_tool.waraps_integration.sim_utils import Geofence
from utils.colregs_approximations import COLREGSConstraints
from utils.global_constants import ONE_SECOND


class MonitorRuntimeWrapper:
    def __init__(self, colregs_constants: COLREGSConstraints):
        self.colregs_constants = colregs_constants
        self.monitor_runtime = ColregsMonitorRuntime(colregs_constants)
        self.timestamp_task_map: Dict[int, MqttMonitoringTask] = {}

    def monitor_task(self, task: MqttMonitoringTask) -> List[Tuple[MqttMonitoringTask, MonitoredSceneWithResults]]:
        return self.monitor_tasks([task])

    def monitor_tasks(self, tasks: List[MqttMonitoringTask]) -> List[Tuple[MqttMonitoringTask, MonitoredSceneWithResults]]:
        if not tasks:
            return []
        if tasks[0].scene_timestamp == 0 and self.monitor_runtime.is_initialized:
            self.monitor_runtime = ColregsMonitorRuntime(self.colregs_constants)
            self.timestamp_task_map.clear()
        for task in tasks:
            self.timestamp_task_map[task.scene_timestamp] = task
            monitoring_task = MonitoringTask(scene=task.scene, scene_timestamp=task.scene_timestamp, time_step=task.time_step)
            self.monitor_runtime.add_task(monitoring_task)
        monitored_scenes = self.monitor_runtime.monitor_current_tasks()
        return [(self.timestamp_task_map[monitored_scene.timestamp], monitored_scene) for monitored_scene in monitored_scenes]

    @property
    def is_empty(self) -> bool:
        return not self.monitor_runtime.has_tasks


class MonitoringWorker:
    """Runs COLREGS monitoring tasks inside the monitoring Docker container."""

    def __init__(
        self,
        mqtt_connection: MQttConnectionInfo,
        topic: str,
        agent_name: str,
        reference_geofence: Geofence,
        colregs_constants: COLREGSConstraints,
    ):
        self.mqtt_service = MqttMonitorService(
            mqtt_connection,
            topic,
            agent_name,
            reference_geofence,
        )
        self.colregs_constants = colregs_constants
        self.publish_period = 1.0 / self.mqtt_service.info_update_rate
        self.monitoring_tick_period = ONE_SECOND / 50.0
        self.monitor_runtimes: Dict[str, MonitorRuntimeWrapper] = {}
        self._stop_event = threading.Event()
        self._current_tasks: List[MqttMonitoringTask] = []
        self._current_tasks_lock = threading.Lock()
        self._heartbeat_thread: Optional[threading.Thread] = None

    def run(self) -> None:
        self.mqtt_service.connect()
        self._start_heartbeat_thread()
        next_monitor_step_time = time.monotonic() + self.monitoring_tick_period
        try:
            while not self._stop_event.is_set():
                if not self.mqtt_service.is_connected:
                    self._stop_event.wait(0.1)
                    next_monitor_step_time = time.monotonic() + self.monitoring_tick_period
                    continue

                now = time.monotonic()
                next_monitor_step_time = self._process_task_if_due(now, next_monitor_step_time)

                wait_period = self._compute_wait_period(next_monitor_step_time)
                self._stop_event.wait(wait_period)
        finally:
            self._stop_heartbeat_thread()
            self.mqtt_service.disconnect()

    def stop(self) -> None:
        self._stop_event.set()

    def _start_heartbeat_thread(self) -> None:
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="monitoring_heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    def _stop_heartbeat_thread(self) -> None:
        if self._heartbeat_thread is None:
            return
        self._heartbeat_thread.join(timeout=self.publish_period + 1.0)
        self._heartbeat_thread = None

    def _heartbeat_loop(self) -> None:
        next_publish_time = time.monotonic()
        while not self._stop_event.is_set():
            if not self.mqtt_service.is_connected:
                self._stop_event.wait(0.1)
                next_publish_time = time.monotonic()
                continue

            now = time.monotonic()
            if now >= next_publish_time:
                with self._current_tasks_lock:
                    current_tasks = list(self._current_tasks)
                self.mqtt_service.publish_heartbeat_and_sensor_info(current_tasks=current_tasks)
                next_publish_time = now + self.publish_period

            wait_period = max(0.0, min(next_publish_time - time.monotonic(), 0.1))
            self._stop_event.wait(wait_period)

    def _process_task_if_due(self, now: float, next_monitor_step_time: float) -> float:
        if self.mqtt_service.monitoring_task_queue.empty():
            return now + ONE_SECOND
        if now < next_monitor_step_time:
            return next_monitor_step_time

        queued_item = self.mqtt_service.monitoring_task_queue.get()
        if isinstance(queued_item, MqttMonitoringBatchTask):
            self._process_batch_monitor_task(queued_item)
        else:
            self._process_single_monitor_task(queued_item)
        return now + self.monitoring_tick_period

    def _process_batch_monitor_task(self, batch_task: MqttMonitoringBatchTask) -> None:
        monitor_tasks = [
            MqttMonitoringTask(
                sender=batch_task.sender,
                task_uuid=batch_task.task_uuid,
                scenario_id=batch_task.scenario_id,
                scene=scene,
                scene_timestamp=timestamp,
                time_step=batch_task.time_step,
                is_simulation_frame=batch_task.is_simulation_frame,
            )
            for scene, timestamp in zip(batch_task.scenes, batch_task.scene_timestamps)
        ]
        with self._current_tasks_lock:
            self._current_tasks.extend(monitor_tasks)
        runtime = self._runtime_for_trajectory(batch_task.trajectory_id)
        monitor_result = runtime.monitor_tasks(monitor_tasks)
        self.mqtt_service.publish_monitored_scene_batch(batch_task, monitor_result)
        with self._current_tasks_lock:
            for task in monitor_tasks:
                if task in self._current_tasks:
                    self._current_tasks.remove(task)

    def _process_single_monitor_task(self, task: MqttMonitoringTask) -> None:
        with self._current_tasks_lock:
            self._current_tasks.append(task)
        runtime = self._runtime_for_trajectory(task.trajectory_id)
        monitor_result = runtime.monitor_task(task)
        for completed_task, monitored_scene in monitor_result:
            self.mqtt_service.publish_monitored_scene(completed_task, monitored_scene)
            with self._current_tasks_lock:
                if completed_task in self._current_tasks:
                    self._current_tasks.remove(completed_task)

    def _runtime_for_trajectory(self, trajectory_id: str) -> MonitorRuntimeWrapper:
        if trajectory_id not in self.monitor_runtimes:
            self.monitor_runtimes[trajectory_id] = MonitorRuntimeWrapper(self.colregs_constants)
        return self.monitor_runtimes[trajectory_id]

    def _compute_wait_period(self, next_monitor_step_time: float) -> float:
        if self.mqtt_service.monitoring_task_queue.empty():
            return 0.1
        now = time.monotonic()
        return max(0.0, next_monitor_step_time - now)
