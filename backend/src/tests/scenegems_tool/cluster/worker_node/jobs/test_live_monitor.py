"""The live COLREGS monitor of the simulation jobs, fed scene by scene: the same outcomes whether the run's series is judged in process or by the monitoring subsystem."""

import pytest

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.jobs import live_monitor
from scenegems_tool.cluster.worker_node.jobs.live_monitor import InProcessSeries, LiveMonitor, SimulationMonitor, series_of_run
from scenegems_tool.cluster.worker_node.jobs.pooled_series import PooledSeries
from scenegems_tool.subsystems.monitoring.rule_outcomes import RuleOutcomes
from tests.scenegems_tool.cluster.worker_node.jobs.series_fakes import SynchronousPool


def _feed(monitor: LiveMonitor, trajectories) -> int:
    """Feed every step of the trajectories; the index the monitor stopped at, or the last one."""
    columns = [trajectories.state_list(actor) for actor in monitor.actors]
    for index, states in enumerate(zip(*columns)):
        if monitor.on_step(index, states):
            return index
    return len(columns[0]) - 1


def _pooled(pool: SynchronousPool) -> PooledSeries:
    """The run's series in a monitoring subsystem that answers at once."""
    return PooledSeries(pool.client_of, "job-1-1-live", "job-1", 1, None)


def _monitor(trajectories, where: str, early_stop: bool = False, pool=None) -> LiveMonitor:
    series = InProcessSeries("job-1", 1, None) if where == "in_process" else _pooled(pool or SynchronousPool())
    return LiveMonitor(trajectories.initial_scene.actors, 1, None, early_stop=early_stop, series=series)


def test_the_wire_values_stay():
    assert [member.value for member in SimulationMonitor] == ["none", "live"]


@pytest.mark.parametrize("where", ["in_process", "pooled"])
def test_every_step_is_judged_in_the_post_hoc_shape(head_on_trajectories, where):
    monitor = _monitor(head_on_trajectories, where)
    assert _feed(monitor, head_on_trajectories) == 120
    result = monitor.result(stopped_early=False)
    assert result["scenes"] == 121 and result["monitored_scenes"] == 121 and result["time_step"] == 1
    assert {"rules", "failed_rules", "encounters", "encounter_roles", "passed"} <= set(result) and result["stopped_early_at"] is None
    assert not result["passed"] and result["failed_rules"][0]["first_failed_at"] == 61


def test_the_monitoring_subsystem_gives_the_result_and_the_frames_of_the_monitor_in_process(head_on_trajectories):
    """Where the series is judged does not change what the run reports: its result and what its observers see."""
    pool = SynchronousPool()
    in_process, pooled = _monitor(head_on_trajectories, "in_process"), _monitor(head_on_trajectories, "pooled", pool=pool)
    columns = [head_on_trajectories.state_list(actor) for actor in in_process.actors]
    for index, states in enumerate(zip(*columns)):
        in_process.on_step(index, states)
        pooled.on_step(index, states)
        if index in (0, 60, 61, 120):  # somebody watches these steps
            frame = pooled.frame_of(index)
            assert frame == in_process.frame_of(index) and frame["timestamp"] == index and frame["scenarioId"] == "job-1"
    assert pooled.result(stopped_early=False) == in_process.result(stopped_early=False)
    assert [len(batch["scenes"]) for batch in pool.batches()] == [1, 60, 1, 59], "the scenes went when a frame was asked for, and at the end"
    assert [batch["frames"] for batch in pool.batches()] == [True, True, True, True]


@pytest.mark.parametrize("where", ["in_process", "pooled"])
def test_early_stop_ends_the_feed_once_every_rule_is_decided(head_on_trajectories, monkeypatch, where):
    monkeypatch.setattr(RuleOutcomes, "every_rule_decided", lambda outcomes: outcomes.monitored_scenes == 11)
    monitor = _monitor(head_on_trajectories, where, early_stop=True)
    assert _feed(monitor, head_on_trajectories) == 10, "the same step wherever the series is judged"
    result = monitor.result(stopped_early=True)
    assert (result["stopped_early_at"], result["scenes"]) == (10, 11)
    assert monitor.frame_of(10)["timestamp"] == 10, "the step it stopped at still has its frame for the observers"


def test_a_frame_is_that_of_the_step_judged_last_and_carries_the_runs_own_time(head_on_trajectories):
    monitor = LiveMonitor(head_on_trajectories.initial_scene.actors, 2, None, early_stop=False, series=InProcessSeries("job-1", 2, None))
    assert monitor.frame_of(0) is None, "nothing is judged yet"
    states = [head_on_trajectories.state_list(actor)[0] for actor in monitor.actors]
    monitor.on_step(0, states)
    monitor.on_step(1, states)
    assert monitor.frame_of(0) is None, "an earlier step: its frame is the scene alone"
    assert monitor.frame_of(1)["timestamp"] == 2, "step 1 of a run with 2 s steps"


class RecordingSeries:
    """A series that only counts what the monitor asks of it."""

    def __init__(self):
        self.added, self.closed, self.abandoned = 0, 0, 0

    def add(self, scene):
        self.added += 1

    def every_rule_decided(self):
        raise AssertionError("a run without early stop never waits for the monitor")

    def latest_frame(self):
        return None

    def close(self):
        self.closed += 1
        return {"scenes": self.added, "monitored_scenes": self.added, "time_step": 1, "rules": {}, "failed_rules": [], "encounters": {}, "encounter_roles": {}, "passed": True}

    def abandon(self):
        self.abandoned += 1


def test_a_run_without_early_stop_never_waits_and_closes_its_series_once(head_on_trajectories):
    series = RecordingSeries()
    monitor = LiveMonitor(head_on_trajectories.initial_scene.actors, 1, None, early_stop=False, series=series)
    assert _feed(monitor, head_on_trajectories) == 120 and series.added == 121
    assert monitor.frame_of(120) is None, "the series has no frame: the observers get the scene alone"
    first = monitor.result(stopped_early=False)
    assert monitor.result(stopped_early=False) == first and series.closed == 1
    monitor.abandon()
    assert series.abandoned == 0, "a closed series is not given up"


def test_a_run_that_ends_without_its_result_gives_its_series_up(head_on_trajectories):
    series = RecordingSeries()
    LiveMonitor(head_on_trajectories.initial_scene.actors, 1, None, early_stop=False, series=series).abandon()
    assert (series.closed, series.abandoned) == (0, 1)


def test_the_series_is_in_the_monitoring_subsystem_the_runner_was_given_and_in_process_without_one(monkeypatch, make_job):
    job = make_job(JobType.SIMULATION, {"runner": "kinematic"})
    monkeypatch.delenv("SCENEGEMS_MONITORING_POOL", raising=False)
    assert isinstance(series_of_run(job, 1, None), InProcessSeries)
    from scenegems_tool.cluster.worker_node.jobs import pooled_series
    from scenegems_tool.subsystems.monitoring.monitoring_types import monitoring_pool_environment

    asked = []
    monkeypatch.setattr(pooled_series, "pooled_series_of", lambda pool, job, time_step, constants: asked.append((pool, job.job_id, time_step, constants)) or "pooled")
    for variable, value in monitoring_pool_environment("monitoring-subsystem-3", {"MQTT_BROKER": "broker", "MQTT_PORT": "1883"}, (57.7, 11.9, 2000.0)).items():
        monkeypatch.setenv(variable, value)
    assert series_of_run(job, 2, "constants") == "pooled"
    assert asked == [(("monitoring-subsystem-3", {"MQTT_BROKER": "broker", "MQTT_PORT": "1883"}, (57.7, 11.9, 2000.0)), "job-1", 2, "constants")]
    assert isinstance(series_of_run(None, 1, None), InProcessSeries), "a monitor outside a job has nothing to name its series by"
    assert isinstance(live_monitor.LiveMonitor([], 1, None, False, job=None).series, InProcessSeries)
