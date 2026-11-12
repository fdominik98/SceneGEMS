"""A run's series in the monitoring subsystem: the request and the batches the run sends, where it waits for an answer, and how it ends when the pool does not answer."""

import pytest

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs import pooled_series
from scenegems_tool.cluster.worker_node.jobs.pooled_series import PooledSeries, pooled_series_of
from scenegems_tool.gateway.serialization import serialize_monitored_frame
from scenegems_tool.subsystems.monitoring.monitoring_worker import SeriesMonitor
from scenegems_tool.subsystems.monitoring.rule_outcomes import RuleOutcomes
from tests.concrete_level.colregs_monitoring.monitor_runs import monitored_run
from tests.scenegems_tool.cluster.worker_node.jobs.series_fakes import SynchronousPool

START = (200.0, -200.0)


def scenes(count: int):
    return [result.scene for result in monitored_run(START, count)]


def series_on(pool: SynchronousPool, **options) -> PooledSeries:
    return PooledSeries(pool.client_of, "job-1-1-live", "job-1", 1, None, seed=4, **options)


def test_the_run_requests_a_series_of_its_own_and_waits_until_it_runs():
    pool = SynchronousPool()
    series = series_on(pool)
    assert pool.connected and pool.streams == ("monitored-scene", "monitor_result")
    assert pool.requests == [("monitor-scenario", "job-1-1-live", {"scenario-id": "job-1", "time-step": 1, "colregs-constraints-content": None, "include-frames": False}, 4)]
    assert series.request_id == "job-1-1-live" and pool.signals == []


def test_scenes_go_in_batches_without_waiting_and_the_verdict_is_that_of_one_monitor_over_all_of_them():
    pool = SynchronousPool()
    series = series_on(pool)
    run = scenes(250)
    for scene in run:
        series.add(scene)
    assert [(batch["index"], batch["first-timestamp"], len(batch["scenes"]), batch["frames"]) for batch in pool.batches()] == [
        (0, 0, 100, False),
        (1, 100, 100, False),
    ], "a full batch goes when the next scene comes"
    verdict = series.close()
    assert [(batch["index"], batch["first-timestamp"], len(batch["scenes"])) for batch in pool.batches()][-1] == (2, 200, 50)
    assert pool.signals[-1] == ("close", {"batches": 3}) and pool.disconnected and pool.cancels == []
    reference = SeriesMonitor("job-1", 1)
    reference.add(run)
    assert verdict == {"scenes": 250, "monitored_scenes": 250, "time_step": 1, **reference.summary()}


def test_a_run_that_may_stop_early_gets_an_answer_at_every_step(monkeypatch):
    monkeypatch.setattr(RuleOutcomes, "every_rule_decided", lambda outcomes: outcomes.monitored_scenes >= 3)
    pool = SynchronousPool()
    series = series_on(pool)
    answers = []
    for scene in scenes(4):
        series.add(scene)
        answers.append(series.every_rule_decided())
    assert answers == [False, False, True, True]
    assert [(batch["index"], len(batch["scenes"]), batch["frames"]) for batch in pool.batches()] == [
        (0, 1, True),
        (1, 1, True),
        (2, 1, True),
        (3, 1, True),
    ], "one batch a step, with its frame for the observers"
    assert pool.feedback == [("every rule is decided", {"stop-advised": True, "decided-at": 2})]


def test_the_frame_of_the_latest_step_is_asked_for_only_when_somebody_wants_it():
    pool = SynchronousPool()
    series = series_on(pool)
    run = monitored_run(START, 6)
    for result in run[:3]:
        series.add(result.scene)
    assert pool.batches() == [], "nobody asked: the scenes are still collected"
    frame = series.latest_frame()
    assert frame == serialize_monitored_frame(scenario_id="job-1", monitored_scene=run[2], timestamp=2, time_step=1), "the frame the run's own monitor made before"
    [batch] = pool.batches()
    assert (len(batch["scenes"]), batch["frames"]) == (3, True)
    assert series.latest_frame() == frame, "asked again for the same step: no new batch"
    assert len(pool.batches()) == 1
    for result in run[3:]:
        series.add(result.scene)
    assert series.latest_frame()["timestamp"] == 5 and [len(batch["scenes"]) for batch in pool.batches()] == [3, 3]


def test_a_series_without_scenes_has_no_frame_and_closes_empty():
    pool = SynchronousPool()
    series = series_on(pool)
    assert series.latest_frame() is None
    assert series.close()["scenes"] == 0 and pool.signals == [("close", {"batches": 0})]


def test_a_series_whose_task_fails_fails_the_runs_attempt_with_the_pools_reason():
    pool = SynchronousPool(fail_at=1)
    series = series_on(pool)
    run = scenes(3)
    series.add(run[0])
    assert series.every_rule_decided() is False
    series.add(run[1])
    with pytest.raises(JobFailed, match="The run's series in the monitoring pool failed: the worker process ended without a result") as failure:
        series.every_rule_decided()
    assert failure.value.retryable


def test_a_pool_that_does_not_answer_in_time_fails_the_runs_attempt():
    pool = SynchronousPool(silent=True)
    series = series_on(pool, reply_timeout_s=0.0)
    series.add(scenes(1)[0])
    with pytest.raises(JobFailed, match="The monitoring pool did not judge the run's scenes within 0 s") as failure:
        series.latest_frame()
    assert failure.value.retryable
    with pytest.raises(JobFailed, match="did not return the run's verdict within 0 s"):
        series.close()
    assert pool.cancels == ["job-1-1-live"] and pool.disconnected, "a series that ends without its verdict is cancelled"


def test_a_pool_without_a_heartbeat_fails_the_run_before_it_starts():
    pool = SynchronousPool(heartbeat=False)
    with pytest.raises(JobFailed, match="The monitoring pool sent no heartbeat within 0 s") as failure:
        series_on(pool, start_timeout_s=0.0)
    assert failure.value.retryable and pool.requests == [] and pool.disconnected


def test_a_run_that_ends_without_its_verdict_gives_its_series_up():
    pool = SynchronousPool()
    series = series_on(pool)
    series.add(scenes(1)[0])
    series.abandon()
    assert pool.cancels == ["job-1-1-live"] and pool.disconnected and pool.batches() == []


def test_the_series_of_a_job_names_the_job_as_its_scenario_and_talks_to_the_pool_it_was_given(monkeypatch, make_job):
    made = {}

    class Client:
        def __init__(self, connection, topic, geofence, service_name, **options):
            made.update(connection=connection, topic=topic, geofence=geofence, service_name=service_name, options=options)

    class Series:
        def __init__(self, client_of, request_id, scenario_id, time_step, constants, *, seed):
            made.update(request_id=request_id, scenario_id=scenario_id, time_step=time_step, constants=constants, seed=seed)
            client_of(streams=("monitored-scene",))

    from scenegems_tool.messaging import mqtt_pool_client

    monkeypatch.setattr(mqtt_pool_client, "MqttPoolClient", Client)
    monkeypatch.setattr(pooled_series, "PooledSeries", Series)
    pool = ("monitoring-subsystem-3", {"MQTT_BROKER": "broker.lab", "MQTT_PORT": "1883", "MQTT_TOPIC_ROOT": "scenegems"}, (57.7, 11.9, 2000.0))
    job = make_job(JobType.SIMULATION, {"runner": "kinematic", "seed": 9}, job_id="abc", attempt=2)
    pooled_series_of(pool, job, 2, "constants")
    assert (made["request_id"], made["scenario_id"], made["time_step"], made["constants"], made["seed"]) == ("abc-2-live", "abc", 2, "constants", 9)
    assert (made["topic"], made["service_name"]) == ("scenegems/service/virtual/real/monitoring-subsystem-3", "monitoring-subsystem-3")
    assert (made["connection"].agent_broker, made["connection"].port, made["geofence"].radius_meters) == ("broker.lab", 1883, 2000.0)
    assert made["options"] == {"name": "run_abc-2-live", "streams": ("monitored-scene",)}
