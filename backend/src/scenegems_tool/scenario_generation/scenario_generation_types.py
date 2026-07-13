from dataclasses import dataclass


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
