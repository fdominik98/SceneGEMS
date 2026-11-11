"""The trajectory generation subsystem on the broker: a generate-trajectories request is one task, one plan for a scene.

The pool, the task states and the channels are the ones every subsystem has (messaging/mqtt_pool_service.py).
A task publishes previews of its plan on sensor/planned_trajectory_preview while it searches and its result on
sensor/planned_trajectory: the trajectories, whether a plan was found (valid), whether it is a whole one
(complete; false for the best partial path, which is still valid) and the reason when there is none.
"""

from typing import Any, Dict, List, Mapping

from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.messaging.mqtt_pool_service import PoolService
from scenegems_tool.subsystems.pool.pool_task import PoolTask
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import (
    GENERATE_TRAJECTORIES_TASK,
    TRAJECTORY_GENERATION_SERVICE_NAME,
    TRAJECTORY_PREVIEW_STREAM,
    TRAJECTORY_RESULT_STREAM,
    MqttTrajectoryGenerationTask,
    TrajectoryGenerationParams,
)
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_worker import run_trajectory_generation_worker
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence


class MqttTrajectoryGenerationService(PoolService):
    description = "Trajectory Generation Subsystem"
    task_name = GENERATE_TRAJECTORIES_TASK
    streams = (TRAJECTORY_RESULT_STREAM, TRAJECTORY_PREVIEW_STREAM)
    worker = staticmethod(run_trajectory_generation_worker)

    def __init__(self, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence, max_workers: int = 1, name: str = TRAJECTORY_GENERATION_SERVICE_NAME, **options: Any):
        super().__init__(mqtt_connection, reference_geofence, max_workers, name, **options)

    def make_tasks(self, task_uuid: str, request_id: str, seed: int, params: Mapping[str, Any]) -> List[PoolTask]:
        return [
            MqttTrajectoryGenerationTask(
                sender=self.name,
                task_uuid=task_uuid,
                request_id=request_id,
                seed=seed,
                scenario_content=params["scenario-content"],
                colregs_constraints_content=params["colregs-constraints-content"],
                params=TrajectoryGenerationParams.from_task_params(params.get("params", {})),
            )
        ]

    def stream_message(self, task: PoolTask, stream: str, payload: Any, final: bool) -> Dict[str, Any]:
        if stream == TRAJECTORY_PREVIEW_STREAM:
            return {"trajectory-data": payload}
        return dict(payload)  # the result as the worker put it: trajectory-data, valid, complete, error-message
