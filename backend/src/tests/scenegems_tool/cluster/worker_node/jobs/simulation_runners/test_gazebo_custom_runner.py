"""The gazebo_custom runner of the simulation job: the per-job Gazebo stack as compose content without Docker, and the run against a fake actuator link."""

import os
import re

import pytest

from scenegems_tool.cluster.fingerprints.components import images_of
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs.in_container.run_observation import RunObserver
from scenegems_tool.cluster.worker_node.jobs.job_payload import parse_payload
from scenegems_tool.cluster.worker_node.jobs.job_types import payload_components
from scenegems_tool.cluster.worker_node.jobs.simulation_job import SimulationPayload, execute
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.ardupilot_runner import STACK_NETWORK
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.gazebo_custom_runner import GazeboCustomSimulationPayload, build_job_stack
from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import ObservationControl
from scenegems_tool.cluster.worker_node.launchers.per_job.job_stack import RUNNER_SERVICE
from scenegems_tool.vessel_stack.simulation_layers.gazebo import gz_lockstep_runner
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_transport_actuator import DEFAULT_PORT
from tests.scenegems_tool.vessel_stack.simulation_layers.gazebo.fake_hull_link import hull_link

WIND = [0.0, 3.0, 0.0]
WAVES = {"amplitude": 0.5, "period": 5.0, "steepness": 0.0, "direction": [1.0, 0.0]}


def custom_payload(head_on_trajectories, **fields):
    return {"runner": "gazebo_custom", "trajectories": head_on_trajectories.to_dict(), **fields}


def stack_for(worker_node, make_job, head_on_trajectories, job_id="sim-1", **fields):
    payload_data = custom_payload(head_on_trajectories, **fields)
    job = make_job(JobType.SIMULATION, payload_data, job_id=job_id)
    return job, build_job_stack(job, worker_node, GazeboCustomSimulationPayload.model_validate(payload_data))


def test_usv_navigation_runs_in_its_own_image(instances_folder, worker_node, make_job, head_on_trajectories):
    _, stack = stack_for(worker_node, make_job, head_on_trajectories, mode="usv_navigation")
    services = stack.compose["services"]
    own_ship, target = services["os_asv_system"], services["ts1_asv_system"]
    assert "scenegems-usv-navigation" in own_ship["image"] and own_ship["command"][2] == "scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_server"
    assert "scenegems-simulation-subsystem" in target["image"], "the other vessel replays"


def test_the_stack_is_the_paused_world_a_controller_and_asv_system_per_vessel_and_the_runner(instances_folder, worker_node, make_job, head_on_trajectories):
    """No SITL: Gazebo starts paused with the actuator listening, every vessel has its controller and its replay container, and the runner steps them."""
    job, stack = stack_for(worker_node, make_job, head_on_trajectories)
    scope = worker_node.job_scope(job)
    services = stack.compose["services"]
    vessel_services = {f"{vessel}_{layer}" for vessel in ("os", "ts1") for layer in ("controller", "asv_system")}
    assert set(services) == {"gazebo", RUNNER_SERVICE} | vessel_services
    for name in vessel_services:
        assert services[name]["image"].endswith("scenegems-simulation-subsystem:latest}") and services[name]["networks"] == [STACK_NETWORK]
    assert services["os_controller"]["command"][-3:] == ["scenegems_tool.vessel_stack.control_layers.custom.custom_controller_server", "--port", "11420"]
    assert services["os_asv_system"]["command"][-3:] == ["scenegems_tool.vessel_stack.asv_system.replay.replay_server", "--port", "11410"]
    gazebo = services["gazebo"]
    assert gazebo["image"].endswith("scenegems-gazebo-harmonic:latest}") or "scenegems-gazebo-harmonic" in gazebo["image"]
    assert gazebo["environment"]["GZ_START_PAUSED"] == "1" and gazebo["environment"]["GZ_ACTUATOR_PORT"] == str(DEFAULT_PORT)
    assert "depends_on" not in gazebo
    for key, service in services.items():
        assert service["container_name"] == scope.container_name(key)
        assert "ports" not in service
    runner = services[RUNNER_SERVICE]
    assert runner["image"] == "scenegems-simulation-subsystem:latest"
    assert runner["networks"] == [STACK_NETWORK] and set(runner["depends_on"]) == set(services) - {RUNNER_SERVICE}
    assert stack.project.name == scope.compose_project


def test_the_world_and_the_models_go_to_the_job_folder(instances_folder, worker_node, make_job, head_on_trajectories):
    job, stack = stack_for(worker_node, make_job, head_on_trajectories)
    gen_folder = f"{worker_node.job_scope(job).folder}/gen"
    assert sorted(os.listdir(gen_folder)) == ["ocean_world.sdf", "os_model.sdf", "trajectories.json", "ts1_model.sdf"]
    assert stack.compose["services"]["gazebo"]["environment"]["WORLD_SDF"].endswith(f"{gen_folder}/ocean_world.sdf")
    model = open(f"{gen_folder}/os_model.sdf", encoding="utf-8").read()
    assert "ArduPilotPlugin" not in model


def test_the_world_gets_the_payloads_wind(instances_folder, worker_node, make_job, head_on_trajectories):
    job, _ = stack_for(worker_node, make_job, head_on_trajectories, environment={"wind_vector": WIND})
    world = open(f"{worker_node.job_scope(job).folder}/gen/ocean_world.sdf", encoding="utf-8").read()
    assert re.search(r"<wind>\s*<linear_velocity>0\.0 3\.0 0\.0</linear_velocity>", world)


def test_a_calm_world_has_no_wind(instances_folder, worker_node, make_job, head_on_trajectories):
    job, _ = stack_for(worker_node, make_job, head_on_trajectories)
    world = open(f"{worker_node.job_scope(job).folder}/gen/ocean_world.sdf", encoding="utf-8").read()
    assert re.search(r"<wind>\s*<linear_velocity>0\.0 0\.0 0\.0</linear_velocity>", world)


def test_an_unknown_own_ship_fails_for_good(instances_folder, worker_node, make_job, head_on_trajectories):
    with pytest.raises(JobFailed) as failure:
        stack_for(worker_node, make_job, head_on_trajectories, mode="usv_navigation", own_ship_id=9)
    assert not failure.value.retryable and "No vessel with id 9" in str(failure.value)


@pytest.mark.parametrize(
    "fields, components, asv_images",
    [
        ({}, ("asv_system/replay", "control_layer/custom", "simulation_layer/gazebo"), set()),
        ({"mode": "usv_navigation"}, ("asv_system/replay", "asv_system/usv_navigation", "control_layer/custom", "simulation_layer/gazebo"), {"scenegems-usv-navigation:latest"}),
    ],
)
def test_a_gazebo_worker_node_without_sitl_runs_it(head_on_trajectories, fields, components, asv_images):
    """The job needs the custom control layer and the Gazebo layer, whose images are Gazebo and the simulation subsystem image (runner, controllers, replay), plus USV Navigation's own: no SITL."""
    assert payload_components(JobType.SIMULATION, custom_payload(head_on_trajectories, **fields)) == components
    assert images_of(components) == {"scenegems-gazebo-harmonic:latest", "scenegems-simulation-subsystem:latest"} | asv_images


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"own_ship_id": 1}, "apply only to mode usv_navigation"),
        ({"dt": 0.25}, "whole number of the custom controller's 0.1 s control steps"),
        ({"dt": 0.5, "monitor": "live"}, "whole number of seconds"),
        ({"colregs_constraints_content": "x: 1"}, "applies only to monitor live"),
        ({"environment": {"wind_vector": [1.0, 0.0]}}, "wind_vector"),
    ],
)
def test_the_payload_is_checked(make_job, head_on_trajectories, fields, message):
    with pytest.raises(JobFailed) as failure:
        parse_payload(SimulationPayload, make_job(JobType.SIMULATION, custom_payload(head_on_trajectories, **fields)))
    assert message in str(failure.value) and not failure.value.retryable


@pytest.fixture
def fake_actuator(monkeypatch):
    """GzLockstepLink replaced by a FakeHullLink over the run's vessels; returns the hosts and ports the runner connected to and the links."""
    from scenegems_tool.cluster.worker_node.jobs.simulation_runners import gazebo_custom_runner
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig

    connected = {"addresses": [], "links": [], "environments": []}
    original_hull_dynamics = gz_lockstep_runner.hull_dynamics

    def recording_hull_dynamics(vessel, environment):
        connected["environments"].append(environment)
        return original_hull_dynamics(vessel, environment)

    def link(host, port):
        connected["addresses"].append((host, port))
        trajectories = gazebo_custom_runner.to_trajectories(connected["trajectories"])
        fake = hull_link(trajectories, EnvironmentConfig.calm())
        connected["links"].append(fake)
        return fake

    monkeypatch.setattr(gz_lockstep_runner, "GzLockstepLink", link)
    monkeypatch.setattr(gz_lockstep_runner, "hull_dynamics", recording_hull_dynamics)
    return connected


def _quiet(message, progress=None):
    pass


def custom_job(make_job, head_on_trajectories, fake_actuator, **fields):
    payload = custom_payload(head_on_trajectories, steps=20, **fields)
    fake_actuator["trajectories"] = payload["trajectories"]
    return make_job(JobType.SIMULATION, payload)


def test_the_runner_steps_the_world_on_the_gazebo_service(fake_actuator, make_job, head_on_trajectories):
    result = execute(custom_job(make_job, head_on_trajectories, fake_actuator), _quiet)
    assert fake_actuator["addresses"] == [("gazebo", DEFAULT_PORT)] and fake_actuator["links"][0].closed
    assert fake_actuator["links"][0].steps == 200, "20 scenario steps of ten control steps"
    assert result["steps"] == 20 and result["late_commands"] == 0
    assert result["state_digest"] == result["run_record"]["state_digest"]
    assert {"custom_controller_waypoint_follower", "gz_transport_actuator"} <= set(result["run_record"]["specs"])
    assert result["run_record"]["repeatability_tier"] == "bounded"
    assert "monitor" not in result and "trajectories" not in result


def test_the_same_payload_gives_the_same_digest(fake_actuator, make_job, head_on_trajectories):
    job = custom_job(make_job, head_on_trajectories, fake_actuator)
    assert execute(job, _quiet)["state_digest"] == execute(job, _quiet)["state_digest"]


def test_the_hull_dynamics_see_the_payloads_environment(fake_actuator, make_job, head_on_trajectories):
    """The autopilot gains come from the hull the generated world floats, so they take the same wind."""
    result = execute(custom_job(make_job, head_on_trajectories, fake_actuator, environment={"wind_vector": WIND}, seed=5), _quiet)
    # the runner's two hulls; the fake link builds its own calm hulls too
    assert sum([float(component) for component in environment.wind_vector] == WIND for environment in fake_actuator["environments"]) == 2
    assert result["run_record"]["environment"] == {"wind_vector": WIND, "waves": None, "seed": 5}


def test_waves_reach_the_run(fake_actuator, make_job, head_on_trajectories):
    result = execute(custom_job(make_job, head_on_trajectories, fake_actuator, environment={"waves": WAVES}), _quiet)
    assert result["run_record"]["environment"]["waves"] == WAVES


def test_usv_navigation_steers_the_own_ship(fake_actuator, make_job, head_on_trajectories):
    result = execute(custom_job(make_job, head_on_trajectories, fake_actuator, mode="usv_navigation"), _quiet)
    record = result["run_record"]
    assert "custom_controller_heading_speed_input" in record["specs"] and "custom_controller_waypoint_follower" in record["specs"]
    assert set(record["usv_navigation"]) == {"0"}
    assert sorted(record["participant_seeds"]) == ["replay/1", "usv_navigation/0"]


def test_usv_navigation_takes_the_named_vessel_and_its_parameters(fake_actuator, make_job, head_on_trajectories):
    usv_navigation = {"goal": [0.0, 0.0], "speed": 6.0, "safety_radius": 150.0, "control_horizon": 40.0}
    result = execute(custom_job(make_job, head_on_trajectories, fake_actuator, mode="usv_navigation", own_ship_id=1, usv_navigation=usv_navigation), _quiet)
    parameters = result["run_record"]["usv_navigation"]
    assert set(parameters) == {"1"} and parameters["1"]["goal"] == [0.0, 0.0] and parameters["1"]["v"] == 6.0 and parameters["1"]["Cs"] == 150.0


def without_wall_clock(result):
    """The result without the pace the run achieved, the only field that reads the wall clock."""
    return {**{key: value for key, value in result.items() if key != "achieved_speedup"}, "run_record": {key: value for key, value in result["run_record"].items() if key != "achieved_speedup"}}


def _observe(job, speed=10.0):
    frames, sleeps = [], []
    now = [0.0]

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds  # a fake clock: the sleeps move the time only

    class Observation:
        def observer(self, build_frame, dt, **options):
            return RunObserver(lambda: ObservationControl(active=True, speed=speed, revision=1), frames.append, build_frame, dt, sleep=sleep, clock=lambda: now[0], **options)

    return execute(job, _quiet, observation=Observation()), frames, sleeps


def test_an_observed_run_is_paced_and_unchanged(fake_actuator, make_job, head_on_trajectories):
    """The runner steps the world, so the observers' speed paces it; the frames are every step and the result is the unobserved one."""
    job = custom_job(make_job, head_on_trajectories, fake_actuator, include_trajectories=True)
    plain = execute(job, _quiet)
    observed, frames, sleeps = _observe(job)
    assert without_wall_clock(observed) == without_wall_clock(plain)
    assert sleeps, "paced to the observers' speed"
    assert [frame["timestamp"] for frame in frames] == list(range(21))
    assert frames[-1]["scenarioId"] == job.job_id and set(frames[-1]["statesByActorId"]) == {"0", "1"}


def test_the_live_monitor_judges_the_run_and_its_trajectories_hold_the_observed_states(fake_actuator, make_job, head_on_trajectories):
    from concrete_level.models.trajectories import Trajectories
    from scenegems_tool.cluster.worker_node.jobs import monitoring_post_hoc_job

    job = custom_job(make_job, head_on_trajectories, fake_actuator, monitor="live", include_trajectories=True)
    result, frames, _ = _observe(job)
    assert result["monitor"]["scenes"] == 21 and result["monitor"]["stopped_early_at"] is None
    assert frames[0]["ruleResults"] and frames[-1]["ruleResults"]
    run = Trajectories.from_dict(result["trajectories"])
    assert run.time_step == 1 and len(run.scene_list) == 21
    post_hoc = monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, {"trajectories": result["trajectories"]}), _quiet)
    summary_keys = ("scenes", "monitored_scenes", "time_step", "rules", "failed_rules", "passed")
    assert {key: result["monitor"][key] for key in summary_keys} == {key: post_hoc[key] for key in summary_keys}
