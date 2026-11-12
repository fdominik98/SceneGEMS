"""Every layer of every stack in its own container: the services each stack generates, and how its runner finds them."""

import pytest

from scenegems_tool.vessel_stack.contracts.docker_stack import DockerAsvSystem, DockerControlLayer, DockerSimulationLayer
from scenegems_tool.vessel_stack.contracts.lockstep_wire import Endpoint
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.stack_services import (
    ASV_SYSTEM_PORT,
    CONTROLLER_PORT,
    KINEMATIC_SIM_PORT,
    asv_system_endpoint,
    asv_system_service_name,
    controller_endpoint,
    controller_service_name,
    is_participant_service,
    kinematic_sim_endpoint,
    stack_agent_name,
)
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig
from scenegems_tool.vessel_stack.hosting import ContainerHosting, InProcessHosting, participant_reports
from scenegems_tool.vessel_stack.registry.catalog import default_registry, default_resolver
from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import kinematic_instance
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, mqtt_connection, stack_instance

SIMULATION = "${SIMULATION_IMAGE:-scenegems-simulation-subsystem:latest}"
USV_NAVIGATION = "${USV_NAVIGATION_IMAGE:-scenegems-usv-navigation:latest}"
SITL = "${SITL_IMAGE:-scenegems-ardupilot-sitl:latest}"
GAZEBO = "${GAZEBO_IMAGE:-scenegems-gazebo-harmonic:latest}"
TRAJECTORIES = encounter_trajectories("head_on", 20)


def services_of(instance) -> dict:
    _, compose = build_simulation_docker_stack_artifacts(instance, TRAJECTORIES, mqtt_connection(), GEOFENCE, headless=True)
    return compose["services"]


def images_of(instance) -> dict:
    return {name: service["image"] for name, service in services_of(instance).items()}


class TestEveryLayerHasItsContainer:
    """Per stack: one simulator for the scenario, and per vessel its controller and its ASV system."""

    def test_kinematic_with_replay(self):
        assert images_of(kinematic_instance(TRAJECTORIES)) == {
            "os_asv_system": SIMULATION,
            "ts1_asv_system": SIMULATION,
            "kinematic_sim": SIMULATION,
        }, "control layer none is the absence of a controller, so it has no container"

    def test_kinematic_with_usv_navigation_on_the_own_ship(self):
        assert images_of(kinematic_instance(TRAJECTORIES, {0: AsvSystemId.USV_NAVIGATION})) == {
            "os_asv_system": USV_NAVIGATION,
            "ts1_asv_system": SIMULATION,
            "kinematic_sim": SIMULATION,
        }

    def test_gazebo_with_the_custom_controller(self):
        instance = stack_instance(SimulationLayerId.GAZEBO, [0, 1], asv_system=AsvSystemId.USV_NAVIGATION, control_layer=ControlLayerId.CUSTOM)
        assert images_of(instance) == {
            "agent_0_controller": SIMULATION,
            "agent_0_asv_system": USV_NAVIGATION,
            "agent_1_controller": SIMULATION,
            "agent_1_asv_system": USV_NAVIGATION,
            "gazebo": GAZEBO,
        }

    @pytest.mark.parametrize("asv_system, asv_image", [(AsvSystemId.REPLAY, SIMULATION), (AsvSystemId.USV_NAVIGATION, USV_NAVIGATION)])
    def test_ardupilot_on_its_own_physics(self, asv_system, asv_image):
        instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0], asv_system=asv_system)
        assert images_of(instance) == {"agent_0": SITL, "agent_0_asv_system": asv_image}, "SITL is the controller and the simulator of its vessel"

    def test_ardupilot_on_gazebo(self):
        instance = stack_instance(SimulationLayerId.GAZEBO, [0])
        assert images_of(instance) == {"agent_0": SITL, "agent_0_asv_system": SIMULATION, "gazebo": GAZEBO}

    def test_through_arduagent_the_asv_system_is_arduagent_itself(self):
        instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0], adapter_ids=("replay_arduagent_follower",))
        assert set(services_of(instance)) == {"agent_0", "agent_0_mavproxy", "agent_0_arduagent"}, "no replay container next to ArduAgent"


class TestComponentServices:
    def test_a_component_listens_on_the_stack_network_only(self):
        services = services_of(kinematic_instance(TRAJECTORIES, {0: AsvSystemId.USV_NAVIGATION}))
        for service in services.values():
            assert service["networks"] == ["maritime_net"]
            assert "ports" not in service and "volumes" not in service, "the runner sends a component what it needs when it starts it"
        assert services["kinematic_sim"]["command"] == ["python", "-m", "scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_sim_server", "--port", str(KINEMATIC_SIM_PORT)]
        assert services["ts1_asv_system"]["command"] == ["python", "-m", "scenegems_tool.vessel_stack.asv_system.replay.replay_server", "--port", str(ASV_SYSTEM_PORT)]
        assert services["os_asv_system"]["command"] == ["python", "-m", "scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_server", "--port", str(ASV_SYSTEM_PORT)]

    def test_the_runner_finds_each_component_by_its_service_name(self):
        assert asv_system_endpoint("agent_3") == Endpoint(asv_system_service_name("agent_3"), ASV_SYSTEM_PORT) == Endpoint("agent_3_asv_system", 11410)
        assert controller_endpoint("agent_3") == Endpoint(controller_service_name("agent_3"), CONTROLLER_PORT) == Endpoint("agent_3_controller", 11420)
        assert kinematic_sim_endpoint() == Endpoint("kinematic_sim", 11430)

    def test_a_vessel_without_an_agent_connection_is_named_by_its_id(self):
        assert stack_agent_name(kinematic_instance(TRAJECTORIES).vessels["1"]) == "ts1"
        assert stack_agent_name(stack_instance(SimulationLayerId.GAZEBO, [1]).vessels["1"]) == "agent_1"

    def test_participant_services_are_told_from_the_others(self):
        assert is_participant_service("agent_0_asv_system") and is_participant_service("agent_0_controller")
        assert not any(is_participant_service(name) for name in ("agent_0", "asv_0", "gazebo", "kinematic_sim", "agent_0_mavproxy", "agent_0_arduagent"))


class TestRegistryBindings:
    def test_every_layer_and_lockstep_adapter_that_runs_in_a_container_has_its_contributor(self):
        registry = default_registry()
        kinds = {
            "simulation_layer/kinematic": DockerSimulationLayer,
            "simulation_layer/gazebo": DockerSimulationLayer,
            "simulation_layer/ardupilot_sim": DockerSimulationLayer,
            "control_layer/ardupilot": DockerControlLayer,
            "control_layer/custom": DockerControlLayer,
            "replay_state_follower": DockerAsvSystem,
            "replay_mavlink_lockstep": DockerAsvSystem,
            "custom_controller_waypoint_follower": DockerAsvSystem,
            "usv_navigation_in_process": DockerAsvSystem,
            "usv_navigation_mavlink_lockstep": DockerAsvSystem,
            "custom_controller_heading_speed_input": DockerAsvSystem,
        }
        for spec_id, kind in kinds.items():
            assert isinstance(registry.docker(spec_id)(), kind), spec_id

    @pytest.mark.parametrize("spec_id", ["control_layer/none", "replay_arduagent_follower", "mission_planner_gcs_port", "kinematic_command_input"])
    def test_a_spec_that_brings_no_container_has_none(self, spec_id):
        assert default_registry().docker(spec_id) is None

    def test_the_container_specs_name_what_the_services_run(self):
        resolver = default_resolver()
        chain = resolver.resolve(VesselStackConfig(AsvSystemId.USV_NAVIGATION, ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO))
        images = {container.image for spec in chain.specs for container in spec.containers}
        assert images == {USV_NAVIGATION, SIMULATION, GAZEBO}
        usv_navigation = chain.specs[0].containers[0]
        assert usv_navigation.build_fingerprint_sources == (
            "deploy/images/usv_navigation",
            "backend/src/scenegems_tool/vessel_stack/asv_system/usv_navigation/usv_navigation_server.py",
            "backend/src/scenegems_tool/vessel_stack/contracts/lockstep_wire.py",
        ), "the image copies exactly these two source files"


class TestHosting:
    def test_in_process_hosting_builds_the_layers_in_the_callers_process(self):
        from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_simulation import KinematicSimulation

        hosting = InProcessHosting()
        simulation = hosting.kinematic_simulation(TRAJECTORIES.initial_scene, 1.0, ["replay/0"])
        assert isinstance(simulation, KinematicSimulation) and simulation.clock.participant_ids == ("replay/0",)
        hosting.close()

    def test_container_hosting_closes_what_it_opened_even_after_a_failed_connect(self):
        from scenegems_tool.vessel_stack.contracts.lockstep_wire import WireError

        hosting = ContainerHosting({"kinematic_sim": Endpoint("127.0.0.1", 1)}, connect_timeout_s=0.2)
        with pytest.raises(WireError):
            hosting.kinematic_simulation(TRAJECTORIES.initial_scene, 1.0, [])
        assert len(hosting._links) == 1
        hosting.close()
        assert hosting._links == []

    def test_reports_are_collected_from_the_software_that_has_one(self):
        class Reporting:
            def report(self):
                return {"goal_reached_at": 12.0}

        class Silent:
            def report(self):
                return {}

        assert participant_reports({2: Reporting(), 1: Silent(), 0: object()}) == {2: {"goal_reached_at": 12.0}}
