"""The design space exploration subsystem on the broker: what a request becomes, that requests run side by side, and the form of what an exploration publishes."""

from typing import Any, Dict

import pytest

from scenegems_tool.messaging.mqtt_design_space_exploration_service import REQUEST_FIELDS, MqttDesignSpaceExplorationService
from scenegems_tool.subsystems.design_space_exploration.design_space_exploration_types import DESIGN_SPACE_EXPLORATION_SERVICE_NAME
from scenegems_tool.subsystems.design_space_exploration.design_space_exploration_worker import explore
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline
from tests.scenegems_tool.subsystems.design_space_exploration.generator_fakes import NAMED_MODEL, STAND_IN_COMMAND
from tests.scenegems_tool.subsystems.pool.pool_fakes import manual_pool_factory


def service_of(max_workers: int = 1, worker=None):
    processes: Dict[str, Any] = {}
    service = offline(MqttDesignSpaceExplorationService(CONNECTION, GEOFENCE, max_workers, pool_factory=manual_pool_factory(processes)))
    service.processes = processes
    # The real worker with the stand-in for the generator, unless the test brings its own
    service.pool.worker = worker or (lambda task, channel: explore(task, channel, command=STAND_IN_COMMAND, pool_size=max_workers))
    return service


def start(service, request_id: str, **params) -> None:
    request = {"problem": "class A.", "request-id": request_id, **params}
    deliver(service, service.exec_command_topic, {"command": "start-task", "execution-unit": service.name, "task-uuid": f"u-{request_id}", "task": {"name": "explore-design-space", "params": request}})


def published(service, channel: str):
    return [message for topic, message in service.client.published if topic == f"{service.topic}/{channel}"]


def states(service) -> Dict[str, str]:
    return {message["request-id"]: message["response"] for message in published(service, "exec/response")}


def test_an_explore_design_space_request_is_one_task_with_the_requests_seed():
    service = service_of()
    assert (service.name, service.topic) == (DESIGN_SPACE_EXPLORATION_SERVICE_NAME, f"waraps/service/virtual/real/{DESIGN_SPACE_EXPLORATION_SERVICE_NAME}")
    limits = {"max-models": 5, "timeout": 30, "load-timeout": 20, "state-coder-depth": 6, "status-interval": 0.5}
    start(service, "r1", seed=42, scopes=["TS=2"], **{"scope-overrides": ["StaticObstacle=0"]}, **limits)
    [task] = service.current_tasks
    assert (task.request_id, task.task_uuid, task.seed, task.sender) == ("r1", "u-r1", 42, service.name)
    assert (task.problem, task.scopes, task.scope_overrides) == ("class A.", ("TS=2",), ("StaticObstacle=0",))
    assert (task.max_models, task.timeout_s, task.load_timeout_s, task.state_coder_depth, task.status_interval_s) == (5, 30.0, 20.0, 6, 0.5)
    assert task.order_key is None, "an exploration depends on no other"
    assert task.generator_payload()["random_seed"] == 42, "the request's seed is the generator's"


def test_a_request_with_a_problem_alone_leaves_the_rest_to_the_generators_defaults():
    service = service_of()
    start(service, "r1")
    [task] = service.current_tasks
    assert (task.scopes, task.max_models, task.timeout_s, task.load_timeout_s, task.status_interval_s) == ((), None, None, 120.0, 1.0)
    assert 0 <= task.seed, "a request without a seed gets one drawn, as on every subsystem"


@pytest.mark.parametrize(
    "params, reason",
    [
        ({"problem": "  \n"}, "the problem is empty"),
        ({"problem": None}, "the problem is empty"),
        ({"max_models": 5}, "the generator knows no max_models"),
        ({"scope": "TS = 2"}, "the generator knows no scope"),
        ({"scopes": "TS=2"}, "scopes is a list of scope entries"),
        ({"max-models": 0}, "max-models is at least 1"),
        ({"timeout": 0}, "timeout is positive"),
    ],
    ids=["blank", "no_problem", "the_jobs_spelling", "unknown_field", "scopes_not_a_list", "cap_0", "timeout_0"],
)
def test_a_request_the_generator_would_refuse_is_refused_with_the_reason(params, reason):
    service = service_of()
    start(service, "r1", **params)
    [response] = published(service, "exec/response")
    assert response["response"] == "failed" and reason in response["fail-reason"] and service.current_tasks == []


def test_the_request_fields_are_the_generators_in_the_brokers_spelling():
    assert {field.replace("-", "_") for field in REQUEST_FIELDS} == {"problem", "scopes", "scope_overrides", "max_models", "timeout", "load_timeout", "state_coder_depth", "status_interval"}


def test_explorations_of_different_requests_run_side_by_side_and_a_third_waits():
    service = service_of(max_workers=2, worker=lambda task, channel: None)
    for request_id in ("r1", "r2", "r3"):
        start(service, request_id)
    service.pool.step()
    assert states(service) == {"r1": "running", "r2": "running", "r3": "queued"}
    service.processes["r1"].work()
    service.pool.step()
    assert states(service) == {"r1": "finished", "r2": "running", "r3": "running"}


def test_an_exploration_publishes_its_progress_and_then_the_explored_fecs():
    service = service_of()
    start(service, "r1", seed=5)
    service.pool.step()
    service.processes["r1"].work()
    service.pool.step()

    loading, generating, finished = published(service, "exec/feedback")
    assert (loading["request-id"], loading["status"], loading["message"], loading["progress"], loading["detail"]) == ("r1", "running", "loading the problem", None, {"phase": "loading"})
    assert (generating["message"], generating["progress"], generating["detail"]) == ("generating models: 1 of 2 found", 0.5, {"phase": "generating", "models_found": 1})
    assert (finished["progress"], finished["detail"]["phase"]) == (1.0, "finished")

    [message] = published(service, "sensor/design_space")
    assert set(message) == {"stamp", "task_sender", "task-uuid", "request-id", "design-space", "error", "retryable", "final"}
    assert (message["request-id"], message["error"], message["retryable"], message["final"]) == ("r1", None, False, True)
    design_space = message["design-space"]
    assert set(design_space) == {"stop_reason", "complete", "models_found", "max_models", "random_seed", "elapsed_s", "message", "fecs", "functional_scenarios"}
    assert design_space["functional_scenarios"] == [NAMED_MODEL, NAMED_MODEL] and design_space["random_seed"] == 5
    assert states(service) == {"r1": "finished"} and service.current_tasks == []


def test_an_error_of_the_generator_is_published_as_the_result_of_a_finished_task():
    service = service_of()
    start(service, "r1", problem="// stand-in: error\nclass A extends Missing.")
    service.pool.step()
    service.processes["r1"].work()
    service.pool.step()
    [message] = published(service, "sensor/design_space")
    assert (message["design-space"], message["error"], message["retryable"], message["final"]) == (None, "the problem has errors: line 1: no such class Missing", False, True)
    assert states(service) == {"r1": "finished"}, "the task ran to its end: its answer is that the problem cannot be explored"


def test_a_generator_that_dies_fails_its_task_with_the_reason():
    service = service_of()
    start(service, "r1", problem="// stand-in: crash\nclass A.")
    service.pool.step()
    service.processes["r1"].work()
    service.pool.step()
    [failure] = [message for message in published(service, "exec/response") if message["response"] == "failed"]
    assert failure["fail-reason"] == "GeneratorFailed: the model generator ended with exit code 3 and left no result" and published(service, "sensor/design_space") == []


def test_a_cancel_ends_the_exploration_without_a_result():
    service = service_of()
    start(service, "r1", problem="// stand-in: hang\nclass A.")
    service.pool.step()
    deliver(service, service.exec_command_topic, {"command": "signal-task", "execution-unit": service.name, "signal": {"name": "cancel", "request-id": "r1"}})
    service.processes["r1"].work()
    service.pool.step()
    assert states(service) == {"r1": "aborted"} and published(service, "sensor/design_space") == []


def test_the_heartbeat_names_the_task_and_its_stream():
    service = service_of(max_workers=2)
    service.publish_heartbeat_and_sensor_info()
    by_topic = {topic: message for topic, message in service.client.published}
    assert by_topic[service.heartbeat_topic]["agent-description"] == "Design Space Exploration Subsystem"
    assert by_topic[service.sensor_info_topic]["sensor-data-provided"] == ["design_space"]
    info = by_topic[service.direct_execution_topic]
    assert info["tasks-available"] == [{"name": "explore-design-space", "signals": ["cancel"]}] and info["pool-size"] == 2
