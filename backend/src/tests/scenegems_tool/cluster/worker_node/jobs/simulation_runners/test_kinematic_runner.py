"""The kinematic runner of the simulation job: its stack, and the run with the layers hosted in process: the live monitor gives the post-hoc result, and a run without it is unchanged."""

import io

import pytest

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs import monitoring_post_hoc_job, simulation_job
from scenegems_tool.cluster.worker_node.jobs.in_container.run_observation import ContainerObservation, RunObserver
from scenegems_tool.cluster.worker_node.jobs.simulation_runners.kinematic_runner import KinematicSimulationPayload, build_job_stack, kinematic_run_instance
from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import OBSERVE_DOCUMENT, ObservationControl, parse_frame_line
from scenegems_tool.cluster.worker_node.launchers.per_job.job_stack import RUNNER_SERVICE
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


def test_the_stack_is_the_simulator_an_asv_system_container_per_vessel_and_the_runner(instances_folder, worker_node, make_job, head_on_trajectories):
    job, stack = kinematic_stack(worker_node, make_job, head_on_trajectories)
    scope = worker_node.job_scope(job)
    services = stack.compose["services"]
    assert set(services) == {"kinematic_sim", "vessel_0_asv_system", "vessel_1_asv_system", RUNNER_SERVICE}
    for key, service in services.items():
        assert service["container_name"] == scope.container_name(key)
        assert "scenegems-simulation-subsystem" in service["image"], "the simulator, replay and the runner start from the simulation subsystem image"
        assert service["networks"] == [STACK_NETWORK] and "ports" not in service
    assert set(services[RUNNER_SERVICE]["depends_on"]) == set(services) - {RUNNER_SERVICE}
    assert stack.compose["networks"] == {STACK_NETWORK: {"driver": "bridge"}}, "the job's own network, which reaches nothing else"
    assert "volumes" not in stack.compose, "the runner sends every container what it needs"


def test_in_mode_usv_navigation_the_own_ship_runs_usv_navigations_image(instances_folder, worker_node, make_job, head_on_trajectories):
    _, stack = kinematic_stack(worker_node, make_job, head_on_trajectories, mode="usv_navigation", own_ship_id=1)
    services = stack.compose["services"]
    assert "scenegems-usv-navigation" in services["vessel_1_asv_system"]["image"]
    assert "scenegems-simulation-subsystem" in services["vessel_0_asv_system"]["image"]


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


def test_the_live_monitor_gives_the_post_hoc_result_of_the_same_run(simulate, make_job):
    plain, live = simulate(), simulate(monitor="live")
    assert live["state_digest"] == plain["state_digest"] and live["steps"] == plain["steps"]
    post_hoc = monitoring_post_hoc_job.execute(make_job(JobType.MONITORING_POST_HOC, {"trajectories": plain["trajectories"]}), _quiet)
    assert {key: live["monitor"][key] for key in SUMMARY_KEYS} == {key: post_hoc[key] for key in SUMMARY_KEYS}
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
