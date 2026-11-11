"""The worker of a simulation task with a stand-in for the run: what the runner is given, how its report, its observation and its cancel flag ride on the task's channel, and what the task emits."""

import pytest

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.messages import LogStream
from scenegems_tool.cluster.worker_node.job_observation import JobObservation
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.subsystems.simulation import simulation_worker
from scenegems_tool.subsystems.simulation.simulation_types import SIMULATION_FRAMES_STREAM, SIMULATION_LOG_STREAM, SIMULATION_RESULT_STREAM
from scenegems_tool.subsystems.simulation.simulation_worker import CancelFlag, ChannelReport, TaskRelay, context_from_environment, run_task
from tests.scenegems_tool.subsystems.simulation.simulation_fakes import PAYLOAD, SignalChannel, simulation_task, stand_in_run, task_context


def test_the_runner_gets_the_requests_job_and_the_worker_nodes_context():
    seen = {}
    context = task_context()
    run_task(simulation_task("job-7", attempt=2), SignalChannel(), context, stand_in_run(seen=seen), threaded=False)
    job = seen["job"]
    assert (job.job_id, job.attempt, job.job_type, job.payload, job.idempotency_key) == ("job-7", 2, JobType.SIMULATION, PAYLOAD, "job-7-2")
    assert seen["context"] is context and not seen["cancelled"]
    assert context.job_scope(job).instance_id == "simulation-subsystem-job-7-2", "the names the daemon gave a job's containers"
    assert len(context.observations) == 0, "the run's observation is closed with the run"


def test_the_result_is_emitted_after_everything_the_run_wrote():
    channel = SignalChannel()
    run_task(simulation_task(), channel, task_context(), stand_in_run({"steps": 3}), threaded=False)
    assert [stream for stream, _, _ in channel.emitted] == [SIMULATION_LOG_STREAM, SIMULATION_RESULT_STREAM], "the log lines first"
    [(result, final)] = channel.of(SIMULATION_RESULT_STREAM)
    assert final and result == {"result": {"steps": 3}, "error": None, "retryable": False, "frame-batches": 0, "log-batches": 1}


def test_the_runs_status_is_the_tasks_progress_with_its_detail():
    channel = SignalChannel()
    run_task(simulation_task(), channel, task_context(), stand_in_run(), threaded=False)
    assert channel.progressed == [("generating the stack", None), ("run finished", 1.0)]
    assert channel.details == [{"phase": "preparing"}, None]


def test_the_runs_log_lines_go_out_in_batches_with_their_source_and_stream():
    channel = SignalChannel()
    run_task(simulation_task(), channel, task_context(), stand_in_run(), threaded=False)
    [(batch, final)] = channel.of(SIMULATION_LOG_STREAM)
    assert not final and batch == {"index": 0, "lines": [{"source": "runner", "text": "the stack is up", "stream": "stdout"}, {"source": "runner", "text": "a warning", "stream": "stderr"}]}


def test_many_log_lines_are_split_into_batches(monkeypatch):
    report = ChannelReport(SignalChannel())
    for index in range(5):
        report.log("runner", f"line {index}", LogStream.STDOUT)
    assert [line["text"] for line in report.take_lines(limit=2)] == ["line 0", "line 1"]
    channel = SignalChannel()
    relay = TaskRelay(channel, None, report)
    monkeypatch.setattr(simulation_worker, "LOG_BATCH_LINES", 2)
    relay.step()
    assert [(payload["index"], len(payload["lines"])) for payload, _ in channel.of(SIMULATION_LOG_STREAM)] == [(0, 2), (1, 1)] and relay.log_batches == 2


def test_observe_and_start_reach_the_run_as_its_observation_and_its_frames_go_out():
    """The run waits for the operator's Start, as an attended run does; the signals arrive on the task's channel while it waits."""
    seen = {}
    channel = SignalChannel()
    channel.send("observe", {"active": True, "speed": 4.0})
    channel.send("start")
    run_task(simulation_task(), channel, task_context(), stand_in_run(wait_for_start=True, frames=3, seen=seen))
    assert (seen["observed"], seen["speed"]) == (True, 4.0)
    frames = [frame for payload, _ in channel.of(SIMULATION_FRAMES_STREAM) for frame in payload["frames"]]
    assert frames == [{"timestamp": 0}, {"timestamp": 1}, {"timestamp": 2}]
    assert [payload["index"] for payload, _ in channel.of(SIMULATION_FRAMES_STREAM)] == list(range(len(channel.of(SIMULATION_FRAMES_STREAM))))
    [(result, _)] = channel.of(SIMULATION_RESULT_STREAM)
    assert result["frame-batches"] == len(channel.of(SIMULATION_FRAMES_STREAM)) >= 1
    assert channel.emitted[-1][0] == SIMULATION_RESULT_STREAM, "every frame is out before the result"
    assert ("running", 0.0) in channel.progressed


def test_a_run_nobody_observes_writes_no_frames():
    channel = SignalChannel()
    run_task(simulation_task(), channel, task_context(), stand_in_run(frames=3), threaded=False)
    assert channel.of(SIMULATION_FRAMES_STREAM) == []


def test_the_relay_sets_the_observation_from_the_signals_and_takes_a_batch_a_round():
    observation = JobObservation("job-1", 1, min_interval_s=0.0)
    channel = SignalChannel()
    relay = TaskRelay(channel, observation, ChannelReport(channel))
    channel.send("observe", {"active": True, "speed": 2.0})
    relay.step()
    assert (observation.active, observation.control.speed, observation.started) == (True, 2.0, False)
    channel.send("start")
    channel.send("unknown", {"ignored": True})
    observation.add_frames([({"timestamp": 0}, 20)])
    relay.step()
    assert observation.started and channel.of(SIMULATION_FRAMES_STREAM) == [({"index": 0, "frames": [{"timestamp": 0}]}, False)]
    channel.send("observe", {"active": False, "speed": 2.0})
    relay.step(last=True)
    assert not observation.active and relay.frame_batches == 1


@pytest.mark.parametrize("retryable", [False, True])
def test_a_run_that_fails_with_a_reason_is_a_result_with_its_retry_rule(retryable):
    channel = SignalChannel()
    run_task(simulation_task(), channel, task_context(), stand_in_run(failure=JobFailed("Simulation stack rejected: no such layer", retryable=retryable)), threaded=False)
    [(result, final)] = channel.of(SIMULATION_RESULT_STREAM)
    assert final and (result["result"], result["error"], result["retryable"]) == (None, "Simulation stack rejected: no such layer", retryable)
    assert channel.of(SIMULATION_LOG_STREAM), "what the run wrote until it failed still goes out"


def test_a_cancelled_task_emits_no_result():
    channel = SignalChannel()
    seen = {}

    def cancelled_run(job, context, report, cancel):
        channel.cancelled = True  # the cancel arrives while the stack runs
        seen["cancelled"] = cancel.is_set()
        raise JobFailed("cancelled", retryable=False)

    run_task(simulation_task(), channel, task_context(), cancelled_run, threaded=False)
    assert seen == {"cancelled": True} and channel.of(SIMULATION_RESULT_STREAM) == []


def test_the_cancel_flag_follows_the_tasks_channel():
    channel = SignalChannel()
    flag = CancelFlag(channel)
    assert not flag.is_set()
    channel.cancelled = True
    assert flag.is_set()


def test_a_run_that_breaks_fails_its_task_and_still_closes_its_observation():
    context = task_context()

    def broken(job, context_, report, cancel):
        raise RuntimeError("docker is gone")

    with pytest.raises(RuntimeError, match="docker is gone"):
        run_task(simulation_task(), SignalChannel(), context, broken, threaded=False)
    assert len(context.observations) == 0


def test_the_context_comes_from_the_containers_environment(monkeypatch):
    for variable, value in {
        "SCENEGEMS_CONTROL_NODE_ID": "lab",
        "SCENEGEMS_WORKER_NODE_ID": "bench",
        "SCENEGEMS_DOCKER_NETWORK": "scenegems-lab-bench",
        "MQTT_BROKER": "broker.lab",
        "MQTT_PORT": "1883",
        "MQTT_TOPIC_ROOT": "scenegems",
        "GEOFENCE_LATITUDE": "57.7",
        "GEOFENCE_LONGITUDE": "11.9",
        "GEOFENCE_RADIUS": "2000",
    }.items():
        monkeypatch.setenv(variable, value)
    context = context_from_environment()
    assert (context.control_node_id, context.worker_node_id, context.broker_network) == ("lab", "bench", "scenegems-lab-bench")
    assert (context.mqtt_connection.agent_broker, context.mqtt_connection.topic_root, context.reference_geofence.radius_meters) == ("broker.lab", "scenegems", 2000.0)
    monkeypatch.setenv("SCENEGEMS_DOCKER_NETWORK", " ")
    assert context_from_environment().broker_network is None, "the default network of the stack builder"


def test_the_pools_worker_runs_its_task_in_the_containers_context(monkeypatch):
    seen = []
    monkeypatch.setattr(simulation_worker, "context_from_environment", lambda: "context")
    monkeypatch.setattr(simulation_worker, "run_task", lambda task, channel, context: seen.append((task.request_id, channel, context)))
    simulation_worker.run_simulation_worker(simulation_task(), "channel")
    assert seen == [("job-1-1", "channel", "context")]


def test_without_a_runner_given_the_task_runs_the_simulation_jobs_stack(monkeypatch):
    from scenegems_tool.cluster.worker_node.jobs import simulation_job

    calls = []
    monkeypatch.setattr(simulation_job, "run_stack", lambda job, context, report, cancel: calls.append(job.job_id) or {"ran": True})
    channel = SignalChannel()
    run_task(simulation_task("job-9"), channel, task_context(), threaded=False)
    assert calls == ["job-9"] and channel.of(SIMULATION_RESULT_STREAM)[0][0]["result"] == {"ran": True}


def test_a_task_and_its_worker_cross_the_process_boundary_of_the_pool():
    """The pool starts a worker process with the task and the worker function: both have to pickle, payload and all."""
    import pickle

    task = simulation_task("job-3", attempt=2)
    copy = pickle.loads(pickle.dumps(task))
    assert copy == task and copy.payload == PAYLOAD
    assert pickle.loads(pickle.dumps(simulation_worker.run_simulation_worker)) is simulation_worker.run_simulation_worker
