"""The simulation subsystem on the broker: what a request becomes, that runs go side by side, how its signals reach a run, and the form of what a run publishes."""

from typing import Any, Dict

import pytest

from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.messaging.mqtt_simulation_service import MqttSimulationService
from scenegems_tool.subsystems.simulation.simulation_types import SIMULATION_SERVICE_NAME
from scenegems_tool.subsystems.simulation.simulation_worker import run_task
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline
from tests.scenegems_tool.subsystems.pool.pool_fakes import manual_pool_factory
from tests.scenegems_tool.subsystems.simulation.simulation_fakes import PAYLOAD, stand_in_run, task_context


def service_of(max_workers: int = 1, run_stack=None):
    processes: Dict[str, Any] = {}
    service = offline(MqttSimulationService(CONNECTION, GEOFENCE, max_workers, pool_factory=manual_pool_factory(processes)))
    service.processes = processes
    # The real worker around a run that starts no container
    service.pool.worker = lambda task, channel: run_task(task, channel, task_context(), run_stack or stand_in_run())
    return service


def start(service, request_id: str, **params) -> None:
    request = {"job-id": request_id, "attempt": 1, "payload": PAYLOAD, "request-id": request_id, **params}
    request = {key: value for key, value in request.items() if value is not ...}  # ... drops a field from the request
    deliver(service, service.exec_command_topic, {"command": "start-task", "execution-unit": service.name, "task-uuid": f"u-{request_id}", "task": {"name": "run-simulation", "params": request}})


def signal(service, name: str, request_id: str, data=None) -> None:
    deliver(service, service.exec_command_topic, {"command": "signal-task", "execution-unit": service.name, "signal": {"name": name, "request-id": request_id, "data": data}})


def published(service, channel: str):
    return [message for topic, message in service.client.published if topic == f"{service.topic}/{channel}"]


def states(service) -> Dict[str, str]:
    return {message["request-id"]: message["response"] for message in published(service, "exec/response")}


def test_a_run_simulation_request_is_one_task_with_the_jobs_payload_and_the_requests_seed():
    service = service_of()
    assert (service.name, service.topic) == (SIMULATION_SERVICE_NAME, f"waraps/service/virtual/real/{SIMULATION_SERVICE_NAME}")
    start(service, "r1", seed=4, attempt=2, **{"job-id": "job-7"})
    [task] = service.current_tasks
    assert (task.request_id, task.task_uuid, task.seed, task.sender) == ("r1", "u-r1", 4, service.name)
    assert (task.job_id, task.attempt, task.payload) == ("job-7", 2, PAYLOAD)
    assert task.order_key is None, "a run depends on no other"


@pytest.mark.parametrize(
    "params, reason",
    [
        ({"job-id": ...}, "job-id"),
        ({"payload": ...}, "payload"),
        ({"job-id": ""}, "names the job"),
        ({"attempt": 0}, "at least 1"),
        ({"payload": {"trajectories": {}}}, "names its runner"),
        ({"payload": "text"}, "names its runner"),
    ],
    ids=["no_job", "no_payload", "empty_job", "attempt_0", "no_runner", "payload_not_an_object"],
)
def test_a_request_that_is_no_run_is_refused_with_the_reason(params, reason):
    service = service_of()
    start(service, "r1", **params)
    [response] = published(service, "exec/response")
    assert response["response"] == "failed" and reason in response["fail-reason"] and service.current_tasks == []


def test_runs_of_different_requests_go_side_by_side_and_a_third_waits():
    service = service_of(max_workers=2)
    for request_id in ("r1", "r2", "r3"):
        start(service, request_id)
    service.pool.step()
    assert states(service) == {"r1": "running", "r2": "running", "r3": "queued"}
    service.processes["r1"].work()
    service.pool.step()
    assert states(service) == {"r1": "finished", "r2": "running", "r3": "running"}


def test_a_run_publishes_its_status_its_log_lines_and_then_its_result():
    service = service_of(run_stack=stand_in_run({"steps": 120, "state_digest": "abc"}))
    start(service, "r1", seed=4)
    service.pool.step()
    service.processes["r1"].work()
    service.pool.step()

    preparing, finished = published(service, "exec/feedback")
    assert (preparing["request-id"], preparing["status"], preparing["message"], preparing["detail"]) == ("r1", "running", "generating the stack", {"phase": "preparing"})
    assert (finished["message"], finished["progress"]) == ("run finished", 1.0)
    [log] = published(service, "sensor/simulation_log")
    assert (log["request-id"], log["index"], log["final"]) == ("r1", 0, False) and [line["text"] for line in log["lines"]] == ["the stack is up", "a warning"]
    [result] = published(service, "sensor/simulation_result")
    assert set(result) == {"stamp", "task_sender", "task-uuid", "request-id", "result", "error", "retryable", "frame-batches", "log-batches", "final"}
    assert (result["result"], result["error"], result["frame-batches"], result["log-batches"], result["final"]) == ({"steps": 120, "state_digest": "abc"}, None, 0, 1, True)
    assert states(service) == {"r1": "finished"} and service.current_tasks == []


def test_observe_and_start_reach_the_run_and_its_frames_are_published():
    seen = {}
    service = service_of(run_stack=stand_in_run(wait_for_start=True, frames=2, seen=seen))
    start(service, "r1")
    service.pool.step()
    signal(service, "observe", "r1", {"active": True, "speed": 8.0})
    signal(service, "start", "r1")
    service.processes["r1"].work()
    service.pool.step()
    assert (seen["observed"], seen["speed"]) == (True, 8.0)
    frames = [frame for message in published(service, "sensor/simulation_frames") for frame in message["frames"]]
    assert frames == [{"timestamp": 0}, {"timestamp": 1}]
    [result] = published(service, "sensor/simulation_result")
    assert result["frame-batches"] == len(published(service, "sensor/simulation_frames"))


def test_a_run_that_fails_with_a_reason_finishes_its_task_with_the_reason_as_its_result():
    service = service_of(run_stack=stand_in_run(failure=JobFailed("nobody started the run within 600 s", retryable=False)))
    start(service, "r1")
    service.pool.step()
    service.processes["r1"].work()
    service.pool.step()
    [result] = published(service, "sensor/simulation_result")
    assert (result["result"], result["error"], result["retryable"]) == (None, "nobody started the run within 600 s", False)
    assert states(service) == {"r1": "finished"}, "the requester hears the reason and that another attempt would not help"


def test_a_cancel_reaches_the_run_and_ends_its_task_without_a_result():
    seen = {}
    service = service_of(run_stack=stand_in_run(seen=seen))
    start(service, "r1")
    service.pool.step()
    signal(service, "cancel", "r1")
    service.processes["r1"].work()
    service.pool.step()
    assert seen["cancelled"] and states(service) == {"r1": "aborted"} and published(service, "sensor/simulation_result") == []


def test_the_heartbeat_names_the_task_its_signals_and_its_streams():
    service = service_of(max_workers=2)
    service.publish_heartbeat_and_sensor_info()
    by_topic = {topic: message for topic, message in service.client.published}
    assert by_topic[service.heartbeat_topic]["agent-description"] == "Simulation Subsystem"
    assert by_topic[service.sensor_info_topic]["sensor-data-provided"] == ["simulation_frames", "simulation_log", "simulation_result"]
    info = by_topic[service.direct_execution_topic]
    signals = ["cancel", "observe", "start"]
    assert info["tasks-available"] == [{"name": "run-simulation", "signals": signals}, {"name": "compare-repeats", "signals": signals}] and info["pool-size"] == 2


# The subsystem's second request: the comparison of a run's repeats


def compare(service, request_id: str, payload) -> None:
    command = {"command": "start-task", "execution-unit": service.name, "task-uuid": f"u-{request_id}", "task": {"name": "compare-repeats", "params": {"payload": payload, "request-id": request_id}}}
    deliver(service, service.exec_command_topic, command)


def test_a_compare_repeats_request_is_one_task_of_the_same_pool_next_to_the_runs():
    service = service_of(max_workers=2)
    start(service, "r1")
    compare(service, "r2", {"trajectories": [{}, {}], "reference": "head_on"})
    run, comparison = service.current_tasks
    assert (type(run).__name__, type(comparison).__name__) == ("RunSimulationTask", "CompareRepeatsTask")
    assert (comparison.request_id, comparison.payload) == ("r2", {"trajectories": [{}, {}], "reference": "head_on"})
    service.pool.step()
    assert states(service) == {"r1": "running", "r2": "running"}
    service.publish_heartbeat_and_sensor_info()
    info = [message for topic, message in service.client.published if topic == service.direct_execution_topic][-1]
    assert info["tasks-executing"] == [{"name": "run-simulation", "uuid": "u-r1"}, {"name": "compare-repeats", "uuid": "u-r2"}]


@pytest.mark.parametrize("payload", [None, "text", {"reference": "head_on"}, {"trajectories": {}}])
def test_a_comparison_without_its_repeats_is_refused(payload):
    service = service_of()
    compare(service, "r1", payload)
    [response] = published(service, "exec/response")
    assert response["response"] == "failed" and "lists the repeats' trajectories" in response["fail-reason"] and service.current_tasks == []
