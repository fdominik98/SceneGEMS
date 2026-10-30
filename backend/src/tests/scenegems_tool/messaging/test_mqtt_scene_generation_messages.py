"""Scene generation over MQTT: the seed in the command and the task, the final flag in the generated scene."""

import pytest

from scenegems_tool.messaging.mqtt_scene_generation_client import MqttSceneGenerationClient
from scenegems_tool.messaging.mqtt_scene_generation_service import MqttSceneGenerationService
from scenegems_tool.subsystems.scene_generation.scene_generation_types import SCENE_GENERATION_SERVICE_NAME, SCENE_GENERATION_SERVICE_TOPIC
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline


def _client(**handlers):
    handlers.setdefault("on_generated_scene", lambda *args: None)
    return offline(MqttSceneGenerationClient(CONNECTION, SCENE_GENERATION_SERVICE_TOPIC, GEOFENCE, SCENE_GENERATION_SERVICE_NAME, send_payload=lambda message: None, **handlers))


def _command(client, **options):
    client.publish_generate_scene_command("r1", "problem", "colregs", "vessels", "obstacles", 30, **options)
    [(topic, command)] = client.client.published
    assert topic == client.exec_command_topic
    return command


def test_the_seed_is_in_the_command_only_when_given():
    assert _command(_client(), seed=42)["task"]["params"]["seed"] == 42
    assert "seed" not in _command(_client())["task"]["params"]


@pytest.fixture
def service():
    return MqttSceneGenerationService(CONNECTION, GEOFENCE, max_workers=1)


def test_the_service_puts_the_seed_into_the_task(service):
    client = _client()
    for seed in (42, None):
        client.client.published.clear()
        command = _command(client, seed=seed)
        deliver(service, service.exec_command_topic, command)
        assert service.scene_generation_task_queue.get(timeout=5).seed == seed


def test_generated_scenes_say_whether_they_are_final(service, monkeypatch):
    offline(service)
    task = _service_task(service)
    scene = _evaluation_data()
    service.publish_generated_scene(task, scene, final=False)
    service.publish_generated_scene(task, scene)
    assert [message["final"] for _, message in service.client.published] == [False, True]


def test_a_cluster_job_gets_every_scene_with_its_final_flag():
    received, monitored = [], []
    client = _client(on_scene_result=lambda *args: received.append(args), on_generated_scene=lambda *args: monitored.append(args))
    message = {"task_sender": SCENE_GENERATION_SERVICE_NAME, "request-id": "r1", "evaluation-data": {"x": 1}, "valid": True}
    deliver(client, client.generated_scene_topic, {**message, "final": False})
    deliver(client, client.generated_scene_topic, message)  # a service from before the flag: one scene, final
    deliver(client, client.generated_scene_topic, {**message, "task_sender": "someone else"})
    assert received == [("r1", {"x": 1}, True, False), ("r1", {"x": 1}, True, True)]
    assert monitored == []


def test_the_cancel_names_the_request_to_stop():
    client = _client()
    client.publish_cancel_command("r1")
    [(topic, command)] = client.client.published
    assert topic == client.exec_command_topic
    assert (command["command"], command["execution-unit"], command["signal"]) == ("signal-task", SCENE_GENERATION_SERVICE_NAME, {"name": "cancel", "request-id": "r1"})


def _service_task(service):
    from scenegems_tool.subsystems.scene_generation.scene_generation_types import MqttSceneGenerationTask

    return MqttSceneGenerationTask(
        sender=service.name, task_uuid="u", request_id="r1", functional_scenario_content="", colregs_constraints_content="", vessel_types_content="", obstacle_types_content="", timeout=1
    )


def _evaluation_data():
    from logical_level.constraint_satisfaction.evaluation_data import EvaluationData
    from tests.scenegems_tool.vessel_stack.scenarios import encounter_trajectories

    return EvaluationData(best_scene=encounter_trajectories("head_on", 10).initial_scene, timeout=1, random_seed=3)
