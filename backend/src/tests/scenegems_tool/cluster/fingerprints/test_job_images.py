import pytest

from scenegems_tool.cluster.fingerprints.job_images import (
    BASE_JOB_TYPE_IMAGES,
    MONITORING_IMAGE,
    SCENARIO_EXECUTION_IMAGE,
    SCENE_GENERATION_IMAGE,
    SIMULATION_JOB_STACKS,
    TRAJECTORY_GENERATION_IMAGE,
    JobStackError,
    capability_images,
    job_images,
    job_type_images,
    job_types_of_stack,
    stack_images,
    unrun_campaign_stacks,
)
from scenegems_tool.cluster.node.subsystem import Subsystem, subsystem_image
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from tests.scenegems_tool.cluster.stack_images import GAZEBO_IMAGE, SITL_IMAGE

MAVPROXY_IMAGE = "scenegems-mavproxy:latest"
ARDUAGENT_IMAGE = "scenegems-arduagent:latest"


def _stack(asv_software: AsvSoftwareId, control_layer: ControlLayerId, simulation_layer: SimulationLayerId) -> VesselStackConfig:
    return VesselStackConfig(asv_software=asv_software, control_layer=control_layer, simulation_layer=simulation_layer)


def test_every_job_type_has_its_images():
    assert set(BASE_JOB_TYPE_IMAGES) == set(JobType) and set(job_type_images()) == set(JobType)
    assert set(SIMULATION_JOB_STACKS) == {JobType.SIMULATION_KINEMATIC, JobType.SIMULATION_ARDUPILOT_SIM, JobType.SIMULATION_GAZEBO}


def test_the_subsystem_images_are_the_ones_the_node_launches(monkeypatch):
    for variable in ("SCENE_GENERATION_IMAGE", "TRAJECTORY_GENERATION_IMAGE", "MONITORING_IMAGE", "SCENARIO_EXECUTION_IMAGE"):
        monkeypatch.delenv(variable, raising=False)
    assert subsystem_image(Subsystem.SCENE_GENERATION) == SCENE_GENERATION_IMAGE
    assert subsystem_image(Subsystem.TRAJECTORY_GENERATION) == TRAJECTORY_GENERATION_IMAGE
    assert subsystem_image(Subsystem.MONITORING) == MONITORING_IMAGE
    assert subsystem_image(Subsystem.SCENARIO_EXECUTION) == SCENARIO_EXECUTION_IMAGE


def test_the_simulation_job_types_take_their_images_from_the_stacks_they_run():
    assert job_images(JobType.SIMULATION_KINEMATIC) == (SCENARIO_EXECUTION_IMAGE,)
    assert job_images(JobType.SIMULATION_ARDUPILOT_SIM) == (SCENARIO_EXECUTION_IMAGE, SITL_IMAGE)
    assert job_images(JobType.SIMULATION_GAZEBO) == (SCENARIO_EXECUTION_IMAGE, SITL_IMAGE, GAZEBO_IMAGE)
    for job_type, stacks in SIMULATION_JOB_STACKS.items():
        containers = {container.default_image for triple in stacks for spec in default_resolver().resolve(_stack(*triple)).specs for container in spec.containers}
        assert set(job_images(job_type)) == {SCENARIO_EXECUTION_IMAGE} | containers


def test_the_lockstep_replay_on_ardupilot_needs_neither_mavproxy_nor_arduagent():
    for job_type in (JobType.SIMULATION_ARDUPILOT_SIM, JobType.SIMULATION_GAZEBO):
        assert not {MAVPROXY_IMAGE, ARDUAGENT_IMAGE} & set(job_images(job_type))


def test_a_stack_the_matrix_does_not_offer_for_campaigns_fails():
    with pytest.raises(JobStackError, match="not available in the vessel stack matrix: no adapter from control_layer/ardupilot to simulation_layer/kinematic"):
        stack_images([(AsvSoftwareId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.KINEMATIC)])
    with pytest.raises(JobStackError, match="workbench only"):
        stack_images([(AsvSoftwareId.MISSION_PLANNER, ControlLayerId.ARDUPILOT, SimulationLayerId.GAZEBO)])
    assert stack_images([(AsvSoftwareId.REPLAY, ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO)]) == (GAZEBO_IMAGE,)


def test_the_job_types_of_a_stack():
    assert job_types_of_stack(_stack(AsvSoftwareId.USV_NAVIGATION, ControlLayerId.NONE, SimulationLayerId.KINEMATIC)) == (JobType.SIMULATION_KINEMATIC,)
    assert job_types_of_stack(_stack(AsvSoftwareId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.GAZEBO)) == (JobType.SIMULATION_GAZEBO,)
    assert job_types_of_stack(_stack(AsvSoftwareId.REPLAY, ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO)) == ()


def test_the_campaign_stacks_no_job_runs():
    assert set(unrun_campaign_stacks()) == {
        _stack(AsvSoftwareId.REPLAY, ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO),
        _stack(AsvSoftwareId.USV_NAVIGATION, ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO),
        _stack(AsvSoftwareId.USV_NAVIGATION, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM),
        _stack(AsvSoftwareId.USV_NAVIGATION, ControlLayerId.ARDUPILOT, SimulationLayerId.GAZEBO),
    }


def test_a_calibration_job_runs_in_the_scenario_execution_image():
    assert job_images(JobType.CALIBRATION_DEVIATION) == (SCENARIO_EXECUTION_IMAGE,)


def test_capability_images():
    assert capability_images([JobType.SIMULATION_KINEMATIC, JobType.MONITORING_POST_HOC]) == {SCENARIO_EXECUTION_IMAGE, MONITORING_IMAGE}
    assert capability_images([JobType.SIMULATION_ARDUPILOT_SIM]) == {SCENARIO_EXECUTION_IMAGE, SITL_IMAGE}
    assert GAZEBO_IMAGE in capability_images([JobType.SIMULATION_GAZEBO])
    assert capability_images([]) == set()
