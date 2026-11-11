"""The simulation service queues start-simulation tasks and reports the simulation state."""

import pytest

from scenegems_tool.gateway.protocol import SimulationStatus
from scenegems_tool.messaging.mqtt_simulation_service import (
    SIMULATION_SERVICE_NAME,
    SIMULATION_SERVICE_TOPIC,
    MqttSimulationService,
    MqttStartSimulationTask,
)
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline


def _service():
    return offline(MqttSimulationService(CONNECTION, GEOFENCE))


def _command(**changes):
    command = {
        "execution-unit": SIMULATION_SERVICE_NAME,
        "command": "start-task",
        "task": {"name": "start-simulation", "params": {}},
        "task_sender": "client",
        "task-uuid": "u1",
    }
    command.update(changes)
    return command


def test_service_name_and_topics():
    service = _service()
    assert service.topic == SIMULATION_SERVICE_TOPIC
    assert service.listen_topics == [service.exec_command_topic]
    assert service.simulation_state_topic == f"{SIMULATION_SERVICE_TOPIC}/sensor/simulation-state"


def test_a_start_simulation_command_is_queued():
    service = _service()
    deliver(service, service.exec_command_topic, _command())
    assert service.task_queue.get_nowait() == MqttStartSimulationTask(sender="client", task_uuid="u1")


@pytest.mark.parametrize(
    "changes",
    [{"execution-unit": "someone_else"}, {"command": "abort-task"}, {"task": {"name": "other", "params": {}}}],
    ids=["other_unit", "other_command", "other_task"],
)
def test_other_commands_are_ignored(changes):
    service = _service()
    deliver(service, service.exec_command_topic, _command(**changes))
    assert service.task_queue.empty()


def test_ready_follows_connect_and_disconnect():
    service = _service()
    service.client.subscribe = lambda topic: None
    assert not service.is_ready
    service.on_connect(None, None, {}, 5)
    assert not service.is_ready
    service.on_connect(None, None, {}, 0)
    assert service.is_ready
    service.on_disconnect(None, None, 0)
    assert not service.is_ready


def test_the_simulation_state_is_published_with_status_clock_and_scene():
    service = _service()
    service.publish_simulation_state(SimulationStatus.INITIALIZING, 1.5, {"scene": 1})
    [(topic, message)] = service.client.published
    assert topic == service.simulation_state_topic
    assert (message["task_sender"], message["status"], message["clock"], message["scene"]) == (SIMULATION_SERVICE_NAME, SimulationStatus.INITIALIZING.value, 1.5, {"scene": 1})


def test_heartbeat_lists_the_tracked_tasks_as_executing():
    service = _service()
    task = MqttStartSimulationTask("client", "u1")
    other = MqttStartSimulationTask("client", "u2")
    service.track_task(task)
    service.track_task(other)
    service.untrack_task(task)
    service.untrack_task(task)  # untracking twice is harmless
    service.publish_heartbeat_and_sensor_info()
    published = {topic: message for topic, message in service.client.published}
    assert published[service.heartbeat_topic]["agent-description"] == "Simulation Subsystem"
    assert published[service.sensor_info_topic]["sensor-data-provided"] == ["simulation-state"]
    info = published[service.direct_execution_topic]
    assert info["tasks-available"] == [{"name": "start-simulation", "signals": []}]
    assert info["tasks-executing"] == [{"name": "start-simulation", "uuid": "u2"}]
