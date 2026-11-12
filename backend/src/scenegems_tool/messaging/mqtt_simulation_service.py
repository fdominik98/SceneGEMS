"""The simulation subsystem on the broker: a run-simulation request is one task, one run of every vessel's stack.

The pool, the task states and the channels are the ones every subsystem has (messaging/mqtt_pool_service.py).
A request names the job it belongs to and carries the simulation job's payload; its seed is the payload's run
seed. Different requests run side by side, each with a vessel stack of its own, as many as the pool has places.

While a task runs it takes two signals besides cancel: observe ({"active", "speed"}: somebody watches the run,
at that many times real time, or stopped watching) and start (the operator's Start of an attended run). It publishes

    exec/feedback              the run's status, with its detail: the phase of an attended run, what its vessels
                               still lack, the ports a ground control station connects to
    sensor/simulation_frames   the frames of an observed run, in batches: {"index", "frames"}
    sensor/simulation_log      the lines the run's containers wrote, in batches: {"index", "lines": [{source, text, stream}]}
    sensor/simulation_result   at the end: {"result"} as the simulation job returns it, or {"error", "retryable"}
                               for a run that failed with a reason, and how many frame and log batches went before it

The run itself is subsystems/simulation/simulation_worker.py.

A run that is judged while it runs has a series of its own in the worker node's monitoring subsystem, which its
runner container requested (cluster/worker_node/jobs/pooled_series.py). When such a run's task ends, however
it ends, the service cancels that series: a runner that was killed could not, and its series would hold a
place of the monitoring pool until it idles out. For a series that is already closed the cancel changes nothing.

The subsystem takes a second request, compare-repeats: how far the finished repeats of one run on one stack
drift apart (cluster/worker_node/jobs/calibration_deviation_job.py). It is one task that starts no container,
takes no signal but cancel, reports its progress and publishes its result on sensor/simulation_result too.
"""

import json
import time
import uuid
from typing import Any, Dict, List, Mapping, Optional

from scenegems_tool.cluster.worker_node.instance_scope import pooled_service_name
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo, service_topic
from scenegems_tool.messaging.mqtt_pool_service import PoolService
from scenegems_tool.subsystems.monitoring.monitoring_types import MONITORING_SERVICE_NAME, live_series_request_id
from scenegems_tool.subsystems.pool.pool_task import PoolTask, TaskState
from scenegems_tool.subsystems.simulation.simulation_types import (
    COMPARE_REPEATS_TASK,
    OBSERVE_SIGNAL,
    RUN_SIMULATION_TASK,
    SIMULATION_FRAMES_STREAM,
    SIMULATION_LOG_STREAM,
    SIMULATION_RESULT_STREAM,
    SIMULATION_SERVICE_NAME,
    START_SIGNAL,
    CompareRepeatsTask,
    RunSimulationTask,
)
from scenegems_tool.subsystems.simulation.simulation_worker import run_simulation_worker, worker_node_number
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence


class MqttSimulationService(PoolService):
    description = "Simulation Subsystem"
    task_name = RUN_SIMULATION_TASK
    task_names = (RUN_SIMULATION_TASK, COMPARE_REPEATS_TASK)
    signals = (OBSERVE_SIGNAL, START_SIGNAL)
    streams = (SIMULATION_FRAMES_STREAM, SIMULATION_LOG_STREAM, SIMULATION_RESULT_STREAM)
    worker = staticmethod(run_simulation_worker)

    def __init__(self, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence, max_workers: int = 1, name: str = SIMULATION_SERVICE_NAME, **options: Any):
        super().__init__(mqtt_connection, reference_geofence, max_workers, name, **options)

    def make_tasks(self, task_uuid: str, request_id: str, seed: int, params: Mapping[str, Any]) -> List[PoolTask]:
        job_id = str(params["job-id"])
        attempt = int(params.get("attempt", 1))
        payload = params["payload"]
        if not job_id:
            raise ValueError("a run names the job it belongs to")
        if attempt < 1:
            raise ValueError(f"an attempt is at least 1, got {attempt}")
        if not isinstance(payload, Mapping) or not payload.get("runner"):
            raise ValueError("the payload names its runner")
        return [RunSimulationTask(sender=self.name, task_uuid=task_uuid, request_id=request_id, seed=seed, job_id=job_id, attempt=attempt, payload=dict(payload))]

    def make_tasks_of(self, name: str, task_uuid: str, request_id: str, seed: int, params: Mapping[str, Any]) -> List[PoolTask]:
        if name != COMPARE_REPEATS_TASK:
            return self.make_tasks(task_uuid, request_id, seed, params)
        payload = params["payload"]
        if not isinstance(payload, Mapping) or not isinstance(payload.get("trajectories"), list):
            raise ValueError("the payload lists the repeats' trajectories")
        return [CompareRepeatsTask(sender=self.name, task_uuid=task_uuid, request_id=request_id, seed=seed, payload=dict(payload))]

    def task_name_of(self, task: PoolTask) -> str:
        return COMPARE_REPEATS_TASK if isinstance(task, CompareRepeatsTask) else RUN_SIMULATION_TASK

    @property
    def monitoring_service(self) -> str:
        """The name of the same worker node's monitoring subsystem: this subsystem's number, or the subsystem's own name beside a simulation subsystem on its own."""
        numbered = self.name.rpartition("-")[2].isdigit()
        return pooled_service_name("monitoring", worker_node_number(self.name)) if numbered else MONITORING_SERVICE_NAME

    def _on_state(self, task: PoolTask, state: TaskState, reason: Optional[str]) -> None:
        super()._on_state(task, state, reason)
        if state.is_final and isinstance(task, RunSimulationTask) and task.payload.get("monitor") == "live":
            self._cancel_series(task)

    def _cancel_series(self, task: RunSimulationTask) -> None:
        """Tell the monitoring subsystem to end the series of the run, in case its runner could not."""
        service = self.monitoring_service
        command = {
            "stamp": time.time(),
            "task_sender": self.name,
            "task-uuid": str(uuid.uuid4()),
            "command": "signal-task",
            "execution-unit": service,
            "signal": {"name": "cancel", "request-id": live_series_request_id(task.request_id)},
        }
        if self.is_connected:
            self.client.publish(f"{service_topic(self.mqtt_connection.topic_root, service)}/exec/command", json.dumps(command), qos=1)

    def stream_message(self, task: PoolTask, stream: str, payload: Mapping[str, Any], final: bool) -> Dict[str, Any]:
        return {**payload, "final": bool(final)}
