"""Cancelling a generation of a scene generation pool: only the named request's worker stops.

The service is the real one; its workers run as threads instead of processes, and each stands-in
generation blocks until the test wakes it, then ends without a scene when its own cancel event
was set, or with its final scene. The test steps the pool (`_start_worker`, `_reap_workers`)
and the publisher (`_publish_next_scene`) itself.
"""

import queue
import threading

import pytest

from scenegems_tool.messaging import mqtt_scene_generation_service as service_module
from scenegems_tool.messaging.mqtt_scene_generation_client import MqttSceneGenerationClient
from scenegems_tool.messaging.mqtt_scene_generation_service import MqttSceneGenerationService
from scenegems_tool.subsystems.scene_generation.scene_generation_types import SCENE_GENERATION_SERVICE_NAME, SCENE_GENERATION_SERVICE_TOPIC
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline

_JOIN_S = 10.0  # a safety net only: every wait below ends when the test sets the event


class _ThreadProcess:
    def __init__(self, generations, target, args, name, daemon):
        self._generations = generations
        self._request_id = args[0].request_id
        self._thread = threading.Thread(target=target, args=args, name=name, daemon=daemon)

    def start(self):
        self._thread.start()

    def is_alive(self):
        return self._thread.is_alive()

    def join(self, timeout=None):
        self._thread.join(timeout)

    def terminate(self):
        self._generations.wake_event(self._request_id).set()  # the process ends at once

    kill = terminate


class _Generations:
    """The worker: a generation waits for its wake event, then ends cancelled (nothing published) or with its final scene."""

    def __init__(self):
        self.started = []
        self.wake = {}
        self.threads = {}

    def __call__(self, task, generated_scene_queue, cancel_event):
        self.started.append(task.request_id)
        self.threads[task.request_id] = threading.current_thread()
        assert self.wake_event(task.request_id).wait(_JOIN_S)
        if not cancel_event.is_set():
            generated_scene_queue.put((task, f"scene of {task.request_id}", True))

    def wake_event(self, request_id):
        return self.wake.setdefault(request_id, threading.Event())

    def finish(self, request_id):
        self.wake_event(request_id).set()
        self.threads[request_id].join(_JOIN_S)
        assert not self.threads[request_id].is_alive()


@pytest.fixture
def generations(monkeypatch):
    generations = _Generations()
    monkeypatch.setattr(service_module, "Process", lambda **arguments: _ThreadProcess(generations, **arguments))
    monkeypatch.setattr(service_module, "run_scene_generation_worker", generations)
    return generations


def _service(max_workers):
    service = offline(MqttSceneGenerationService(CONNECTION, GEOFENCE, max_workers=max_workers))
    service.scene_generation_task_queue, service.generated_scene_queue = queue.Queue(), queue.Queue()
    service.published = []
    service.publish_generated_scene = lambda task, scene, final=True: service.published.append((task.request_id, scene, final))
    return service


def _start(service, request_id):
    command = {
        "execution-unit": SCENE_GENERATION_SERVICE_NAME,
        "command": "start-task",
        "task-uuid": f"uuid-{request_id}",
        "task": {
            "name": "generate-scene",
            "params": {
                "request-id": request_id,
                "functional-scenario-content": "",
                "colregs-constraints-content": "",
                "vessel-types-content": "",
                "obstacle-types-content": "",
                "timeout": 30,
            },
        },
    }
    deliver(service, service.exec_command_topic, command)


def _cancel(service, request_id):
    """The cancel exactly as a job's client sends it."""
    client = offline(
        MqttSceneGenerationClient(CONNECTION, SCENE_GENERATION_SERVICE_TOPIC, GEOFENCE, SCENE_GENERATION_SERVICE_NAME, send_payload=lambda message: None, on_generated_scene=lambda *args: None)
    )
    client.publish_cancel_command(request_id)
    [(topic, command)] = client.client.published
    assert topic == client.exec_command_topic
    deliver(service, service.exec_command_topic, command)


def _start_queued(service):
    while not service.scene_generation_task_queue.empty():
        service._start_worker(service.scene_generation_task_queue.get_nowait())


def _published(service):
    while service._publish_next_scene(timeout=0):
        pass
    return {request_id: (scene, final) for request_id, scene, final in service.published}


def _cancelled(service, request_id):
    return service._cancel_events[f"uuid-{request_id}"].is_set()


def test_cancelling_one_of_two_running_generations_leaves_the_other_to_its_scene(generations):
    service = _service(max_workers=2)
    _start(service, "campaign")
    _start(service, "workbench")
    _start_queued(service)
    assert generations.started == ["campaign", "workbench"]

    _cancel(service, "workbench")
    assert _cancelled(service, "workbench") and not _cancelled(service, "campaign")
    generations.finish("workbench")
    service._reap_workers()  # the cancelled worker published nothing: ending is what frees its task
    assert [task.request_id for task in service.current_tasks] == ["campaign"] and list(service._cancel_events) == ["uuid-campaign"]
    assert not _cancelled(service, "campaign")
    generations.finish("campaign")

    assert _published(service) == {"campaign": ("scene of campaign", True)}
    service._reap_workers()
    assert service.current_tasks == [] and service._cancel_events == {} and service._active_workers == []


def test_a_generation_cancelled_while_it_queues_never_starts(generations):
    service = _service(max_workers=2)
    for request_id in ("a", "b", "c"):
        _start(service, request_id)
    _cancel(service, "c")
    _start_queued(service)
    assert generations.started == ["a", "b"]
    assert [task.request_id for task in service.current_tasks] == ["a", "b"] and not _cancelled(service, "a") and not _cancelled(service, "b")
    generations.finish("a")
    generations.finish("b")
    assert sorted(_published(service)) == ["a", "b"]  # nothing for the generation that never ran


@pytest.mark.parametrize("request_id", [None, "unknown"])
def test_a_cancel_for_no_request_or_an_unknown_one_stops_nothing(generations, request_id):
    service = _service(max_workers=2)
    _start(service, "a")
    _start_queued(service)
    if request_id is None:
        deliver(service, service.exec_command_topic, {"execution-unit": SCENE_GENERATION_SERVICE_NAME, "command": "signal-task", "signal": {"name": "cancel"}})
    else:
        _cancel(service, request_id)
    assert not _cancelled(service, "a")
    generations.finish("a")
    assert _published(service) == {"a": ("scene of a", True)}


def test_a_search_sample_does_not_end_the_task(generations):
    service = _service(max_workers=1)
    _start(service, "a")
    _start_queued(service)
    service.generated_scene_queue.put((service.current_tasks[0], "sample", False))
    assert _published(service) == {"a": ("sample", False)}
    assert [task.request_id for task in service.current_tasks] == ["a"]
    generations.finish("a")
    assert _published(service) == {"a": ("scene of a", True)}
    assert service.current_tasks == [] and service._cancel_events == {}


def test_a_worker_that_ends_without_a_scene_frees_its_task_and_event(generations):
    service = _service(max_workers=1)
    _start(service, "a")
    _start_queued(service)
    _cancel(service, "a")
    generations.finish("a")  # cancelled: ends with nothing published
    service._reap_workers()
    assert service.current_tasks == [] and service._cancel_events == {} and service._active_workers == []
    assert _published(service) == {}


def test_the_heartbeat_offers_the_cancel_signal():
    service = _service(max_workers=1)
    service.publish_heartbeat_and_sensor_info()
    [info] = [message for topic, message in service.client.published if topic == service.direct_execution_topic]
    assert info["tasks-available"] == [{"name": "generate-scene", "signals": ["cancel"]}]


def test_stopping_the_service_cancels_every_generation(generations):
    service = _service(max_workers=2)
    _start(service, "a")
    _start(service, "b")
    _start_queued(service)
    events = list(service._cancel_events.values())
    service.stop_runtime()
    assert all(event.is_set() for event in events)
    assert service.current_tasks == [] and service._cancel_events == {}
    assert not any(thread.is_alive() for thread in generations.threads.values())
