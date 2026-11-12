from dataclasses import dataclass

from scenegems_tool.subsystems.pool.pool_task import PoolTask

# Kept apart from the service module, which imports the generation code, so launchers and
# requesters can name the service, its task and its stream without loading it.
# The service's name on its own. A worker node's instance takes the name the cluster gave it
# (scene-generation-subsystem-<number>) and the topic root of its broker (messaging/mqtt_client.py service_topic).
SCENE_GENERATION_SERVICE_NAME = "scene-generation-subsystem"
GENERATE_SCENE_TASK = "generate-scene"  # the start-task name of a request
GENERATED_SCENE_STREAM = "generated_scene"  # sensor/generated_scene: the best scene so far while it searches, then the final one


@dataclass(frozen=True)
class MqttSceneGenerationTask(PoolTask):
    """The search for one scene of a functional equivalence class. Its seed (PoolTask.seed) seeds random and numpy at the start, so it fixes the scene."""

    functional_scenario_content: str
    colregs_constraints_content: str
    vessel_types_content: str
    obstacle_types_content: str
    timeout: int
    enforce_low_tcpa: bool = False
