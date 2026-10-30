"""The module of each job type. Every module defines its payload model (PAYLOAD_MODEL, or PAYLOAD_MODELS
by job type for a module that runs several types), its artifact fields (ARTIFACT_INPUT_FIELDS, ARTIFACT_RESULT_FIELDS) and `run`; the ones that run
in a per-job runner container also define `execute`, their in-container part."""

from types import ModuleType
from typing import Dict, Tuple, Type

from scenegems_tool.cluster.node.jobs import (
    calibration_deviation_job,
    monitoring_post_hoc_job,
    scene_generation_job,
    simulation_ardupilot_job,
    simulation_kinematic_job,
    trajectory_generation_job,
)
from scenegems_tool.cluster.protocol.artifacts import ArtifactField
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.model_base import ProtocolModel

JOB_TYPE_MODULES: Dict[JobType, ModuleType] = {
    JobType.SCENE_GENERATION: scene_generation_job,
    JobType.TRAJECTORY_GENERATION: trajectory_generation_job,
    JobType.SIMULATION_KINEMATIC: simulation_kinematic_job,
    JobType.SIMULATION_ARDUPILOT_SIM: simulation_ardupilot_job,
    JobType.SIMULATION_GAZEBO: simulation_ardupilot_job,
    JobType.MONITORING_POST_HOC: monitoring_post_hoc_job,
    JobType.CALIBRATION_DEVIATION: calibration_deviation_job,
}


def job_type_module(job_type: JobType) -> ModuleType:
    return JOB_TYPE_MODULES[job_type]


def payload_model(job_type: JobType) -> Type[ProtocolModel]:
    module = JOB_TYPE_MODULES[job_type]
    models = getattr(module, "PAYLOAD_MODELS", None)
    return models[job_type] if models is not None else module.PAYLOAD_MODEL


def artifact_input_fields(job_type: JobType) -> Tuple[ArtifactField, ...]:
    return JOB_TYPE_MODULES[job_type].ARTIFACT_INPUT_FIELDS


def artifact_result_fields(job_type: JobType) -> Tuple[ArtifactField, ...]:
    return JOB_TYPE_MODULES[job_type].ARTIFACT_RESULT_FIELDS
