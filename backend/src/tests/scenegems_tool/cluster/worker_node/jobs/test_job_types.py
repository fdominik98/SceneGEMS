"""Every job type module declares its payload model and artifact fields, and the declarations match the model."""

from typing import get_args

import pytest

from scenegems_tool.cluster.protocol.artifacts import ArtifactContent, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.cluster.worker_node.jobs.job_types import JOB_TYPE_MODULES, artifact_input_fields, artifact_result_fields, payload_components, payload_model
from scenegems_tool.cluster.worker_node.jobs.simulation_job import RunnerPayload, SimulationPayload
from tests.scenegems_tool.cluster.payloads import ardupilot_payload, valid_payload


def _models(job_type):
    """The protocol models of a job type's payload: the simulation's runner models, else the one model."""
    model = payload_model(job_type)
    return get_args(get_args(RunnerPayload)[0]) if model is SimulationPayload else (model,)


@pytest.mark.parametrize("job_type", list(JobType))
def test_each_job_type_declares_a_payload_model_and_its_artifact_fields(job_type):
    for model in _models(job_type):
        assert issubclass(model, ProtocolModel)
        for field in artifact_input_fields(job_type):
            assert field.name in model.model_fields, f"{job_type.value}: {field.name} is not a payload field"
        assert all(field.name not in model.model_fields or field.name in {f.name for f in artifact_input_fields(job_type)} for field in artifact_result_fields(job_type))


def test_the_declared_fields_are_the_contract_of_the_artifact_transport():
    declared = {job_type: ({(f.name, f.kind, f.content, f.many) for f in artifact_input_fields(job_type)}, {(f.name, f.kind) for f in artifact_result_fields(job_type)}) for job_type in JobType}
    json, text = ArtifactContent.JSON, ArtifactContent.TEXT
    assert declared == {
        JobType.DESIGN_SPACE_EXPLORATION: (set(), {("functional_scenarios", ArtifactKind.FUNCTIONAL_SCENARIO)}),
        JobType.SCENE_GENERATION: ({("functional_scenario_content", ArtifactKind.FUNCTIONAL_SCENARIO, text, False)}, {("evaluation_data", ArtifactKind.SCENE)}),
        JobType.TRAJECTORY_GENERATION: ({("scenario_content", ArtifactKind.SCENE, text, False)}, {("trajectory_data", ArtifactKind.TRAJECTORY_DATA)}),
        JobType.SIMULATION: ({("trajectories", ArtifactKind.TRAJECTORIES, json, False)}, {("states", ArtifactKind.TRAJECTORIES), ("trajectories", ArtifactKind.TRAJECTORIES)}),
        JobType.MONITORING_POST_HOC: ({("trajectories", ArtifactKind.TRAJECTORIES, json, False), ("scene", ArtifactKind.SCENE, json, False)}, {("frames", ArtifactKind.FRAMES)}),
        JobType.CALIBRATION_DEVIATION: ({("trajectories", ArtifactKind.TRAJECTORIES, json, True)}, set()),
    }


def test_payload_models_are_the_modules_own():
    for job_type, module in JOB_TYPE_MODULES.items():
        assert payload_model(job_type).__module__ == module.__name__


def test_a_job_needs_its_subsystem_component_or_its_vessels_layers():
    assert payload_components(JobType.SCENE_GENERATION, valid_payload(JobType.SCENE_GENERATION)) == ("scene_generation",)
    assert payload_components(JobType.TRAJECTORY_GENERATION, valid_payload(JobType.TRAJECTORY_GENERATION)) == ("trajectory_generation",)
    assert payload_components(JobType.MONITORING_POST_HOC, valid_payload(JobType.MONITORING_POST_HOC)) == ("monitoring",)
    assert payload_components(JobType.CALIBRATION_DEVIATION, valid_payload(JobType.CALIBRATION_DEVIATION)) == ("calibration",)
    assert payload_components(JobType.SIMULATION, valid_payload(JobType.SIMULATION)) == ("asv_system/replay", "control_layer/none", "simulation_layer/kinematic")
    assert payload_components(JobType.SIMULATION, ardupilot_payload("gazebo")) == ("asv_system/replay", "control_layer/ardupilot", "simulation_layer/gazebo")
