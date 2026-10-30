"""Every job type module declares its payload model and artifact fields, and the declarations match the model."""

import pytest

from scenegems_tool.cluster.node.jobs.job_types import JOB_TYPE_MODULES, artifact_input_fields, artifact_result_fields, payload_model
from scenegems_tool.cluster.protocol.artifacts import ArtifactContent, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.model_base import ProtocolModel


@pytest.mark.parametrize("job_type", list(JobType))
def test_each_job_type_declares_a_payload_model_and_its_artifact_fields(job_type):
    model = payload_model(job_type)
    assert issubclass(model, ProtocolModel)
    for field in artifact_input_fields(job_type):
        assert field.name in model.model_fields, f"{job_type.value}: {field.name} is not a payload field"
    assert all(field.name not in model.model_fields or field.name in {f.name for f in artifact_input_fields(job_type)} for field in artifact_result_fields(job_type))


def test_the_declared_fields_are_the_contract_of_the_artifact_transport():
    declared = {job_type: ({(f.name, f.kind, f.content, f.many) for f in artifact_input_fields(job_type)}, {(f.name, f.kind) for f in artifact_result_fields(job_type)}) for job_type in JobType}
    json, text = ArtifactContent.JSON, ArtifactContent.TEXT
    assert declared == {
        JobType.SCENE_GENERATION: ({("functional_scenario_content", ArtifactKind.FUNCTIONAL_SCENARIO, text, False)}, {("evaluation_data", ArtifactKind.SCENE)}),
        JobType.TRAJECTORY_GENERATION: ({("scenario_content", ArtifactKind.SCENE, text, False)}, {("trajectory_data", ArtifactKind.TRAJECTORY_DATA)}),
        JobType.SIMULATION_KINEMATIC: ({("trajectories", ArtifactKind.TRAJECTORIES, json, False)}, {("trajectories", ArtifactKind.TRAJECTORIES)}),
        JobType.SIMULATION_ARDUPILOT_SIM: ({("trajectories", ArtifactKind.TRAJECTORIES, json, False)}, {("states", ArtifactKind.TRAJECTORIES), ("trajectories", ArtifactKind.TRAJECTORIES)}),
        JobType.SIMULATION_GAZEBO: ({("trajectories", ArtifactKind.TRAJECTORIES, json, False)}, {("states", ArtifactKind.TRAJECTORIES), ("trajectories", ArtifactKind.TRAJECTORIES)}),
        JobType.MONITORING_POST_HOC: ({("trajectories", ArtifactKind.TRAJECTORIES, json, False), ("scene", ArtifactKind.SCENE, json, False)}, {("frames", ArtifactKind.FRAMES)}),
        JobType.CALIBRATION_DEVIATION: ({("trajectories", ArtifactKind.TRAJECTORIES, json, True)}, set()),
    }


def test_payload_models_are_the_modules_own():
    for job_type, module in JOB_TYPE_MODULES.items():
        assert payload_model(job_type).__module__ == module.__name__
