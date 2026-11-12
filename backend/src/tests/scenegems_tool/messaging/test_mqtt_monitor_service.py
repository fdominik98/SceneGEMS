"""The monitoring subsystem on the broker: what a request becomes, which series wait for each other, and the form of what a series publishes."""

from typing import Any, Dict

import pytest

from scenegems_tool.messaging.mqtt_monitor_service import MqttMonitoringService
from scenegems_tool.subsystems.monitoring.monitoring_types import MONITORING_SERVICE_NAME
from scenegems_tool.subsystems.monitoring.rule_outcomes import RuleOutcomes
from tests.concrete_level.colregs_monitoring.monitor_runs import monitored_run
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline
from tests.scenegems_tool.subsystems.pool.pool_fakes import manual_pool_factory

STEPS = 5


def service_of(max_workers: int = 1, worker=None):
    processes: Dict[str, Any] = {}
    service = offline(MqttMonitoringService(CONNECTION, GEOFENCE, max_workers, pool_factory=manual_pool_factory(processes)))
    service.processes = processes
    if worker is not None:
        service.pool.worker = worker
    return service


def start(service, request_id: str, scenario_id: str = "case-1#run0", **params) -> None:
    request = {"scenario-id": scenario_id, "time-step": 1, "colregs-constraints-content": None, "request-id": request_id, **params}
    request = {key: value for key, value in request.items() if value is not ...}  # ... drops a field from the request
    deliver(service, service.exec_command_topic, {"command": "start-task", "execution-unit": service.name, "task-uuid": f"u-{request_id}", "task": {"name": "monitor-scenario", "params": request}})


def signal(service, name: str, request_id: str, data=None) -> None:
    deliver(service, service.exec_command_topic, {"command": "signal-task", "execution-unit": service.name, "signal": {"name": name, "request-id": request_id, "data": data}})


def published(service, channel: str):
    return [message for topic, message in service.client.published if topic == f"{service.topic}/{channel}"]


def states(service) -> Dict[str, str]:
    """The last state of every request the service answered."""
    return {message["request-id"]: message["response"] for message in published(service, "exec/response")}


def scenes():
    return [result.scene.to_dict() for result in monitored_run((200.0, -200.0), STEPS)]


def test_a_monitor_scenario_request_is_one_task_ordered_by_its_scenario():
    service = service_of()
    assert (service.name, service.topic) == (MONITORING_SERVICE_NAME, f"waraps/service/virtual/real/{MONITORING_SERVICE_NAME}")
    start(service, "r1", seed=9, **{"time-step": 2, "colregs-constraints-content": "constants", "include-frames": True})
    [task] = service.current_tasks
    assert (task.request_id, task.task_uuid, task.seed, task.sender) == ("r1", "u-r1", 9, service.name)
    assert (task.scenario_id, task.time_step, task.colregs_constraints_content, task.include_frames) == ("case-1#run0", 2, "constants", True)
    assert task.order_key == "case-1#run0"


def test_a_request_may_leave_the_constants_to_the_defaults_and_gets_no_frames_unless_it_asks():
    service = service_of()
    start(service, "r1")
    [task] = service.current_tasks
    assert task.colregs_constraints_content is None and not task.include_frames
    assert 0 <= task.seed, "a request without a seed gets one drawn, as on every subsystem"


@pytest.mark.parametrize(
    "params, reason",
    [
        ({"scenario-id": ...}, "scenario-id"),
        ({"time-step": ...}, "time-step"),
        ({"colregs-constraints-content": ...}, "colregs-constraints-content"),
        ({"time-step": 0}, "at least 1"),
        ({"colregs-constraints-content": {"not": "text"}}, "YAML text"),
    ],
    ids=["no_scenario", "no_time_step", "no_constants_field", "time_step_0", "constants_not_text"],
)
def test_a_request_the_monitor_cannot_run_is_refused_with_the_reason(params, reason):
    service = service_of()
    scenario_id = params.pop("scenario-id", "case-1#run0")
    start(service, "r1", scenario_id, **params)
    [response] = published(service, "exec/response")
    assert response["response"] == "failed" and reason in response["fail-reason"] and service.current_tasks == []


def test_two_series_of_one_scenario_wait_for_each_other_and_another_scenario_runs_beside_them():
    """The scenes of a scenario are judged in time order; the pool has a free place and still keeps the second series of the scenario waiting."""
    service = service_of(max_workers=3, worker=lambda task, channel: None)
    start(service, "r1", "case-1#run0")
    start(service, "r2", "case-1#run0")
    start(service, "r3", "case-2#run0")
    service.pool.step()
    assert states(service) == {"r1": "running", "r2": "queued", "r3": "running"}
    service.processes["r1"].work()
    service.pool.step()
    assert states(service) == {"r1": "finished", "r2": "running", "r3": "running"}


def test_a_series_is_judged_from_its_signals_and_published_batch_by_batch_then_the_verdict():
    service = service_of()
    start(service, "r1", **{"include-frames": True})
    service.pool.step()
    # The scenes may arrive before the worker reads them: they wait in the task's signals, in order
    signal(service, "scenes", "r1", {"index": 0, "first-timestamp": 0, "scenes": scenes()[:3]})
    signal(service, "scenes", "r1", {"index": 1, "first-timestamp": 3, "scenes": scenes()[3:]})
    signal(service, "close", "r1", {"batches": 2})
    service.processes["r1"].work()
    service.pool.step()

    first, second = published(service, "sensor/monitored-scene")
    assert set(first) == {"stamp", "task_sender", "task-uuid", "request-id", "scenario-id", "index", "monitored-scenes", "every-rule-decided", "monitored-frames", "final"}
    assert first["every-rule-decided"] is False
    assert (first["request-id"], first["scenario-id"], first["index"], first["monitored-scenes"], first["final"]) == ("r1", "case-1#run0", 0, 3, False)
    assert [frame["timestamp"] for frame in first["monitored-frames"] + second["monitored-frames"]] == list(range(STEPS))
    assert {frame["scenarioId"] for frame in second["monitored-frames"]} == {"case-1#run0"}

    expected = RuleOutcomes()
    for result in monitored_run((200.0, -200.0), STEPS):
        expected.add(result)
    [verdict] = published(service, "sensor/monitor_result")
    assert set(verdict) == {"stamp", "task_sender", "task-uuid", "request-id", "scenario-id", "scenes", "monitored-scenes", "time-step", "batches", "summary", "final"}
    assert (verdict["request-id"], verdict["scenes"], verdict["monitored-scenes"], verdict["time-step"], verdict["batches"], verdict["final"]) == ("r1", STEPS, STEPS, 1, 2, True)
    assert verdict["summary"] == expected.summary()
    assert states(service) == {"r1": "finished"} and service.current_tasks == []


def test_a_series_that_cannot_be_judged_fails_its_task_with_the_reason():
    service = service_of()
    start(service, "r1")
    service.pool.step()
    signal(service, "scenes", "r1", {"index": 1, "first-timestamp": 3, "scenes": scenes()[3:]})
    service.processes["r1"].work()
    service.pool.step()
    [failure] = [message for message in published(service, "exec/response") if message["response"] == "failed"]
    assert failure["fail-reason"] == "SeriesError: batch 1 arrived before batch 0" and published(service, "sensor/monitor_result") == []


def test_the_advice_to_stop_goes_out_as_feedback_of_the_running_task(monkeypatch):
    monkeypatch.setattr(RuleOutcomes, "every_rule_decided", lambda self: True)
    service = service_of()
    start(service, "r1")
    service.pool.step()
    signal(service, "scenes", "r1", {"index": 0, "first-timestamp": 0, "scenes": scenes()})
    signal(service, "close", "r1")
    service.processes["r1"].work()
    service.pool.step()
    [feedback] = published(service, "exec/feedback")
    assert (feedback["request-id"], feedback["status"], feedback["message"]) == ("r1", "running", "every rule is decided")
    assert feedback["detail"] == {"stop-advised": True, "decided-at": STEPS - 1}


def test_a_cancel_ends_the_series_without_a_verdict():
    service = service_of()
    start(service, "r1")
    service.pool.step()
    signal(service, "scenes", "r1", {"index": 0, "first-timestamp": 0, "scenes": scenes()})
    signal(service, "cancel", "r1")
    service.processes["r1"].work()
    service.pool.step()
    assert states(service) == {"r1": "aborted"} and published(service, "sensor/monitor_result") == []


def test_the_heartbeat_names_the_task_its_signals_and_its_streams():
    service = service_of(max_workers=2)
    start(service, "r1")
    service.pool.step()
    service.publish_heartbeat_and_sensor_info()
    by_topic = {topic: message for topic, message in service.client.published}
    assert by_topic[service.heartbeat_topic]["agent-description"] == "Monitoring Subsystem"
    assert by_topic[service.sensor_info_topic]["sensor-data-provided"] == ["monitored-scene", "monitor_result"]
    info = by_topic[service.direct_execution_topic]
    assert info["tasks-available"] == [{"name": "monitor-scenario", "signals": ["cancel", "scenes", "close"]}]
    assert info["tasks-executing"] == [{"name": "monitor-scenario", "uuid": "u-r1"}] and info["pool-size"] == 2


def test_a_batch_may_ask_for_its_frames_whatever_the_request_said():
    """A run that is judged while it runs asks only for the batches somebody watches."""
    service = service_of()
    start(service, "r1")  # the request asks for no frames
    service.pool.step()
    signal(service, "scenes", "r1", {"index": 0, "first-timestamp": 0, "scenes": scenes()[:2]})
    signal(service, "scenes", "r1", {"index": 1, "first-timestamp": 2, "scenes": scenes()[2:4], "frames": True})
    signal(service, "scenes", "r1", {"index": 2, "first-timestamp": 4, "scenes": scenes()[4:], "frames": False})
    signal(service, "close", "r1", {"batches": 3})
    service.processes["r1"].work()
    service.pool.step()
    batches = published(service, "sensor/monitored-scene")
    assert [[frame["timestamp"] for frame in batch["monitored-frames"]] for batch in batches] == [[], [2, 3], []]


def test_every_batch_says_whether_every_rule_is_decided(monkeypatch):
    monkeypatch.setattr(RuleOutcomes, "every_rule_decided", lambda outcomes: outcomes.monitored_scenes >= 4)
    service = service_of()
    start(service, "r1")
    service.pool.step()
    signal(service, "scenes", "r1", {"index": 0, "first-timestamp": 0, "scenes": scenes()[:2]})
    signal(service, "scenes", "r1", {"index": 1, "first-timestamp": 2, "scenes": scenes()[2:]})
    signal(service, "close", "r1")
    service.processes["r1"].work()
    service.pool.step()
    assert [batch["every-rule-decided"] for batch in published(service, "sensor/monitored-scene")] == [False, True]
