from dataclasses import dataclass
from typing import Optional

# Kept apart from the service module, which imports the generation code, so launchers and
# clients can name the service without loading it.
MAX_SCENE_GENERATION_WORKERS = 5  # the workbench pool; a worker node sizes its pool by its slots
SCENE_GENERATION_SERVICE_NAME = "scene_generation_service"
SCENE_GENERATION_SERVICE_TOPIC = f"waraps/service/virtual/real/{SCENE_GENERATION_SERVICE_NAME}"


@dataclass(frozen=True)
class MqttSceneGenerationTask:
    sender: str
    task_uuid: str
    request_id: str
    functional_scenario_content: str
    colregs_constraints_content: str
    vessel_types_content: str
    obstacle_types_content: str
    timeout: int
    enforce_low_tcpa: bool = False
    seed: Optional[int] = None  # seeds random and numpy at task start; a fresh seed when None
