"""The scene generation subsystem on the broker: a generate-scene request is one task, the search for one scene.

The pool, the task states and the channels are the ones every subsystem has (messaging/mqtt_pool_service.py).
A task publishes on sensor/generated_scene: its best scene so far once a second (final false), then the
final scene with whether it satisfies the class. A cancelled search publishes no final scene.
"""

from typing import Any, Dict, List, Mapping

from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
from scenegems_tool.gateway.serialization import serialize_frame
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.messaging.mqtt_pool_service import PoolService
from scenegems_tool.subsystems.pool.pool_task import PoolTask
from scenegems_tool.subsystems.scene_generation.scene_generation_types import GENERATE_SCENE_TASK, GENERATED_SCENE_STREAM, SCENE_GENERATION_SERVICE_NAME, MqttSceneGenerationTask
from scenegems_tool.subsystems.scene_generation.scene_generation_worker import run_scene_generation_worker
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence


class MqttSceneGenerationService(PoolService):
    description = "Scene Generation Subsystem"
    task_name = GENERATE_SCENE_TASK
    streams = (GENERATED_SCENE_STREAM,)
    worker = staticmethod(run_scene_generation_worker)

    def __init__(self, mqtt_connection: MQttConnectionInfo, reference_geofence: Geofence, max_workers: int = 1, name: str = SCENE_GENERATION_SERVICE_NAME, **options: Any):
        super().__init__(mqtt_connection, reference_geofence, max_workers, name, **options)

    def make_tasks(self, task_uuid: str, request_id: str, seed: int, params: Mapping[str, Any]) -> List[PoolTask]:
        return [
            MqttSceneGenerationTask(
                sender=self.name,
                task_uuid=task_uuid,
                request_id=request_id,
                seed=seed,
                functional_scenario_content=params["functional-scenario-content"],
                colregs_constraints_content=params["colregs-constraints-content"],
                vessel_types_content=params["vessel-types-content"],
                obstacle_types_content=params["obstacle-types-content"],
                timeout=params["timeout"],
                enforce_low_tcpa=bool(params.get("enforce-low-tcpa", False)),
            )
        ]

    def stream_message(self, task: PoolTask, stream: str, payload: EvaluationData, final: bool) -> Dict[str, Any]:
        return {
            "generated-frame": serialize_frame(scenario_id=task.request_id, scene=payload.best_scene, timestamp=0, time_step=1),
            "evaluation-data": payload.to_dict(),
            "valid": bool(payload.is_valid),
            "final": bool(final),  # the worker's last scene for the task; earlier ones are search progress
        }
