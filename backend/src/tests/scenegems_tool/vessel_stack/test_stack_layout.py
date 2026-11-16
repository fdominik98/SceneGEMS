"""Every layer of every stack in its own container: the services each stack generates, and how its runner finds them."""

import pytest

from scenegems_tool.vessel_stack.contracts.docker_stack import DockerAsvSystem, DockerControlLayer, DockerSimulationLayer
from scenegems_tool.vessel_stack.contracts.lockstep_wire import Endpoint
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.stack_services import (
    KINEMATIC_SIM_PORT,
    asv_system_endpoint,
    asv_system_port,
    asv_system_service_name,
    controller_endpoint,
    controller_port,
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
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, make_vessel, mqtt_connection, stack_instance

SIMULATION = "${SIMULATION_IMAGE:-scenegems-simulation-subsystem:latest}"
USV_NAVIGATION = "${USV_NAVIGATION_IMAGE:-scenegems-usv-navigation:latest}"
MOOS_IVP = "${MOOS_IVP_IMAGE:-scenegems-moos-ivp:latest}"
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
            "os-asv-system": SIMULATION,
            "ts1-asv-system": SIMULATION,
            "kinematic-sim": SIMULATION,
        }, "control layer none is the absence of a controller, so it has no container"

    def test_kinematic_with_usv_navigation_on_the_own_ship(self):
        assert images_of(kinematic_instance(TRAJECTORIES, {0: AsvSystemId.USV_NAVIGATION})) == {
            "os-asv-system": USV_NAVIGATION,
            "ts1-asv-system": SIMULATION,
            "kinematic-sim": SIMULATION,
        }

    def test_kinematic_with_moos_ivp_on_the_own_ship(self):
        services = services_of(kinematic_instance(TRAJECTORIES, {0: AsvSystemId.MOOS_IVP}))
        assert {name: service["image"] for name, service in services.items()} == {
            "os-asv-system": MOOS_IVP,
            "ts1-asv-system": SIMULATION,
            "kinematic-sim": SIMULATION,
        }
        assert services["os-asv-system"]["command"] == ["python3", "-m", "scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_server", "--port", "12000", "--moosdb-port", "12400"]

    def test_gazebo_with_the_custom_controller(self):
        instance = stack_instance(SimulationLayerId.GAZEBO, [0, 1], asv_system=AsvSystemId.USV_NAVIGATION, control_layer=ControlLayerId.CUSTOM)
        assert images_of(instance) == {
            "agent_0-controller": SIMULATION,
            "agent_0-asv-system": USV_NAVIGATION,
            "agent_1-controller": SIMULATION,
            "agent_1-asv-system": USV_NAVIGATION,
            "gazebo": GAZEBO,
        }

    @pytest.mark.parametrize("asv_system, asv_image", [(AsvSystemId.REPLAY, SIMULATION), (AsvSystemId.USV_NAVIGATION, USV_NAVIGATION)])
    def test_ardupilot_on_its_own_physics(self, asv_system, asv_image):
        instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0], asv_system=asv_system)
        assert images_of(instance) == {"agent_0": SITL, "agent_0-asv-system": asv_image}, "SITL is the controller and the simulator of its vessel"

    def test_ardupilot_on_gazebo(self):
        instance = stack_instance(SimulationLayerId.GAZEBO, [0])
        assert images_of(instance) == {"agent_0": SITL, "agent_0-asv-system": SIMULATION, "gazebo": GAZEBO}

    def test_through_arduagent_the_asv_system_is_arduagent_itself(self):
        instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0], adapter_ids=("replay_arduagent_follower",))
        assert set(services_of(instance)) == {"agent_0", "agent_0-mavproxy", "agent_0-arduagent"}, "no replay container next to ArduAgent"


class TestComponentServices:
    def test_a_component_listens_on_the_stack_network_only(self):
        services = services_of(kinematic_instance(TRAJECTORIES, {0: AsvSystemId.USV_NAVIGATION}))
        for service in services.values():
            assert service["networks"] == ["maritime_net"]
            assert "ports" not in service and "volumes" not in service, "the runner sends a component what it needs when it starts it"
        assert services["kinematic-sim"]["command"] == ["python", "-m", "scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_sim_server", "--port", str(KINEMATIC_SIM_PORT)]
        assert services["ts1-asv-system"]["command"] == ["python", "-m", "scenegems_tool.vessel_stack.asv_system.replay.replay_server", "--port", str(asv_system_port(1))]
        assert services["os-asv-system"]["command"] == ["python", "-m", "scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_server", "--port", str(asv_system_port(0))]

    def test_the_runner_finds_each_component_by_its_service_name(self):
        assert asv_system_endpoint("agent_3", 3) == Endpoint(asv_system_service_name("agent_3"), asv_system_port(3)) == Endpoint("agent_3-asv-system", 12003)
        assert controller_endpoint("agent_3", 3) == Endpoint(controller_service_name("agent_3"), controller_port(3)) == Endpoint("agent_3-controller", 12103)
        assert kinematic_sim_endpoint() == Endpoint("kinematic-sim", 11430)

    def test_a_vessel_without_an_agent_connection_is_named_by_its_id(self):
        assert stack_agent_name(kinematic_instance(TRAJECTORIES).vessels["1"]) == "ts1"
        assert stack_agent_name(stack_instance(SimulationLayerId.GAZEBO, [1]).vessels["1"]) == "agent_1"

    def test_participant_services_are_told_from_the_others(self):
        assert is_participant_service("agent_0-asv-system") and is_participant_service("agent_0-controller")
        assert not any(is_participant_service(name) for name in ("agent_0", "asv_0", "gazebo", "kinematic-sim", "agent_0-mavproxy", "agent_0-arduagent"))


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
            "moos_ivp_heading_speed": DockerAsvSystem,
            "moos_ivp_custom_controller_input": DockerAsvSystem,
            "moos_ivp_mavlink_lockstep": DockerAsvSystem,
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

    def test_the_moos_ivp_image_is_stamped_by_its_folder_the_pinned_fork_and_the_two_files_it_copies(self):
        chain = default_resolver().resolve(VesselStackConfig(AsvSystemId.MOOS_IVP, ControlLayerId.NONE, SimulationLayerId.KINEMATIC))
        (moos_ivp,) = chain.specs[0].containers
        assert moos_ivp.image == MOOS_IVP
        assert moos_ivp.build_fingerprint_sources == (
            "deploy/images/moos_ivp",
            "deploy/images/upstream_pins.env",
            "backend/src/scenegems_tool/vessel_stack/asv_system/moos_ivp/moos_ivp_server.py",
            "backend/src/scenegems_tool/vessel_stack/contracts/lockstep_wire.py",
        )


class TestHosting:
    def test_in_process_hosting_builds_the_layers_in_the_callers_process(self):
        from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_simulation import KinematicSimulation

        hosting = InProcessHosting()
        simulation = hosting.kinematic_simulation(TRAJECTORIES.initial_scene, 1.0, ["replay/0"])
        assert isinstance(simulation, KinematicSimulation) and simulation.clock.participant_ids == ("replay/0",)
        hosting.close()

    def test_container_hosting_closes_what_it_opened_even_after_a_failed_connect(self):
        from scenegems_tool.vessel_stack.contracts.lockstep_wire import WireError

        hosting = ContainerHosting({"kinematic-sim": Endpoint("127.0.0.1", 1)}, connect_timeout_s=0.2)
        with pytest.raises(WireError):
            hosting.kinematic_simulation(TRAJECTORIES.initial_scene, 1.0, [])
        assert len(hosting._links) == 1
        hosting.close()
        assert hosting._links == []

    def test_container_hosting_reaches_each_vessels_components_on_the_ports_of_that_vessel(self):
        from scenegems_tool.vessel_stack.asv_system.asv_system_runtime import ParticipantRequest

        hosting = ContainerHosting()
        hosting._connected = lambda link: link  # the links are made, not connected
        adapter = default_registry().adapter("custom_controller_waypoint_follower")
        for vessel_id in (0, 1):
            request = ParticipantRequest(make_vessel(vessel_id, vessel_id == 0), f"agent_{vessel_id}", AsvSystemId.REPLAY, adapter, TRAJECTORIES, 1.0)
            participant, controller = hosting.custom_control(request, None)
            assert controller._client.endpoint == controller_endpoint(f"agent_{vessel_id}", vessel_id) == Endpoint(f"agent_{vessel_id}-controller", controller_port(vessel_id))
            assert hosting.asv_system(request)._client.endpoint == asv_system_endpoint(f"agent_{vessel_id}", vessel_id)
        assert Endpoint("agent_1-controller", 12101) == controller_endpoint("agent_1", 1) and Endpoint("agent_1-asv-system", 12001) == asv_system_endpoint("agent_1", 1)

    def test_reports_are_collected_from_the_software_that_has_one(self):
        class Reporting:
            def report(self):
                return {"goal_reached_at": 12.0}

        class Silent:
            def report(self):
                return {}

        assert participant_reports({2: Reporting(), 1: Silent(), 0: object()}) == {2: {"goal_reached_at": 12.0}}
