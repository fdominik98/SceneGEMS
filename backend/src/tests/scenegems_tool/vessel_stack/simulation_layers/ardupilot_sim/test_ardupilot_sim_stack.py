"""Key properties of the generated ArduPilot Sim stack (the full output is pinned by the snapshots of test_simulation_docker_stack)."""

import pytest

from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, SimulationLayerId
from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, mqtt_connection, stack_instance
from tests.scenegems_tool.vessel_stack.sdf import parse_params, parse_sdf, plugins


def test_there_is_no_simulator_service(ardupilot_sim_stack):
    assert list(ardupilot_sim_stack.compose["services"]) == ["agent_0", "agent_0_asv_system", "agent_1", "agent_1_asv_system"], "SITL and the replay container of each vessel"
    assert "gazebo" not in ardupilot_sim_stack.compose["services"]


def test_sitl_runs_its_internal_physics(ardupilot_sim_stack):
    for name in ("agent_0", "agent_1"):
        environment = ardupilot_sim_stack.compose["services"][name]["environment"]
        assert "SITL_SIMULATOR=ardupilot" in environment
        assert not [entry for entry in environment if entry.startswith("SITL_MODEL=") or entry.startswith("SITL_RESOLVE_HOST=")]


def test_speedup_reaches_sitl(ardupilot_sim_stack):
    for name in ("agent_0", "agent_1"):
        assert "SITL_SPEEDUP=5" in ardupilot_sim_stack.compose["services"][name]["environment"]


def test_each_sitl_is_homed_at_its_vessel_start_pose(ardupilot_sim_stack):
    first = ardupilot_sim_stack.compose["services"]["agent_0"]["environment"]
    second = ardupilot_sim_stack.compose["services"]["agent_1"]["environment"]
    first_home = next(entry for entry in first if entry.startswith("SITL_CUSTOM_LOCATION=")).split("=")[1].split(",")
    second_home = next(entry for entry in second if entry.startswith("SITL_CUSTOM_LOCATION=")).split("=")[1].split(",")
    assert (float(first_home[0]), float(first_home[1])) == pytest.approx((57.757128, 16.673189))
    assert float(first_home[3]) == pytest.approx(90.0), "heading east is 90 degrees in true north"
    assert float(second_home[3]) == pytest.approx(270.0), "the target heads west"
    assert float(second_home[1]) > float(first_home[1]), "the target starts 6 km east"


def test_the_unused_gazebo_files_are_still_written(ardupilot_sim_stack):
    # Kept for byte identity with the stack before the adapter framework (design doc 11.6, item 2).
    assert {"ocean_world.sdf", "agent_0_model.sdf", "agent_1_model.sdf"} <= set(ardupilot_sim_stack.files)
    assert parse_sdf(ardupilot_sim_stack.files["agent_0_model.sdf"]).find("model").get("name") == "agent_0"
    assert plugins(parse_sdf(ardupilot_sim_stack.files["agent_0_model.sdf"]), "ArduPilotPlugin")


def test_calm_environment_leaves_the_wind_and_waves_parameters_at_zero(ardupilot_sim_stack):
    params = parse_params(ardupilot_sim_stack.files["params-agent_0.params"])
    assert params["SIM_WIND_SPD"] == 0
    assert params["SIM_WAVE_ENABLE"] == 0


def test_workbench_stack_has_sitl_mavproxy_and_arduagent_per_autonomous_vessel(arduagent_stack):
    services = arduagent_stack.compose["services"]
    assert list(services) == ["agent_0", "agent_0_mavproxy", "agent_0_arduagent", "agent_1", "agent_1_mavproxy", "agent_1_arduagent"]


def test_arduagent_depends_on_its_mavproxy_and_mavproxy_reaches_its_sitl(arduagent_stack):
    services = arduagent_stack.compose["services"]
    assert services["agent_0_arduagent"]["depends_on"] == ["agent_0_mavproxy"]
    assert "--master=tcp:agent_0:5760" in services["agent_0_mavproxy"]["command"]
    assert "--master=tcp:agent_1:5770" in services["agent_1_mavproxy"]["command"], "the SITL port is 5760 + 10 * vessel id"


def test_the_ground_control_port_of_each_vessel_is_forwarded(arduagent_stack):
    services = arduagent_stack.compose["services"]
    assert "GCS_1=udp:host.docker.internal:14550" in services["agent_0_mavproxy"]["environment"]
    assert "GCS_1=udp:host.docker.internal:14560" in services["agent_1_mavproxy"]["environment"]


def test_agent_environment_carries_the_broker_and_credentials(arduagent_stack):
    environment = arduagent_stack.compose["services"]["agent_0_arduagent"]["environment"]
    assert "BROKER=broker" in environment
    assert "PORT=1883" in environment
    assert "MQTT_USER=user" in environment
    assert "TLS_CERTIFICE=0" in environment


class TestMissionPlannerGroundStation:
    """mission_planner_gcs_port: SITL plus a MAVProxy whose ground station endpoint Docker publishes; no ArduAgent."""

    @pytest.fixture(scope="class")
    def services(self):
        instance = stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], asv_system=AsvSystemId.MISSION_PLANNER)
        _, compose = build_simulation_docker_stack_artifacts(instance, encounter_trajectories("head_on", 60), mqtt_connection(), GEOFENCE)
        return compose["services"]

    def test_each_vessel_has_sitl_and_mavproxy_only(self, services):
        assert sorted(services) == ["agent_0", "agent_0_mavproxy", "agent_1", "agent_1_mavproxy"]

    def test_mavproxy_takes_serial1_and_leaves_serial0_to_the_runner(self, services):
        assert "--master=tcp:agent_1:5772" in services["agent_1_mavproxy"]["command"][-1]

    def test_the_ground_station_endpoint_is_published_on_a_port_docker_assigns(self, services):
        assert "--out=tcpin:0.0.0.0:5770" in services["agent_0_mavproxy"]["command"][-1]
        assert services["agent_0_mavproxy"]["ports"] == ["5770"]

    def test_mavproxy_restarts_inside_its_container_so_the_published_port_stays(self, services):
        """Docker gives a restarted container a new host port; MAVProxy exits until SITL has booted."""
        shell, flag, loop = services["agent_0_mavproxy"]["command"]
        assert (shell, flag) == ("sh", "-c")
        assert loop.startswith("while true; do python3 -m MAVProxy.mavproxy --non-interactive ")
        assert loop.endswith("; sleep 2; done")
