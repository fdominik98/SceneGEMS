"""The simulation client mirrors the simulation state of its service and starts simulations."""

import time

import pytest

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.gateway.protocol import SimulationStatus
from scenegems_tool.messaging.mqtt_simulation_client import MqttSimulationClient
from scenegems_tool.messaging.mqtt_simulation_service import SIMULATION_SERVICE_NAME, SIMULATION_SERVICE_TOPIC
from scenegems_tool.vessel_stack.calibration.reference_scenarios import make_vessel
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline


def _client(received=None):
    return offline(MqttSimulationClient(CONNECTION, SIMULATION_SERVICE_TOPIC, GEOFENCE, SIMULATION_SERVICE_NAME, on_simulation_state=(received.append if received is not None else lambda state: None)))


def test_the_state_starts_initializing_at_clock_zero_without_a_scene():
    client = _client()
    assert (client.latest_status, client.latest_clock, client.latest_scene) == (SimulationStatus.INITIALIZING, 0.0, None)
    assert client.listen_topics == [client.simulation_state_topic, client.heartbeat_topic]


def test_a_state_from_the_service_is_kept_and_passed_on():
    received = []
    client = _client(received)
    scene = ConcreteScene({make_vessel(0, True): ActorState(1.0, 2.0, 3.0, 0.5)})
    state = {"task_sender": SIMULATION_SERVICE_NAME, "status": SimulationStatus.INITIALIZING.value, "clock": 4.5, "scene": scene.to_dict()}
    deliver(client, client.simulation_state_topic, state)
    assert received == [state]
    assert client.latest_clock == 4.5
    assert client.latest_scene.to_dict() == scene.to_dict()


def test_a_state_from_another_sender_is_ignored():
    received = []
    client = _client(received)
    deliver(client, client.simulation_state_topic, {"task_sender": "someone_else", "status": "running", "clock": 9.0, "scene": None})
    assert received == [] and client.latest_clock == 0.0


def test_an_unknown_status_reads_as_initializing():
    client = _client()
    client.latest_simulation_state = {"status": "no-such-status"}
    assert client.latest_status == SimulationStatus.INITIALIZING


def test_a_heartbeat_makes_the_service_ready_until_it_goes_stale(monkeypatch):
    client = _client()
    client.last_heartbeat_timestamp = 0.0
    assert not client.is_service_ready
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    deliver(client, client.heartbeat_topic, {})
    assert client.last_heartbeat_timestamp == 1000.0 and client.is_service_ready
    monkeypatch.setattr(time, "time", lambda: 1000.0 + client.heartbeat_interval_sec + 0.1)
    assert not client.is_service_ready


def test_start_simulation_is_published_to_the_service():
    client = _client()
    client.publish_start_simulation_command()
    [(topic, command)] = client.client.published
    assert topic == client.exec_command_topic
    assert (command["command"], command["execution-unit"], command["task"]) == ("start-task", SIMULATION_SERVICE_NAME, {"name": "start-simulation", "params": {}})
    assert command["task_sender"] == "simulation_client" and command["task-uuid"]


def test_waiting_for_the_heartbeat_times_out_without_one(monkeypatch):
    client = _client()
    client.last_heartbeat_timestamp = 0.0
    client.timeout_sec = -1.0
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    with pytest.raises(ValueError, match="simulation service"):
        client.wait_for_heartbeat()
    assert client.client.published == []
