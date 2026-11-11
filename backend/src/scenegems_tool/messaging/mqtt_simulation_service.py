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
"""

from typing import Any, Dict, List, Mapping

from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.messaging.mqtt_pool_service import PoolService
from scenegems_tool.subsystems.pool.pool_task import PoolTask
from scenegems_tool.subsystems.simulation.simulation_types import (
    OBSERVE_SIGNAL,
    RUN_SIMULATION_TASK,
    SIMULATION_FRAMES_STREAM,
    SIMULATION_LOG_STREAM,
    SIMULATION_RESULT_STREAM,
    SIMULATION_SERVICE_NAME,
    START_SIGNAL,
    RunSimulationTask,
)
from scenegems_tool.subsystems.simulation.simulation_worker import run_simulation_worker
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence


class MqttSimulationService(PoolService):
    description = "Simulation Subsystem"
    task_name = RUN_SIMULATION_TASK
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

    def stream_message(self, task: PoolTask, stream: str, payload: Mapping[str, Any], final: bool) -> Dict[str, Any]:
        return {**payload, "final": bool(final)}
