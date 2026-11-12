"""A subsystem in process for the job tests: its real service and worker, with only the broker and the worker processes replaced.

A job that goes through run_pool_request talks to an InProcessSubsystem as it talks to its worker node's pool:
what the job publishes goes straight to the service, what the service publishes comes straight back, in the
job's own thread. A task's worker runs when the test (or one of the subsystem's hooks) says so.
"""

import threading
from types import SimpleNamespace
from typing import Any, Callable, Dict, List

from scenegems_tool.messaging import mqtt_pool_client
from scenegems_tool.subsystems.pool.pool_task import TaskState
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline
from tests.scenegems_tool.subsystems.pool.pool_fakes import manual_pool_factory

REQUEST = "request arrived"  # the hook after a job's request; no signal has this name


class InProcessSubsystem:
    """A subsystem's service with a pool whose workers run when the test says so, and what happened in it (events).

    hooks: what happens right after the service took a command of the job, by REQUEST (its request) or the signal's name; each is
    called with the request id. A test lets a worker run there (work), kills it (die) or does anything else.
    events: ("request", params, seed), ("state", request id, state), ("signal", name, data), ("feedback", request id, message), ("cancel", request id).
    """

    def __init__(self, service_class: Callable[..., Any], name: str, max_workers: int = 1):
        self.name = name
        self.processes: Dict[str, Any] = {}
        self.service = offline(service_class(CONNECTION, GEOFENCE, max_workers, name=name, pool_factory=manual_pool_factory(self.processes)))
        self.topic = self.service.topic
        self.clients: List["InProcessPoolClient"] = []
        self.events: List[tuple] = []
        self.hooks: Dict[str, Callable[[str], None]] = {}
        self.asked: List[Any] = []  # the subsystems whose pool a job asked its worker node for
        self._relayed = 0
        self._lock = threading.RLock()

    def command(self, command: Dict[str, Any]) -> None:
        with self._lock:
            deliver(self.service, self.service.exec_command_topic, {"execution-unit": self.name, **command})
            self.relay()

    def work(self, request_id: str) -> None:
        """Let the task's worker run to its end, as its process would. Commands of the job still reach the service while it runs."""
        self.processes[request_id].work()
        self.relay()

    def die(self, request_id: str) -> None:
        """The task's worker process ends without a word."""
        with self._lock:
            self.processes[request_id].die()
            self.relay()

    def relay(self) -> None:
        """Step the pool and hand what the service published since the last time to the clients, as the broker would."""
        with self._lock:
            self.service.pool.step()
            published = self.service.client.published[self._relayed :]
            self._relayed = len(self.service.client.published)
            for topic, message in published:
                if topic == self.service.exec_response_topic:
                    self.events.append(("state", message["request-id"], message["response"]))
                elif topic == self.service.exec_feedback_topic:
                    self.events.append(("feedback", message["request-id"], message.get("message")))
                for client in self.clients:
                    client.receive(topic, message)

    def signals(self, name: str) -> List[Any]:
        return [event[2] for event in self.events if event[:2] == ("signal", name)]

    def states(self, request_id: str) -> List[str]:
        return [event[2] for event in self.events if event[:2] == ("state", request_id)]

    def requests(self) -> List[tuple]:
        """(params, seed) of every request the jobs sent."""
        return [event[1:] for event in self.events if event[0] == "request"]

    def cancels(self) -> List[str]:
        return [event[1] for event in self.events if event[0] == "cancel"]

    def serve(self, monkeypatch: Any, worker_node: Any) -> "InProcessSubsystem":
        """Be the pool the worker node hands its jobs, and what their pool clients reach."""
        monkeypatch.setattr(mqtt_pool_client, "MqttPoolClient", type("Client", (InProcessPoolClient,), {"subsystem": self}))

        def pool_of(subsystem: Any) -> SimpleNamespace:
            self.asked.append(subsystem)
            return SimpleNamespace(mqtt_connection=worker_node.mqtt_connection, service_name=self.name, service_topic=self.topic)

        monkeypatch.setattr(worker_node, "pools", SimpleNamespace(get=pool_of))
        return self


class InProcessPoolClient:
    """Stands in for the job's pool client: what the job publishes goes straight to the subsystem, what the subsystem publishes comes straight back."""

    subsystem: InProcessSubsystem
    is_connected = is_heartbeat_valid = True

    def __init__(self, mqtt_connection, topic, reference_geofence, service_name, *, streams=(), on_state=None, on_stream=None, on_feedback=None):
        assert (topic, service_name) == (self.subsystem.topic, self.subsystem.name), "the job talks to its own worker node's pool"
        self.streams, self.on_state, self.on_stream, self.on_feedback = streams, on_state, on_stream, on_feedback
        self.subsystem.clients.append(self)

    def connect(self):
        pass

    def disconnect(self):
        pass

    def receive(self, topic: str, message: Dict[str, Any]) -> None:
        service = self.subsystem.service
        if topic == service.exec_response_topic:
            self.on_state(message["request-id"], TaskState(message["response"]), message["fail-reason"], message["seed"])
        elif topic == service.exec_feedback_topic and self.on_feedback is not None:
            self.on_feedback(message["request-id"], message)
        for stream in self.streams:
            if topic == service.stream_topic(stream):
                self.on_stream(stream, message)

    def _after(self, what: str, request_id: str) -> None:
        hook = self.subsystem.hooks.get(what)
        if hook is not None:
            hook(request_id)

    def publish_start_task(self, task_name, request_id, params, seed):
        self.subsystem.events.append(("request", dict(params), seed))
        self.subsystem.command({"command": "start-task", "task-uuid": f"u-{request_id}", "task": {"name": task_name, "params": {**params, "request-id": request_id, "seed": seed}}})
        self._after(REQUEST, request_id)
        return f"u-{request_id}"

    def publish_signal(self, signal_name, request_id, data=None):
        self.subsystem.events.append(("signal", signal_name, data))
        self.subsystem.command({"command": "signal-task", "signal": {"name": signal_name, "request-id": request_id, "data": data}})
        self._after(signal_name, request_id)

    def publish_cancel(self, request_id):
        self.subsystem.events.append(("cancel", request_id))
        self.subsystem.command({"command": "signal-task", "signal": {"name": "cancel", "request-id": request_id}})
