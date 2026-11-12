"""Scene and trajectory generation on the broker: what a request becomes, and the form of what their tasks publish."""

from typing import Any, Dict

import pytest

from scenegems_tool.messaging.mqtt_scene_generation_service import MqttSceneGenerationService
from scenegems_tool.messaging.mqtt_trajectory_generation_service import MqttTrajectoryGenerationService
from scenegems_tool.subsystems.scene_generation.scene_generation_types import SCENE_GENERATION_SERVICE_NAME
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import TRAJECTORY_GENERATION_SERVICE_NAME, TrajectoryGenerationParams, TrajectoryGeneratorId
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline
from tests.scenegems_tool.subsystems.pool.pool_fakes import manual_pool_factory


def service_of(service_class, max_workers: int = 1, worker=None):
    processes: Dict[str, Any] = {}
    service = offline(service_class(CONNECTION, GEOFENCE, max_workers, pool_factory=manual_pool_factory(processes)))
    service.processes = processes
    if worker is not None:
        service.pool.worker = worker
    return service


def start(service, task: str, request_id: str, **params) -> None:
    command = {"command": "start-task", "execution-unit": service.name, "task-uuid": f"u-{request_id}", "task": {"name": task, "params": {"request-id": request_id, **params}}}
    deliver(service, service.exec_command_topic, command)


def published(service, channel: str):
    return [message for topic, message in service.client.published if topic == f"{service.topic}/{channel}"]


SCENE_REQUEST = {"functional-scenario-content": "problem", "colregs-constraints-content": "colregs", "vessel-types-content": "vessels", "obstacle-types-content": "obstacles", "timeout": 30}
PLAN_REQUEST = {"scenario-content": "{}", "colregs-constraints-content": "colregs", "params": TrajectoryGenerationParams(generator=TrajectoryGeneratorId.STRAIGHT, timespan=60.0).to_wire()}


def test_a_generate_scene_request_is_one_task_with_the_requests_inputs_and_seed():
    service = service_of(MqttSceneGenerationService)
    assert (service.name, service.topic) == (SCENE_GENERATION_SERVICE_NAME, f"waraps/service/virtual/real/{SCENE_GENERATION_SERVICE_NAME}")
    start(service, "generate-scene", "r1", seed=42, **SCENE_REQUEST, **{"enforce-low-tcpa": True})
    [task] = service.current_tasks
    assert (task.request_id, task.task_uuid, task.seed, task.sender) == ("r1", "u-r1", 42, service.name)
    assert (task.functional_scenario_content, task.colregs_constraints_content, task.vessel_types_content, task.obstacle_types_content) == ("problem", "colregs", "vessels", "obstacles")
    assert (task.timeout, task.enforce_low_tcpa) == (30, True)


def test_a_scene_request_without_its_inputs_is_refused():
    service = service_of(MqttSceneGenerationService)
    start(service, "generate-scene", "r1", timeout=30)
    [response] = published(service, "exec/response")
    assert response["response"] == "failed" and "functional-scenario-content" in response["fail-reason"] and service.current_tasks == []


def test_generated_scenes_keep_their_form_and_say_whether_they_are_final():
    from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
    from tests.scenegems_tool.vessel_stack.scenarios import encounter_trajectories

    scene = EvaluationData(best_scene=encounter_trajectories("head_on", 10).initial_scene, timeout=1, random_seed=3)

    def search(task, channel):
        channel.emit("generated_scene", scene)
        channel.emit("generated_scene", scene, final=True)

    service = service_of(MqttSceneGenerationService, worker=search)
    start(service, "generate-scene", "r1", seed=3, **SCENE_REQUEST)
    service.pool.step()
    service.processes["r1"].work()
    service.pool.step()
    sample, final = published(service, "sensor/generated_scene")
    assert (sample["final"], final["final"]) == (False, True)
    assert set(final) == {"stamp", "task_sender", "task-uuid", "request-id", "generated-frame", "evaluation-data", "valid", "final"}, "what the control node's live previews read"
    assert final["request-id"] == "r1" and final["evaluation-data"]["random_seed"] == 3 and isinstance(final["valid"], bool)


def test_a_generate_trajectories_request_is_one_task_with_its_generator_and_seed():
    service = service_of(MqttTrajectoryGenerationService)
    assert service.name == TRAJECTORY_GENERATION_SERVICE_NAME
    start(service, "generate-trajectories", "r1", seed=5, **PLAN_REQUEST)
    [task] = service.current_tasks
    assert (task.seed, task.scenario_content, task.params.generator_id, task.params.timespan) == (5, "{}", TrajectoryGeneratorId.STRAIGHT, 60.0)


def test_a_plan_and_its_previews_keep_their_form():
    def search(task, channel):
        channel.emit("planned_trajectory_preview", {"t": 0})
        channel.emit("planned_trajectory", {"trajectory-data": {"t": 1}, "valid": True, "complete": False, "error-message": None}, final=True)

    service = service_of(MqttTrajectoryGenerationService, worker=search)
    start(service, "generate-trajectories", "r1", seed=5, **PLAN_REQUEST)
    service.pool.step()
    service.processes["r1"].work()
    service.pool.step()
    [preview], [result] = published(service, "sensor/planned_trajectory_preview"), published(service, "sensor/planned_trajectory")
    assert (preview["trajectory-data"], preview["request-id"]) == ({"t": 0}, "r1")
    assert (result["trajectory-data"], result["valid"], result["complete"], result["error-message"]) == ({"t": 1}, True, False, None)


@pytest.mark.parametrize(
    "service_class, task, request_params", [(MqttSceneGenerationService, "generate-scene", SCENE_REQUEST), (MqttTrajectoryGenerationService, "generate-trajectories", PLAN_REQUEST)]
)
def test_a_second_request_waits_for_the_first_instead_of_replacing_it(service_class, task, request_params):
    """With one place in the pool the requests queue; a new request never cancels the one that runs."""
    service = service_of(service_class, max_workers=1, worker=lambda task, channel: None)
    start(service, task, "r1", seed=1, **request_params)
    service.pool.step()
    start(service, task, "r2", seed=2, **request_params)
    service.pool.step()
    states = {message["request-id"]: message["response"] for message in published(service, "exec/response")}
    assert states == {"r1": "running", "r2": "queued"}
    service.processes["r1"].work()
    service.pool.step()
    assert [message["response"] for message in published(service, "exec/response") if message["request-id"] == "r1"][-1] == "finished"
    assert [task.request_id for task in service.current_tasks] == ["r2"] and "r2" in service.processes


@pytest.mark.parametrize(
    "service_class, task, request_params", [(MqttSceneGenerationService, "generate-scene", SCENE_REQUEST), (MqttTrajectoryGenerationService, "generate-trajectories", PLAN_REQUEST)]
)
def test_a_cancel_stops_only_the_named_request(service_class, task, request_params):
    seen = {}

    def search(task, channel):
        seen[task.request_id] = channel.cancelled

    service = service_of(service_class, max_workers=2, worker=search)
    for request_id in ("r1", "r2"):
        start(service, task, request_id, seed=1, **request_params)
    service.pool.step()
    deliver(service, service.exec_command_topic, {"command": "signal-task", "execution-unit": service.name, "signal": {"name": "cancel", "request-id": "r1"}})
    for request_id in ("r1", "r2"):
        service.processes[request_id].work()
    service.pool.step()
    assert seen == {"r1": True, "r2": False}
    ends = {message["request-id"]: message["response"] for message in published(service, "exec/response")}
    assert ends == {"r1": "aborted", "r2": "finished"}
