"""The module of each job type. Every module defines its payload model (PAYLOAD_MODEL), its artifact fields
(ARTIFACT_INPUT_FIELDS, ARTIFACT_RESULT_FIELDS) and `run`; the ones that run in a per-job runner container
also define `execute`, their in-container part. A module whose components depend on the payload defines
`required_components(payload)` (the simulation); the others need their subsystem component
(cluster/fingerprints/components.py JOB_TYPE_COMPONENTS)."""

from types import ModuleType
from typing import Any, Dict, Mapping, Tuple, Type

from pydantic import BaseModel

from scenegems_tool.cluster.fingerprints.components import JOB_TYPE_COMPONENTS, ComponentId
from scenegems_tool.cluster.protocol.artifacts import ArtifactField
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.jobs import (
    calibration_deviation_job,
    design_space_exploration_job,
    monitoring_post_hoc_job,
    scene_generation_job,
    simulation_job,
    trajectory_generation_job,
)

JOB_TYPE_MODULES: Dict[JobType, ModuleType] = {
    JobType.DESIGN_SPACE_EXPLORATION: design_space_exploration_job,
    JobType.SCENE_GENERATION: scene_generation_job,
    JobType.TRAJECTORY_GENERATION: trajectory_generation_job,
    JobType.SIMULATION: simulation_job,
    JobType.MONITORING_POST_HOC: monitoring_post_hoc_job,
    JobType.CALIBRATION_DEVIATION: calibration_deviation_job,
}


def job_type_module(job_type: JobType) -> ModuleType:
    return JOB_TYPE_MODULES[job_type]


def payload_model(job_type: JobType) -> Type[BaseModel]:
    return JOB_TYPE_MODULES[job_type].PAYLOAD_MODEL


def required_components(job_type: JobType, payload: BaseModel) -> Tuple[ComponentId, ...]:
    """The components a worker node needs for a job with this validated payload."""
    of_payload = getattr(JOB_TYPE_MODULES[job_type], "required_components", None)
    return tuple(of_payload(payload)) if of_payload is not None else (JOB_TYPE_COMPONENTS[job_type],)


def payload_components(job_type: JobType, payload: Mapping[str, Any]) -> Tuple[ComponentId, ...]:
    """The components of a payload as submitted (references checked for shape only); raises ValidationError."""
    return required_components(job_type, payload_model(job_type).model_validate(payload))


def artifact_input_fields(job_type: JobType) -> Tuple[ArtifactField, ...]:
    return JOB_TYPE_MODULES[job_type].ARTIFACT_INPUT_FIELDS


def artifact_result_fields(job_type: JobType) -> Tuple[ArtifactField, ...]:
    return JOB_TYPE_MODULES[job_type].ARTIFACT_RESULT_FIELDS
