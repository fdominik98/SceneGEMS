"""The requester's side of a subsystem: what a request and a signal look like, and what it hears back."""

from scenegems_tool.messaging.mqtt_pool_client import HEARTBEAT_VALID_S, MqttPoolClient
from scenegems_tool.subsystems.pool.pool_task import TaskState
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline

SERVICE = "scene-generation-subsystem-3"
TOPIC = f"scenegems/service/virtual/real/{SERVICE}"


class Heard:
    def __init__(self):
        self.states, self.streams, self.feedback = [], [], []


def client_of(clock=None, **options):
    heard = Heard()
    client = MqttPoolClient(
        CONNECTION,
        TOPIC,
        GEOFENCE,
        SERVICE,
        streams=("generated_scene",),
        on_state=lambda *args: heard.states.append(args),
        on_stream=lambda stream, message: heard.streams.append((stream, message["request-id"])),
        on_feedback=lambda request_id, message: heard.feedback.append((request_id, message["message"])),
        **({"clock": clock} if clock is not None else {}),
        **options,
    )
    return offline(client), heard


def test_a_request_carries_its_inputs_its_request_id_and_its_seed():
    client, _ = client_of()
    task_uuid = client.publish_start_task("generate-scene", "job-1-1", {"timeout": 30}, seed=42)
    [(topic, command)] = client.client.published
    assert topic == f"{TOPIC}/exec/command"
    assert (command["command"], command["execution-unit"], command["task-uuid"], command["task_sender"]) == ("start-task", SERVICE, task_uuid, "pool_client")
    assert command["task"] == {"name": "generate-scene", "params": {"timeout": 30, "request-id": "job-1-1", "seed": 42}}


def test_a_signal_names_the_request_it_is_for_and_a_cancel_is_a_signal():
    client, _ = client_of()
    client.publish_signal("start", "job-1-1", {"speed": 10})
    client.publish_cancel("job-1-1")
    (_, start), (_, cancel) = client.client.published
    assert (start["command"], start["execution-unit"], start["signal"]) == ("signal-task", SERVICE, {"name": "start", "request-id": "job-1-1", "data": {"speed": 10}})
    assert cancel["signal"] == {"name": "cancel", "request-id": "job-1-1"}


def test_it_listens_to_the_states_the_progress_the_heartbeat_and_its_streams():
    client, _ = client_of()
    assert client.listen_topics == [f"{TOPIC}/exec/response", f"{TOPIC}/exec/feedback", f"{TOPIC}/heartbeat", f"{TOPIC}/sensor/generated_scene"]


def test_it_hands_on_what_its_subsystem_sent_and_nothing_of_anybody_else():
    client, heard = client_of()
    ours = {"task_sender": SERVICE, "request-id": "job-1-1"}
    deliver(client, f"{TOPIC}/exec/response", {**ours, "response": "running", "fail-reason": None, "seed": 42})
    deliver(client, f"{TOPIC}/exec/response", {**ours, "response": "failed", "fail-reason": "no scene", "seed": 42})
    deliver(client, f"{TOPIC}/exec/response", {**ours, "response": "planning"})  # another vocabulary
    deliver(client, f"{TOPIC}/exec/response", {"task_sender": "somebody else", "request-id": "job-1-1", "response": "finished"})
    deliver(client, f"{TOPIC}/exec/feedback", {**ours, "message": "working"})
    deliver(client, f"{TOPIC}/sensor/generated_scene", {**ours, "final": True})
    deliver(client, f"{TOPIC}/sensor/generated_scene", "not a message")
    assert heard.states == [("job-1-1", TaskState.RUNNING, None, 42), ("job-1-1", TaskState.FAILED, "no scene", 42)]
    assert heard.feedback == [("job-1-1", "working")] and heard.streams == [("generated_scene", "job-1-1")]


def test_the_subsystem_counts_as_there_while_its_heartbeat_is_fresh():
    now = [100.0]
    client, _ = client_of(clock=lambda: now[0])
    client.last_heartbeat_timestamp = None  # the helper connects a client as if its subsystem already heartbeats
    assert not client.is_heartbeat_valid, "nothing heard yet"
    deliver(client, f"{TOPIC}/heartbeat", {"name": SERVICE})
    assert client.is_heartbeat_valid
    now[0] += HEARTBEAT_VALID_S + 0.1
    assert not client.is_heartbeat_valid
