import pytest

from scenegems_tool.cluster.fingerprints.components import (
    CALIBRATION,
    COMPONENTS,
    JOB_TYPE_COMPONENTS,
    MONITORING,
    MONITORING_IMAGE,
    RUNNER_STACKS,
    SCENE_GENERATION,
    SCENE_GENERATION_IMAGE,
    SIMULATION_IMAGE,
    STACK_COMPONENTS,
    TRAJECTORY_GENERATION,
    TRAJECTORY_GENERATION_IMAGE,
    JobStackError,
    SimulationRunner,
    UnknownComponent,
    check_runner_stacks,
    component_images,
    images_of,
    job_type_of,
    layer_component,
    ordered,
    runner_of_stack,
    stack_components,
    stack_images,
    unrun_campaign_stacks,
)
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.subsystem import Subsystem, subsystem_image
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from tests.scenegems_tool.cluster.stack_images import GAZEBO_IMAGE, SITL_IMAGE

MAVPROXY_IMAGE = "scenegems-mavproxy:latest"
ARDUAGENT_IMAGE = "scenegems-arduagent:latest"
USV_NAVIGATION_IMAGE = "scenegems-usv-navigation:latest"


def _stack(asv_system: AsvSystemId, control_layer: ControlLayerId, simulation_layer: SimulationLayerId) -> VesselStackConfig:
    return VesselStackConfig(asv_system=asv_system, control_layer=control_layer, simulation_layer=simulation_layer)


def _campaign_stacks():
    return [chain.stack for chain in default_resolver().availability_matrix() if chain.available and not chain.capabilities.interactive_only]


def test_the_catalog_lists_the_campaign_layers_and_the_subsystems():
    assert COMPONENTS == (
        "asv_system/replay",
        "asv_system/usv_navigation",
        "asv_system/mission_planner",
        "control_layer/none",
        "control_layer/ardupilot",
        "control_layer/custom",
        "simulation_layer/kinematic",
        "simulation_layer/ardupilot_sim",
        "simulation_layer/gazebo",
        "design_space_exploration",
        "scene_generation",
        "trajectory_generation",
        "monitoring",
        "calibration",
    )
    assert set(component_images()) == set(COMPONENTS)
    assert layer_component(ControlLayerId.ARDUPILOT) == "control_layer/ardupilot"


def test_every_layer_of_every_campaign_stack_is_a_component():
    for stack in _campaign_stacks():
        assert set(stack_components([(stack.asv_system, stack.control_layer, stack.simulation_layer)])) <= set(STACK_COMPONENTS), stack


def test_every_campaign_stacks_images_are_the_union_of_its_three_components_images():
    for stack in _campaign_stacks():
        triple = (stack.asv_system, stack.control_layer, stack.simulation_layer)
        assert images_of(stack_components([triple])) == {SIMULATION_IMAGE} | set(stack_images([triple])), stack


def test_the_layer_images_come_from_the_container_specs():
    images = component_images()
    assert images["control_layer/ardupilot"] == (SITL_IMAGE,)
    assert images["simulation_layer/gazebo"] == tuple(sorted((GAZEBO_IMAGE, SIMULATION_IMAGE)))
    assert images["simulation_layer/kinematic"] == images["simulation_layer/ardupilot_sim"] == (SIMULATION_IMAGE,), "a simulation layer adds the runner"
    assert images["asv_system/replay"] == images["control_layer/custom"] == (SIMULATION_IMAGE,), "the replay and custom controller containers start from the simulation subsystem image"
    assert images["asv_system/usv_navigation"] == (USV_NAVIGATION_IMAGE,), "USV Navigation has an image of its own"
    assert images["control_layer/none"] == (), "no controller, no container"
    assert images["asv_system/mission_planner"] == (MAVPROXY_IMAGE,), "the ground control station reaches the vessel through MAVProxy"
    unattended = [component for component in COMPONENTS if component != "asv_system/mission_planner"]
    assert not {MAVPROXY_IMAGE, ARDUAGENT_IMAGE} & images_of(unattended), "the lockstep replay on ArduPilot needs neither"
    assert ARDUAGENT_IMAGE not in images_of(COMPONENTS), "ArduAgent drives real vessels, which no job runs yet"


def test_the_subsystem_components_and_their_job_types():
    images = component_images()
    assert (images[SCENE_GENERATION], images[TRAJECTORY_GENERATION], images[MONITORING], images[CALIBRATION]) == (
        (SCENE_GENERATION_IMAGE,),
        (TRAJECTORY_GENERATION_IMAGE,),
        (MONITORING_IMAGE,),
        (SIMULATION_IMAGE,),
    )
    assert set(JOB_TYPE_COMPONENTS) == set(JobType) - {JobType.SIMULATION}, "every job type but the simulation has its subsystem component"
    assert [job_type_of(component) for component in (SCENE_GENERATION, MONITORING, "control_layer/ardupilot")] == [JobType.SCENE_GENERATION, JobType.MONITORING_POST_HOC, JobType.SIMULATION]
    with pytest.raises(UnknownComponent):
        job_type_of("gpu")


def test_the_subsystem_images_are_the_ones_the_worker_node_launches(monkeypatch):
    for variable in ("SCENE_GENERATION_IMAGE", "TRAJECTORY_GENERATION_IMAGE", "MONITORING_IMAGE", "SIMULATION_IMAGE"):
        monkeypatch.delenv(variable, raising=False)
    assert subsystem_image(Subsystem.SCENE_GENERATION) == SCENE_GENERATION_IMAGE
    assert subsystem_image(Subsystem.TRAJECTORY_GENERATION) == TRAJECTORY_GENERATION_IMAGE
    assert subsystem_image(Subsystem.MONITORING) == MONITORING_IMAGE
    assert subsystem_image(Subsystem.SIMULATION) == SIMULATION_IMAGE


def test_components_come_in_catalog_order_and_unknown_ones_fail():
    assert ordered(["monitoring", "simulation_layer/gazebo", "asv_system/replay", "monitoring"]) == ("asv_system/replay", "simulation_layer/gazebo", "monitoring")
    with pytest.raises(UnknownComponent, match="gpu"):
        ordered(["gpu"])
    assert images_of(["gpu"]) == set(), "a component the catalog does not list needs no image"


def test_the_runners_run_campaign_stacks_only():
    check_runner_stacks()
    assert {runner.value for runner in RUNNER_STACKS} == {"kinematic", "ardupilot", "gazebo_custom"}
    with pytest.raises(JobStackError, match="not available in the vessel stack matrix: no adapter from control_layer/ardupilot to simulation_layer/kinematic"):
        stack_images([(AsvSystemId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.KINEMATIC)])
    with pytest.raises(JobStackError, match="workbench only"):
        stack_images([(AsvSystemId.MISSION_PLANNER, ControlLayerId.ARDUPILOT, SimulationLayerId.GAZEBO)])


def test_the_runner_of_a_stack():
    assert runner_of_stack(_stack(AsvSystemId.USV_NAVIGATION, ControlLayerId.NONE, SimulationLayerId.KINEMATIC)) == SimulationRunner.KINEMATIC
    assert runner_of_stack(_stack(AsvSystemId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.GAZEBO)) == SimulationRunner.ARDUPILOT
    assert runner_of_stack(_stack(AsvSystemId.USV_NAVIGATION, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM)) == SimulationRunner.ARDUPILOT
    assert runner_of_stack(_stack(AsvSystemId.REPLAY, ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO)) == SimulationRunner.GAZEBO_CUSTOM
    assert runner_of_stack(_stack(AsvSystemId.USV_NAVIGATION, ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO)) == SimulationRunner.GAZEBO_CUSTOM
    assert runner_of_stack(_stack(AsvSystemId.MISSION_PLANNER, ControlLayerId.ARDUPILOT, SimulationLayerId.GAZEBO)) is None


def test_every_campaign_stack_has_a_runner():
    assert unrun_campaign_stacks() == ()


def test_the_custom_controller_needs_no_sitl():
    """A worker node with the Gazebo layer and the custom control layer, and no SITL, runs every stack of the gazebo_custom runner."""
    components = stack_components(RUNNER_STACKS[SimulationRunner.GAZEBO_CUSTOM])
    assert components == ("asv_system/replay", "asv_system/usv_navigation", "control_layer/custom", "simulation_layer/gazebo")
    assert images_of(components) == {GAZEBO_IMAGE, SIMULATION_IMAGE, USV_NAVIGATION_IMAGE}
    assert SITL_IMAGE not in images_of(components)
