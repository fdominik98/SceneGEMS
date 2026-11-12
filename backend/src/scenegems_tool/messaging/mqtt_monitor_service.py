"""The monitoring subsystem on the broker: a monitor-scenario request is one task, judging one series of scenes.

The pool, the task states and the channels are the ones every subsystem has (messaging/mqtt_pool_service.py).
The scenes of a series follow its request as scenes signals, in time order, and a close signal ends it
(subsystems/monitoring/monitoring_types.py). Two series of one scenario never run at once: the later one
waits in the queue until the earlier is over; series of different scenarios run side by side, as many as the
pool has places.

A task publishes on sensor/monitored-scene one message per judged batch: the batch's index, how many scenes
of the series are judged, whether every rule has its final outcome (every-rule-decided), and the monitored
frames when the request, or that batch's scenes signal, asked for them. Once every rule has its
final outcome it says so on exec/feedback (detail.stop-advised). At the close it publishes the verdict on
sensor/monitor_result: the series' size and the rule outcomes (subsystems/monitoring/rule_outcomes.py).
"""

from typing import Any, Dict, List, Mapping

from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.messaging.mqtt_pool_service import PoolService
from scenegems_tool.subsystems.monitoring.monitoring_types import (
    CLOSE_SIGNAL,
    MONITOR_RESULT_STREAM,
    MONITOR_SCENARIO_TASK,
    MONITORED_SCENE_STREAM,
    MONITORING_SERVICE_NAME,
    SCENES_SIGNAL,
    MonitorScenarioTask,
)
from scenegems_tool.subsystems.monitoring.monitoring_worker import run_monitoring_worker
from scenegems_tool.subsystems.pool.pool_task import PoolTask
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence


class MqttMonitoringService(PoolService):
    description = "Monitoring Subsystem"
    task_name = MONITOR_SCENARIO_TASK
    signals = (SCENES_SIGNAL, CLOSE_SIGNAL)
    streams = (MONITORED_SCENE_STREAM, MONITOR_RESULT_STREAM)
    worker = staticmethod(run_monitoring_worker)

    def __init__(self, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence, max_workers: int = 1, name: str = MONITORING_SERVICE_NAME, **options: Any):
        super().__init__(mqtt_connection, reference_geofence, max_workers, name, **options)

    def make_tasks(self, task_uuid: str, request_id: str, seed: int, params: Mapping[str, Any]) -> List[PoolTask]:
        scenario_id = str(params["scenario-id"])
        time_step = int(params["time-step"])
        constants = params["colregs-constraints-content"]  # named by every request; null for the general maritime defaults
        if not scenario_id:
            raise ValueError("a series names its scenario")
        if time_step < 1:
            raise ValueError(f"the time step of a series is at least 1, got {time_step}")
        if constants is not None and not isinstance(constants, str):
            raise TypeError("the COLREGS constants are YAML text, or null for the defaults")
        return [
            MonitorScenarioTask(
                sender=self.name,
                task_uuid=task_uuid,
                request_id=request_id,
                seed=seed,
                scenario_id=scenario_id,
                time_step=time_step,
                colregs_constraints_content=constants,
                include_frames=bool(params.get("include-frames", False)),
            )
        ]

    def stream_message(self, task: PoolTask, stream: str, payload: Mapping[str, Any], final: bool) -> Dict[str, Any]:
        return {"scenario-id": getattr(task, "scenario_id", ""), **payload, "final": bool(final)}
