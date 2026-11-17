"""The kinematic runner of the simulation job: its pod, and the run with the layers hosted in process: the live monitor gives the post-hoc result, and a run without it is unchanged."""

import io

import pytest

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.instance_scope import INSTANCE_LABEL
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs import simulation_job
from scenegems_tool.cluster.worker_node.jobs.in_container.run_observation import ContainerObservation, RunObserver
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.kinematic_runner import KinematicSimulationPayload, build_job_stack, kinematic_run_instance
from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import OBSERVE_DOCUMENT, ObservationControl, parse_frame_line
from scenegems_tool.cluster.worker_node.launchers.per_job.run_pod import RUNNER_SERVICE
from scenegems_tool.subsystems.monitoring.rule_outcomes import RuleOutcomes
from scenegems_tool.vessel_stack.contracts.stack_services import STACK_NETWORK
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import run_kinematic_replay
from tests.scenegems_tool.vessel_stack.loopback_stack import loopback_hosting

SUMMARY_KEYS = ("scenes", "monitored_scenes", "time_step", "rules", "failed_rules", "passed")


def _quiet(message, progress=None):
    pass


@pytest.fixture
def simulate(make_job, head_on_trajectories):
    def simulate(**fields):
        return simulation_job.execute(make_job(JobType.SIMULATION, {"runner": "kinematic", "trajectories": head_on_trajectories.to_dict(), **fields}), _quiet)

    return simulate


def kinematic_stack(worker_node, make_job, head_on_trajectories, **fields):
    payload_data = {"runner": "kinematic", "trajectories": head_on_trajectories.to_dict(), **fields}
    job = make_job(JobType.SIMULATION, payload_data)
    return job, build_job_stack(job, worker_node, KinematicSimulationPayload.model_validate(payload_data))


def test_the_run_is_one_pod_of_the_simulator_an_asv_system_container_per_vessel_and_the_runner(instances_folder, placed_worker_node, make_job, head_on_trajectories):
    job, stack = kinematic_stack(placed_worker_node, make_job, head_on_trajectories)
    scope = placed_worker_node.job_scope(job)
    services = stack.compose["services"]
    assert set(services) == {"kinematic-sim", "os-asv-system", "ts1-asv-system", RUNNER_SERVICE}
    assert "volumes" not in stack.compose, "the runner sends every container what it needs"
    pod = stack.manifest()
    assert pod["metadata"]["name"] == scope.name and pod["metadata"]["labels"][INSTANCE_LABEL] == scope.labels[INSTANCE_LABEL]
    spec = pod["spec"]
    assert [sidecar["name"] for sidecar in spec["initContainers"]] == [name for name in services if name != RUNNER_SERVICE], "in the order the stack lists them"
    assert [container["name"] for container in spec["containers"]] == [RUNNER_SERVICE]
    for container in [*spec["initContainers"], *spec["containers"]]:
        assert "scenegems-simulation-subsystem" in container["image"], "the simulator, replay and the runner start from the simulation subsystem image"
        assert "ports" not in container
    assert spec["hostAliases"] == [{"ip": "127.0.0.1", "hostnames": sorted(services)}], "every service by its name, in the pod's one network"


def test_the_runner_of_a_judged_run_is_told_the_monitoring_subsystem_and_the_clusters_broker(instances_folder, worker_node, make_job, head_on_trajectories):
    """Its scenes are judged by the worker node's monitoring pool on the cluster's broker, which the runner dials by its name."""
    from scenegems_tool.subsystems.monitoring.monitoring_types import monitoring_pool_from_environment

    worker_node.set_instance_number(3)
    _, stack = kinematic_stack(worker_node, make_job, head_on_trajectories, monitor="live")
    services = stack.compose["services"]
    runner = services[RUNNER_SERVICE]
    service, broker, geofence = monitoring_pool_from_environment(runner["environment"])
    assert service == "monitoring-subsystem-3" and broker["MQTT_BROKER"] == "broker" and geofence == (57.7, 11.9, 2000.0)
    assert runner["environment"]["PYTHONUNBUFFERED"] == "1"
    assert "networks" not in runner, "a pod has one network"
    for key, other in services.items():
        if key != RUNNER_SERVICE:
            assert other["networks"] == [STACK_NETWORK] and "SCENEGEMS_MONITORING_POOL" not in other.get("environment", {})


def test_the_runner_of_a_run_without_a_monitor_is_told_of_none(instances_folder, worker_node, make_job, head_on_trajectories):
    _, stack = kinematic_stack(worker_node, make_job, head_on_trajectories)
    assert "SCENEGEMS_MONITORING_POOL" not in stack.compose["services"][RUNNER_SERVICE]["environment"]


def test_in_mode_usv_navigation_the_own_ship_runs_usv_navigations_image(instances_folder, worker_node, make_job, head_on_trajectories):
    _, stack = kinematic_stack(worker_node, make_job, head_on_trajectories, mode="usv_navigation", own_ship_id=1)
    services = stack.compose["services"]
    assert "scenegems-usv-navigation" in services["ts1-asv-system"]["image"]
    assert "scenegems-simulation-subsystem" in services["os-asv-system"]["image"]


def test_in_mode_moos_ivp_the_own_ship_runs_the_moos_ivp_image(instances_folder, worker_node, make_job, head_on_trajectories):
    _, stack = kinematic_stack(worker_node, make_job, head_on_trajectories, mode="moos_ivp")
    services = stack.compose["services"]
    assert "scenegems-moos-ivp" in services["os-asv-system"]["image"]
    assert services["os-asv-system"]["command"] == ["python3", "-m", "scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_server", "--port", "12000", "--moosdb-port", "12400"]
    assert "scenegems-simulation-subsystem" in services["ts1-asv-system"]["image"]


def test_moos_ivp_parameters_that_contradict_the_scenes_fail_the_stack_for_good(instances_folder, worker_node, make_job, head_on_trajectories):
    with pytest.raises(JobFailed) as failure:
        kinematic_stack(worker_node, make_job, head_on_trajectories, mode="moos_ivp", moos_ivp={"speed": 500.0})
    assert not failure.value.retryable and "Simulation payload rejected" in str(failure.value) and "at most max_speed" in str(failure.value)


def test_a_moos_ivp_run_steps_the_helms_container_and_records_what_it_reported(make_job, head_on_trajectories):
    """The helm lives only in its container: the job's execute steps the layers' servers on the loopback interface, with the tests' helm in MOOS-IvP's place."""
    from tests.scenegems_tool.vessel_stack.asv_system.moos_ivp.fake_helm import FakeHelm

    FakeHelm.started.clear()
    job = make_job(JobType.SIMULATION, {"runner": "kinematic", "trajectories": head_on_trajectories.to_dict(), "mode": "moos_ivp", "moos_ivp": {"avoidance": "cpa", "capture_radius": 75.0}})
    instance = kinematic_run_instance(KinematicSimulationPayload.model_validate(job.payload))[1]
    results = []
    for _ in range(2):
        with loopback_hosting(instance) as hosting:
            results.append(simulation_job.execute(job, _quiet, hosting=hosting))
    assert results[0] == results[1], "the same payload gives the same run"
    record = results[0]["run_record"]
    assert record["stacks"] == {"0": "moos_ivp, none, kinematic", "1": "replay, none, kinematic"} and "moos_ivp_heading_speed" in record["specs"]
    helm_block = record["moos_ivp"]
    assert helm_block["vessel"] == 0 and helm_block["parameters"]["avoidance"] == "cpa" and helm_block["parameters"]["capture_radius"] == 75.0
    assert helm_block["avoidance_behaviour"] == "BHV_AvoidCollision" and helm_block["no_decision_steps"] == 0 and [0.0, "spawn", "avd_c1"] in helm_block["events"]
    assert "usv_navigation" not in record
    assert "capture_radius = 75.0" in FakeHelm.started[0].behaviours
    with pytest.raises(RuntimeError, match="MOOS-IvP runs only in its container"):
        simulation_job.execute(job, _quiet)


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"own_ship_id": 1}, "own_ship_id applies only to the modes usv_navigation and moos_ivp"),
        ({"moos_ivp": {"avoidance": "cpa"}}, "moos_ivp parameters apply only to mode moos_ivp"),
        ({"mode": "usv_navigation", "moos_ivp": {"avoidance": "cpa"}}, "moos_ivp parameters apply only to mode moos_ivp"),
        ({"mode": "moos_ivp", "usv_navigation": {"goal": [1.0, 2.0], "speed": 1.0, "safety_radius": 1.0, "control_horizon": 1.0}}, "usv_navigation parameters apply only to mode usv_navigation"),
        ({"mode": "moos_ivp", "moos_ivp": {"pwt_inner_dist": 500.0, "pwt_outer_dist": 100.0}}, "pwt_inner_dist must not exceed pwt_outer_dist"),
        ({"mode": "moos_ivp", "moos_ivp": {"colour": "red"}}, "Extra inputs are not permitted"),
    ],
)
def test_the_options_of_the_own_ships_software_are_checked(head_on_trajectories, fields, message):
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match=message):
        KinematicSimulationPayload.model_validate({"runner": "kinematic", "trajectories": head_on_trajectories.to_dict(), **fields})


def test_a_payload_without_moos_ivp_keeps_the_json_it_had_before_the_mode(head_on_trajectories):
    data = {"runner": "kinematic", "trajectories": head_on_trajectories.to_dict()}
    assert "moos_ivp" not in KinematicSimulationPayload.model_validate(data).model_dump(mode="json")
    given = KinematicSimulationPayload.model_validate({**data, "mode": "moos_ivp", "moos_ivp": {"avoidance": "cpa"}}).model_dump(mode="json")
    assert given["moos_ivp"] == {"avoidance": "cpa"}, "and the values a payload leaves out stay out"


def test_an_unknown_own_ship_fails_the_stack_for_good(instances_folder, worker_node, make_job, head_on_trajectories):
    with pytest.raises(JobFailed) as failure:
        kinematic_stack(worker_node, make_job, head_on_trajectories, mode="usv_navigation", own_ship_id=9)
    assert not failure.value.retryable and "No vessel with id 9" in str(failure.value)


@pytest.mark.parametrize("fields", [{}, {"mode": "usv_navigation"}, {"monitor": "live"}])
def test_the_run_against_the_containers_is_the_run_in_process(make_job, head_on_trajectories, fields):
    """The job's execute steps real sockets here: every layer's server on the loopback interface, as its container runs it."""
    job = make_job(JobType.SIMULATION, {"runner": "kinematic", "trajectories": head_on_trajectories.to_dict(), **fields})
    instance = kinematic_run_instance(KinematicSimulationPayload.model_validate(job.payload))[1]
    in_process = simulation_job.execute(job, _quiet)
    with loopback_hosting(instance) as hosting:
        assert simulation_job.execute(job, _quiet, hosting=hosting) == in_process


def test_a_run_without_a_monitor_is_the_plain_replay(simulate, head_on_trajectories):
    result = simulate()
    assert "monitor" not in result
    assert result["state_digest"] == run_kinematic_replay(head_on_trajectories).state_digest()
    assert result["steps"] == 120


def test_the_live_monitor_gives_the_post_hoc_result_of_the_same_run(simulate, post_hoc):
    plain, live = simulate(), simulate(monitor="live")
    assert live["state_digest"] == plain["state_digest"] and live["steps"] == plain["steps"]
    judged = post_hoc(plain["trajectories"])
    assert {key: live["monitor"][key] for key in SUMMARY_KEYS} == {key: judged[key] for key in SUMMARY_KEYS}
    assert live["monitor"]["stopped_early_at"] is None
    assert not live["monitor"]["passed"] and live["monitor"]["failed_rules"][0]["first_failed_at"] == 61


def test_early_stop_waits_while_any_rule_is_undecided(simulate):
    # Head on without evasion: two rules fail at 61 s, the vessels' manoeuvre rules stay undecided.
    result = simulate(monitor="live", early_stop=True)
    assert result["steps"] == 120 and result["monitor"]["stopped_early_at"] is None


def test_early_stop_ends_the_run_when_every_rule_is_decided(simulate, monkeypatch):
    monkeypatch.setattr(RuleOutcomes, "every_rule_decided", lambda outcomes: bool(outcomes.failed_rules()))
    stopped = simulate(monitor="live", early_stop=True)
    assert stopped["steps"] == 61 and stopped["run_record"]["steps"] == 61
    assert stopped["monitor"]["stopped_early_at"] == 61 and stopped["monitor"]["scenes"] == 62
    assert len(stopped["trajectories"]["scene_list"]) == 62
    assert stopped["state_digest"] == simulate(steps=61)["state_digest"]  # the same states as a run of that length


def test_a_stop_on_the_last_step_is_not_early(simulate, monkeypatch):
    monkeypatch.setattr(RuleOutcomes, "every_rule_decided", lambda outcomes: outcomes.monitored_scenes == 11)
    result = simulate(monitor="live", early_stop=True, steps=10)
    assert result["steps"] == 10 and result["monitor"]["stopped_early_at"] is None


# Live observation: the run in the runner container, with the job folder on disk and a fake clock (its sleeps move the time only)


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def observe(make_job, head_on_trajectories, tmp_path):
    """Runs the job observed from the start at a speed; returns the result, its frames and the wall time it took."""

    def observe(speed: float, **fields):
        (tmp_path / OBSERVE_DOCUMENT).write_text(ObservationControl(active=True, speed=speed, revision=1).to_document(), encoding="utf-8")
        out, fake_time = io.StringIO(), FakeTime()
        observation = ContainerObservation(str(tmp_path), out=out, clock=fake_time, sleep=fake_time.sleep)
        job = make_job(JobType.SIMULATION, {"runner": "kinematic", "trajectories": head_on_trajectories.to_dict(), **fields})
        result = simulation_job.execute(job, _quiet, observation=observation)
        return result, [parse_frame_line(line) for line in out.getvalue().splitlines()], fake_time.now

    return observe


@pytest.mark.parametrize("fields", [{}, {"monitor": "live"}, {"mode": "usv_navigation"}])
def test_an_observed_run_has_the_digest_and_the_result_of_an_unobserved_one(simulate, observe, fields):
    observed, frames, wall_s = observe(10.0, **fields)
    assert observed == simulate(**fields)  # the whole result, digest included
    assert wall_s == pytest.approx(120 / 10.0)  # 120 s of scenario time at ten times real time
    assert [frame["timestamp"] for frame in frames] == list(range(121))  # ten steps a second: a frame per step


def test_frames_hold_every_vessels_state_and_the_live_monitors_outcomes(observe, head_on_trajectories):
    _, frames, _ = observe(10.0, monitor="live")
    replay = run_kinematic_replay(head_on_trajectories)
    for index in (0, 61, 120):
        frame = frames[index]
        assert frame["scenarioId"] == "job-1" and frame["timeStep"] == 1 and frame["timestamp"] == index
        assert {actor["id"] for actor in frame["actors"]} == {"0", "1"}
        states = [frame["statesByActorId"][str(actor.id)] for actor in replay.actors]
        assert [(state["x"], state["y"], state["speed"], state["heading"]) for state in states] == [(s.x, s.y, s.speed, s.heading) for s in replay.states[index]]
        assert frame["ruleResults"] and frame["situationContexts"] and frame["metrics"]
    _, plain_frames, _ = observe(10.0)
    assert plain_frames[0]["ruleResults"] == [] and plain_frames[0]["statesByActorId"] == frames[0]["statesByActorId"]  # without the monitor: the scene only


def test_a_fast_observed_run_writes_decimated_frames(observe):
    _, frames, wall_s = observe(100.0)
    assert [frame["timestamp"] for frame in frames] == list(range(0, 121, 5))  # at most 20 frames a second
    assert wall_s == pytest.approx(1.2)


def test_an_observation_that_starts_mid_run_picks_up_at_the_current_step(simulate, make_job, head_on_trajectories):
    written = []
    calls = []

    def requests():  # read once per step while not observed: on from step 50, off from step 80
        calls.append(len(calls))
        return ObservationControl(active=50 <= len(calls) - 1 < 80, speed=1000.0, revision=1)

    class Observation:
        def observer(self, build_frame, dt, **options):
            return RunObserver(requests, written.append, build_frame, dt, sleep=lambda seconds: None, **options)

    job = make_job(JobType.SIMULATION, {"runner": "kinematic", "trajectories": head_on_trajectories.to_dict(), "monitor": "live"})
    result = simulation_job.execute(job, _quiet, observation=Observation())
    assert result == simulate(monitor="live")
    assert written[0]["timestamp"] == 50 and written[-1]["timestamp"] < 80
    assert written[0]["ruleResults"]
