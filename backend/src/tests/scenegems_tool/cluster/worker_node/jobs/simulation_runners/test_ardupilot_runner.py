"""The ardupilot runner of the simulation job: the generated per-job stack, checked as compose content without Docker, and the run with a fake SITL."""

import os

import pytest

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs.in_container.run_observation import RunObserver
from scenegems_tool.cluster.worker_node.jobs.job_payload import parse_payload
from scenegems_tool.cluster.worker_node.jobs.simulation_job import SimulationPayload, execute
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.ardupilot_runner import STACK_NETWORK, ArduPilotSimulationPayload, build_job_stack
from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import ObservationControl
from scenegems_tool.cluster.worker_node.launchers.per_job.job_stack import RUNNER_SERVICE, project_compose
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_link import StampedState
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_lockstep_runner import MavlinkRunResult
from utils.file_system_utils import RUNTIME_ASSETS_VOLUME

GEOFENCE = {"latitude": 57.7, "longitude": 11.9, "radius_meters": 2000.0}


def stack_for(layer, worker_node, make_job, head_on_trajectories, job_id="sim-1"):
    payload_data = {"runner": "ardupilot", "simulation_layer": layer, "trajectories": head_on_trajectories.to_dict(), "geofence": GEOFENCE}
    job = make_job(JobType.SIMULATION, payload_data, job_id=job_id)
    return job, build_job_stack(job, worker_node, ArduPilotSimulationPayload.model_validate(payload_data))


@pytest.mark.parametrize("layer", ["ardupilot_sim", "gazebo"])
def test_stack_is_scoped_to_the_job(instances_folder, worker_node, make_job, head_on_trajectories, layer):
    job, stack = stack_for(layer, worker_node, make_job, head_on_trajectories)
    scope = worker_node.job_scope(job)
    services = stack.compose["services"]
    vessel_services = [key for key in services if key.startswith(("os", "ts"))]
    assert sorted(vessel_services) == ["os", "os_asv_system", "ts1", "ts1_asv_system"], "SITL and a replay container per vessel"
    for key, service in services.items():
        assert service["container_name"] == scope.container_name(key)
        assert "ports" not in service and "restart" not in service
    runner = services[RUNNER_SERVICE]
    assert runner["image"] == "scenegems-simulation-subsystem:latest"
    assert runner["networks"] == [STACK_NETWORK]
    assert set(runner["depends_on"]) == set(services) - {RUNNER_SERVICE}
    # The stack network has no fixed name, so compose scopes it by the project name.
    assert stack.compose["networks"] == {STACK_NETWORK: {"driver": "bridge"}}
    assert stack.compose["volumes"] == {RUNTIME_ASSETS_VOLUME: {"external": True}}
    assert stack.project.name == scope.compose_project
    if layer == "gazebo":
        assert "gazebo" in services
    else:
        assert "gazebo" not in services


def test_generated_files_go_to_the_job_folder(instances_folder, worker_node, make_job, head_on_trajectories):
    job, stack = stack_for("gazebo", worker_node, make_job, head_on_trajectories)
    gen_folder = f"{worker_node.job_scope(job).folder}/gen"
    assert sorted(os.listdir(gen_folder)) == ["ocean_world.sdf", "os_model.sdf", "params-os.params", "params-ts1.params", "trajectories.json", "ts1_model.sdf"]
    sitl_environment = stack.compose["services"]["os"]["environment"]
    assert any(entry.startswith("SITL_PARAM_FILE=") and entry.endswith(f"{gen_folder}/params-os.params") for entry in sitl_environment)
    assert stack.compose["services"]["gazebo"]["environment"]["WORLD_SDF"].endswith(f"{gen_folder}/ocean_world.sdf")


def test_two_jobs_get_disjoint_stacks(instances_folder, worker_node, make_job, head_on_trajectories):
    _, first = stack_for("ardupilot_sim", worker_node, make_job, head_on_trajectories, job_id="a")
    _, second = stack_for("ardupilot_sim", worker_node, make_job, head_on_trajectories, job_id="b")
    first_names = {service["container_name"] for service in first.compose["services"].values()}
    second_names = {service["container_name"] for service in second.compose["services"].values()}
    assert not first_names & second_names
    assert first.project.name == second.project.name == "scenegems-m1-n1", "both stacks are in the worker node's project"
    first_document, second_document = project_compose(first.scope, first.compose), project_compose(second.scope, second.compose)
    assert not set(first_document["services"]) & set(second_document["services"]), "so compose needs their service keys to differ"
    assert not set(first_document["networks"]) & set(second_document["networks"]), "and their network keys, or one stack would take the other's network away"
    assert first.project.instance != second.project.instance, "and each is removed by its own label"


def usv_navigation_stack(worker_node, make_job, head_on_trajectories, layer="ardupilot_sim", **fields):
    payload_data = {"runner": "ardupilot", "simulation_layer": layer, "mode": "usv_navigation", "trajectories": head_on_trajectories.to_dict(), "geofence": GEOFENCE, **fields}
    job = make_job(JobType.SIMULATION, payload_data)
    return job, build_job_stack(job, worker_node, ArduPilotSimulationPayload.model_validate(payload_data))


@pytest.mark.parametrize("layer", ["ardupilot_sim", "gazebo"])
def test_usv_navigation_gets_a_sitl_and_its_asv_system_per_vessel(instances_folder, worker_node, make_job, head_on_trajectories, layer):
    """Every vessel has a SITL service and its ASV system container (USV Navigation's own image for the own ship, replay for the other), and no MAVProxy or ArduAgent."""
    _, stack = usv_navigation_stack(worker_node, make_job, head_on_trajectories, layer)
    services = stack.compose["services"]
    expected = {"os", "ts1", "os_asv_system", "ts1_asv_system", RUNNER_SERVICE} | ({"gazebo"} if layer == "gazebo" else set())
    assert set(services) == expected
    assert services["os"]["image"] == services["ts1"]["image"]
    assert "scenegems-usv-navigation" in services["os_asv_system"]["image"]
    assert "scenegems-simulation-subsystem" in services["ts1_asv_system"]["image"]


def test_an_unknown_own_ship_fails_for_good(instances_folder, worker_node, make_job, head_on_trajectories):
    with pytest.raises(JobFailed) as failure:
        usv_navigation_stack(worker_node, make_job, head_on_trajectories, own_ship_id=7)
    assert not failure.value.retryable and "No vessel with id 7" in str(failure.value)


@pytest.mark.parametrize("layer", ["ardupilot_sim", "gazebo"])
def test_the_payloads_mode_names_its_vessel_stacks(make_job, head_on_trajectories, layer):
    from scenegems_tool.cluster.worker_node.jobs.job_types import payload_components

    payload_data = {"runner": "ardupilot", "simulation_layer": layer, "trajectories": head_on_trajectories.to_dict(), "geofence": GEOFENCE}
    assert payload_components(JobType.SIMULATION, payload_data) == ("asv_system/replay", "control_layer/ardupilot", f"simulation_layer/{layer}")
    assert payload_components(JobType.SIMULATION, {**payload_data, "mode": "usv_navigation"}) == (
        "asv_system/replay",
        "asv_system/usv_navigation",
        "control_layer/ardupilot",
        f"simulation_layer/{layer}",
    )


@pytest.mark.parametrize("fields", [{"own_ship_id": 1}, {"usv_navigation": {"goal": [3000.0, 0.0], "speed": 8.0, "safety_radius": 120.0, "control_horizon": 60.0}}])
def test_closed_loop_options_need_mode_usv_navigation(make_job, head_on_trajectories, fields):
    payload_data = {"runner": "ardupilot", "simulation_layer": "gazebo", "trajectories": head_on_trajectories.to_dict(), "geofence": GEOFENCE, **fields}
    with pytest.raises(JobFailed) as failure:
        parse_payload(SimulationPayload, make_job(JobType.SIMULATION, payload_data))
    assert "apply only to mode usv_navigation" in str(failure.value)
    assert parse_payload(SimulationPayload, make_job(JobType.SIMULATION, {**payload_data, "mode": "usv_navigation"})).root.mode.value == "usv_navigation"


def test_unavailable_stack_fails_for_good(instances_folder, worker_node, make_job, head_on_trajectories):
    payload_data = {"runner": "ardupilot", "simulation_layer": "ardupilot_sim", "trajectories": head_on_trajectories.to_dict(), "geofence": GEOFENCE, "speedup": 1000}
    job = make_job(JobType.SIMULATION, payload_data)
    with pytest.raises(JobFailed) as failure:
        build_job_stack(job, worker_node, ArduPilotSimulationPayload.model_validate(payload_data))
    assert not failure.value.retryable


def test_the_payload_names_its_layer(make_job, head_on_trajectories):
    payload_data = {"runner": "ardupilot", "trajectories": head_on_trajectories.to_dict(), "geofence": GEOFENCE}
    assert parse_payload(SimulationPayload, make_job(JobType.SIMULATION, {**payload_data, "simulation_layer": "gazebo"})).root.simulation_layer.value == "gazebo"
    with pytest.raises(JobFailed) as failure:
        parse_payload(SimulationPayload, make_job(JobType.SIMULATION, payload_data))
    assert not failure.value.retryable and "simulation_layer" in str(failure.value)


class FakeSitlColumns(dict):
    """The replayed columns by vessel id; calls holds each run_mavlink_stack call's instance and USV Navigation parameters."""

    def __init__(self, columns):
        super().__init__(columns)
        self.calls = []


@pytest.fixture
def fake_sitl(monkeypatch, head_on_trajectories):
    """run_mavlink_stack replaced by a replay of the head-on trajectories, observed exactly; returns the replayed columns and the calls."""
    from scenegems_tool.vessel_stack.control_layers.ardupilot import mavlink_lockstep_runner

    vessels = head_on_trajectories.initial_scene.vessels
    columns = FakeSitlColumns({vessel.id: head_on_trajectories.state_list(vessel) for vessel in vessels})

    def replay(trajectories, instance, geofence, *, dt, steps, start_boot_s, on_step=None, usv_navigation_parameters=None, hosting=None):
        columns.calls.append({"instance": instance, "usv_navigation_parameters": usv_navigation_parameters})
        recorded = []
        for index in range(len(columns[0])):
            samples = {vessel_id: StampedState(boot_ms=100_000 + index * 1000, state=column[index]) for vessel_id, column in columns.items()}
            recorded.append(tuple(samples[vessel_id] for vessel_id in sorted(samples)))
            if on_step is not None:
                on_step(index, samples)
        return MavlinkRunResult((0, 1), 1.0, 0, (), (100_000, 100_000), tuple(recorded), (), 12.0, {"steps": len(recorded) - 1})

    monkeypatch.setattr(mavlink_lockstep_runner, "run_mavlink_stack", replay)
    return columns


def _quiet(message, progress=None):
    pass


def _observe(job, speed=10.0):
    frames = []

    class Observation:
        def observer(self, build_frame, dt, **options):
            return RunObserver(lambda: ObservationControl(active=True, speed=speed, revision=1), frames.append, build_frame, dt, sleep=lambda seconds: None, **options)

    return execute(job, _quiet, observation=Observation()), frames


def ardupilot_job(make_job, head_on_trajectories, **fields):
    return make_job(JobType.SIMULATION, {"runner": "ardupilot", "simulation_layer": "ardupilot_sim", "trajectories": head_on_trajectories.to_dict(), "geofence": GEOFENCE, **fields})


def test_an_observed_run_forwards_its_lockstep_states_at_the_stacks_own_pace(fake_sitl, make_job, head_on_trajectories):
    """SITL runs free, so the run is not slowed down; its frames are decimated by its speedup and the result is unchanged."""
    columns = fake_sitl
    job = ardupilot_job(make_job, head_on_trajectories, speedup=50)
    plain = execute(job, _quiet)
    frames, sleeps = [], []

    class Observation:
        def observer(self, build_frame, dt, **options):
            return RunObserver(lambda: ObservationControl(active=True, speed=10.0, revision=1), frames.append, build_frame, dt, sleep=sleeps.append, **options)

    assert execute(job, _quiet, observation=Observation()) == plain
    assert sleeps == []  # not paced
    assert [frame["timestamp"] for frame in frames] == list(range(0, 121, 3))  # 50 steps a second at speedup 50: every third step
    last = frames[-1]
    assert last["scenarioId"] == job.job_id and set(last["statesByActorId"]) == {"0", "1"}
    assert last["statesByActorId"]["1"]["x"] == columns[1][120].x


def test_a_run_without_the_monitor_has_no_verdicts_or_trajectories(fake_sitl, make_job, head_on_trajectories):
    result, frames = _observe(ardupilot_job(make_job, head_on_trajectories))
    assert "monitor" not in result and "trajectories" not in result
    assert frames and all(frame["ruleResults"] == [] for frame in frames)


def test_the_live_monitor_gives_the_post_hoc_result_of_the_observed_run(fake_sitl, make_job, head_on_trajectories):
    """The monitor judges every lockstep step, observed or not, as monitoring.post_hoc judges the run's trajectories."""
    from scenegems_tool.cluster.worker_node.jobs import monitoring_post_hoc_job

    job = ardupilot_job(make_job, head_on_trajectories, monitor="live", include_trajectories=True)
    result = execute(job, _quiet)
    post_hoc = monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, {"trajectories": result["trajectories"]}), _quiet)
    summary_keys = ("scenes", "monitored_scenes", "time_step", "rules", "failed_rules", "passed")
    assert {key: result["monitor"][key] for key in summary_keys} == {key: post_hoc[key] for key in summary_keys}
    assert result["monitor"]["scenes"] == 121 and result["monitor"]["stopped_early_at"] is None
    observed, _ = _observe(job, speed=1.0)
    assert observed == result  # the observation changes nothing in the result


def test_frames_of_judged_steps_carry_the_monitors_outcomes(fake_sitl, make_job, head_on_trajectories):
    columns = fake_sitl
    _, frames = _observe(ardupilot_job(make_job, head_on_trajectories, monitor="live"))
    assert [frame["timestamp"] for frame in frames] == list(range(121))  # speedup 1: a frame per step
    for index in (0, 61, 120):
        frame = frames[index]
        assert frame["ruleResults"] and frame["situationContexts"] and frame["metrics"]
        assert frame["statesByActorId"]["0"]["x"] == columns[0][index].x and frame["statesByActorId"]["1"]["x"] == columns[1][index].x


def test_the_trajectories_hold_the_observed_states(fake_sitl, make_job, head_on_trajectories):
    from concrete_level.models.trajectories import Trajectories

    result = execute(ardupilot_job(make_job, head_on_trajectories, include_trajectories=True), _quiet)
    run = Trajectories.from_dict(result["trajectories"])
    assert run.time_step == 1 and len(run.scene_list) == 121
    for vessel in head_on_trajectories.initial_scene.vessels:
        observed = run.state_list(next(actor for actor in run.initial_scene.vessels if actor.id == vessel.id))
        assert [(state.x, state.y) for state in observed] == [(state.x, state.y) for state in fake_sitl[vessel.id]]


def test_a_run_on_trajectories_sampled_every_15_s_steps_at_one_second(fake_sitl, make_job, head_on_trajectories):
    from concrete_level.models.trajectories import Trajectories
    from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder

    coarse = TrajectoryBuilder.default_trajectory_from_scene(head_on_trajectories.initial_scene, 15, 120)
    result = execute(ardupilot_job(make_job, coarse, include_trajectories=True, monitor="live"), _quiet)
    assert Trajectories.from_dict(result["trajectories"]).time_step == 1
    assert result["monitor"]["time_step"] == 1 and result["monitor"]["scenes"] == 121


def test_static_obstacles_stay_in_every_step_scene(head_on_trajectories):
    from concrete_level.models.actor_state import ActorState
    from concrete_level.models.concrete_actors import ConcreteStaticObstacle
    from concrete_level.models.concrete_scene import ConcreteScene
    from scenegems_tool.cluster.worker_node.jobs.simulation_runners.ardupilot_runner import step_scene

    vessels = head_on_trajectories.initial_scene.vessels
    obstacle = ConcreteStaticObstacle(id=2, type="Buoy", length=10.0, breadth=10.0, height=1.0, draft=1.0, mass=100.0, safety_radius=20.0)
    scene = ConcreteScene({**{vessel: head_on_trajectories.initial_scene[vessel] for vessel in vessels}, obstacle: ActorState(1500.0, 50.0, 0.0, 0.0)})
    moved = ActorState(1.0, 2.0, 8.0, 0.0)
    states = step_scene(scene)({0: StampedState(boot_ms=0, state=moved)})
    assert states[vessels[0]] == moved and states[obstacle] == ActorState(1500.0, 50.0, 0.0, 0.0)


def _asv_adapters(instance):
    return {agent_id: (vessel.stack.asv_system.value, vessel.adapter_ids) for agent_id, vessel in instance.vessels.items()}


def test_replay_puts_every_vessel_on_the_replay_adapter(fake_sitl, make_job, head_on_trajectories):
    execute(ardupilot_job(make_job, head_on_trajectories), _quiet)
    [call] = fake_sitl.calls
    assert _asv_adapters(call["instance"]) == {"0": ("replay", ("replay_mavlink_lockstep",)), "1": ("replay", ("replay_mavlink_lockstep",))}
    assert call["usv_navigation_parameters"] is None


def test_usv_navigation_steers_the_scenes_own_ship(fake_sitl, make_job, head_on_trajectories):
    result = execute(ardupilot_job(make_job, head_on_trajectories, mode="usv_navigation", simulation_layer="gazebo"), _quiet)
    [call] = fake_sitl.calls
    assert _asv_adapters(call["instance"]) == {"0": ("usv_navigation", ("usv_navigation_mavlink_lockstep",)), "1": ("replay", ("replay_mavlink_lockstep",))}
    assert call["instance"].simulation_layer.value == "gazebo"
    assert call["usv_navigation_parameters"] is None  # derived from the own ship's trajectory by run_mavlink_stack
    assert result["steps"] == 120


def test_usv_navigation_steers_the_named_vessel_with_the_given_parameters(fake_sitl, make_job, head_on_trajectories):
    usv_navigation = {"goal": [0.0, 0.0], "speed": 6.0, "safety_radius": 150.0, "control_horizon": 40.0, "runtime_options": {"K": 2.0}}
    execute(ardupilot_job(make_job, head_on_trajectories, mode="usv_navigation", own_ship_id=1, usv_navigation=usv_navigation), _quiet)
    [call] = fake_sitl.calls
    assert _asv_adapters(call["instance"]) == {"0": ("replay", ("replay_mavlink_lockstep",)), "1": ("usv_navigation", ("usv_navigation_mavlink_lockstep",))}
    [(vessel_id, parameters)] = call["usv_navigation_parameters"].items()
    assert vessel_id == 1
    assert (parameters.goal, parameters.speed, parameters.safety_radius, parameters.control_horizon, parameters.runtime_options) == ((0.0, 0.0), 6.0, 150.0, 40.0, (("K", 2.0),))


def test_the_live_monitor_judges_a_usv_navigation_run(fake_sitl, make_job, head_on_trajectories):
    result = execute(ardupilot_job(make_job, head_on_trajectories, mode="usv_navigation", monitor="live", include_trajectories=True), _quiet)
    assert result["monitor"]["scenes"] == 121 and "trajectories" in result
