"""A subsystem on the broker: a request becomes tasks with its seed, every task state is published, and signals reach the tasks."""

from typing import Any, Dict, List, Mapping

import pytest

from scenegems_tool.messaging.mqtt_pool_service import PoolService
from scenegems_tool.subsystems.pool.pool_task import MAX_SEED, PoolTask
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline
from tests.scenegems_tool.subsystems.pool.pool_fakes import manual_pool_factory

NAME = "echo-subsystem-3"
BASE = f"waraps/service/virtual/real/{NAME}"


def echo(task, channel):
    channel.progress("working", 0.5, {"phase": "running"})
    for signal in channel.signals():
        channel.emit("answers", {"signal": signal.name, "data": signal.data})
    channel.emit("result", {"seed": task.seed}, final=True)


class EchoService(PoolService):
    """A subsystem whose request makes as many tasks as it asks for (repeats), each answering with its seed."""

    description = "Echo Subsystem"
    task_name = "echo"
    signals = ("start",)
    streams = ("result", "answers")
    worker = staticmethod(echo)

    def make_tasks(self, task_uuid: str, request_id: str, seed: int, params: Mapping[str, Any]) -> List[PoolTask]:
        from scenegems_tool.subsystems.pool.pool_task import task_seed

        repeats = int(params.get("repeats", 1))
        if repeats < 1:
            raise ValueError("repeats is at least 1")
        return [PoolTask(sender=self.name, task_uuid=task_uuid if index == 0 else f"{task_uuid}-{index}", request_id=request_id, seed=task_seed(seed, index)) for index in range(repeats)]

    def stream_message(self, task: PoolTask, stream: str, payload: Any, final: bool) -> Dict[str, Any]:
        return {**payload, "final": final}


@pytest.fixture
def service():
    processes: Dict[str, Any] = {}
    made = offline(EchoService(CONNECTION, GEOFENCE, 2, NAME, pool_factory=manual_pool_factory(processes)))
    made.processes = processes
    return made


def request(request_id: str = "r1", task_uuid: str = "u1", unit: str = NAME, task: str = "echo", **params) -> dict:
    return {"command": "start-task", "execution-unit": unit, "task-uuid": task_uuid, "task": {"name": task, "params": {"request-id": request_id, **params}}}


def signal(name: str, request_id: str = "r1", **extra) -> dict:
    return {"command": "signal-task", "execution-unit": NAME, "task-uuid": "s", "signal": {"name": name, "request-id": request_id, **extra}}


def published(service, channel: str) -> List[dict]:
    return [message for topic, message in service.client.published if topic == f"{BASE}/{channel}"]


def responses(service, request_id: str = "r1") -> List[str]:
    return [message["response"] for message in published(service, "exec/response") if message["request-id"] == request_id]


def test_a_request_is_received_queued_run_and_finished_and_every_state_is_published(service):
    deliver(service, service.exec_command_topic, request(seed=42))
    assert responses(service) == ["received", "queued"] and [task.request_id for task in service.current_tasks] == ["r1"]
    service.pool.step()
    assert responses(service) == ["received", "queued", "running"]
    service.processes["r1"].work()
    service.pool.step()
    assert responses(service) == ["received", "queued", "running", "finished"] and service.current_tasks == []
    last = published(service, "exec/response")[-1]
    assert (last["task_sender"], last["task-uuid"], last["seed"], last["fail-reason"]) == (NAME, "u1", 42, None), "every response says who, which task and which seed"


def test_what_a_task_hands_back_goes_out_on_its_stream_and_its_progress_as_feedback(service):
    deliver(service, service.exec_command_topic, request(seed=42))
    service.pool.step()
    service.processes["r1"].work()
    service.pool.step()
    [result] = published(service, "sensor/result")
    assert (result["seed"], result["final"], result["request-id"], result["task-uuid"], result["task_sender"]) == (42, True, "r1", "u1", NAME)
    [feedback] = published(service, "exec/feedback")
    assert (feedback["status"], feedback["message"], feedback["progress"], feedback["detail"], feedback["request-id"]) == ("running", "working", 0.5, {"phase": "running"}, "r1")
    topics = [topic for topic, _ in service.client.published]
    assert topics.index(f"{BASE}/sensor/result") < len(topics) - 1, "the result is out before the task's last state"


def test_a_request_without_a_seed_gets_one_drawn_and_every_response_names_it(service):
    deliver(service, service.exec_command_topic, request())
    seeds = {message["seed"] for message in published(service, "exec/response")}
    assert len(seeds) == 1 and 0 <= seeds.pop() <= MAX_SEED


def test_the_tasks_of_one_request_get_seeds_derived_from_its_seed(service):
    deliver(service, service.exec_command_topic, request(seed=7, repeats=3))
    tasks = service.current_tasks
    assert [task.task_uuid for task in tasks] == ["u1", "u1-1", "u1-2"] and tasks[0].seed == 7
    assert len({task.seed for task in tasks}) == 3
    deliver(service, service.exec_command_topic, request("r2", "u2", seed=7, repeats=3))
    assert [task.seed for task in service.current_tasks[3:]] == [task.seed for task in tasks], "the same seed gives the same tasks"


@pytest.mark.parametrize(
    "command, reason",
    [
        (request(repeats=0), "the request was refused: repeats is at least 1"),
        (request(repeats="many"), "the request was refused: invalid literal"),
        ({"command": "start-task", "execution-unit": NAME, "task-uuid": "u1", "task": {"name": "echo", "params": {}}}, "its request-id"),
        (request(seed="x"), "the request was refused"),
    ],
)
def test_a_request_the_subsystem_cannot_run_is_answered_as_failed_and_never_queued(service, command, reason):
    deliver(service, service.exec_command_topic, command)
    [response] = published(service, "exec/response")
    assert response["response"] == "failed" and reason in response["fail-reason"]
    assert service.current_tasks == []


def test_a_command_for_another_subsystem_or_another_task_is_not_taken(service):
    deliver(service, service.exec_command_topic, request(unit="echo-subsystem-4"))
    deliver(service, service.exec_command_topic, request(task="generate-scene"))
    deliver(service, service.exec_command_topic, "not a command")
    assert service.client.published == [] and service.current_tasks == []


def test_a_cancel_stops_the_tasks_of_its_request_only(service):
    for request_id in ("r1", "r2", "r3"):
        deliver(service, service.exec_command_topic, request(request_id, f"u-{request_id}"))
    service.pool.step()  # two places: r1 and r2 run, r3 waits
    deliver(service, service.exec_command_topic, signal("cancel", "r3"))
    deliver(service, service.exec_command_topic, signal("cancel", "r1"))
    assert responses(service, "r3") == ["received", "queued", "aborted"], "a queued task never starts"
    service.processes["r1"].work()
    service.pool.step()
    assert responses(service, "r1")[-1] == "aborted" and responses(service, "r2") == ["received", "queued", "running"]
    deliver(service, service.exec_command_topic, signal("cancel", "unknown"))
    deliver(service, service.exec_command_topic, {"command": "signal-task", "execution-unit": NAME, "signal": {"name": "cancel"}})


def test_a_signal_of_the_subsystem_reaches_its_task_and_an_unknown_one_does_not(service):
    deliver(service, service.exec_command_topic, request())
    service.pool.step()
    deliver(service, service.exec_command_topic, signal("start", data={"at": 3}))
    deliver(service, service.exec_command_topic, signal("explode"))
    service.processes["r1"].work()
    service.pool.step()
    assert [(message["signal"], message["data"]) for message in published(service, "sensor/answers")] == [("start", {"at": 3})]


def test_the_heartbeat_says_what_the_subsystem_offers_runs_and_has_waiting(service):
    for request_id in ("r1", "r2", "r3"):
        deliver(service, service.exec_command_topic, request(request_id, f"u-{request_id}"))
    service.pool.step()
    service.client.published.clear()
    service.publish_heartbeat_and_sensor_info()
    [heartbeat], [sensor_info], [execution] = published(service, "heartbeat"), published(service, "sensor/sensor_info"), published(service, "direct_execution")
    assert (heartbeat["name"], heartbeat["agent-description"], heartbeat["type"]) == (NAME, "Echo Subsystem", "HeartBeat")
    assert sensor_info["sensor-data-provided"] == ["result", "answers"]
    assert execution["tasks-available"] == [{"name": "echo", "signals": ["cancel", "start"]}] and execution["pool-size"] == 2
    assert [task["uuid"] for task in execution["tasks-executing"]] == ["u-r1", "u-r2"] and [task["uuid"] for task in execution["tasks-queued"]] == ["u-r3"]


def test_a_stream_the_subsystem_does_not_name_is_not_published(service):
    def stray(task, channel):
        channel.emit("somewhere", {"x": 1})

    service.pool.worker = stray
    deliver(service, service.exec_command_topic, request())
    service.pool.step()
    service.processes["r1"].work()
    service.pool.step()
    assert not [topic for topic, _ in service.client.published if "somewhere" in topic]


# A subsystem with more than one kind of request


class TwoRequestService(EchoService):
    """Takes echo and shout; a shout's tasks are marked, so the worker and the heartbeat can tell them from an echo's."""

    task_names = ("echo", "shout")

    def make_tasks_of(self, name: str, task_uuid: str, request_id: str, seed: int, params: Mapping[str, Any]) -> List[PoolTask]:
        tasks = self.make_tasks(task_uuid, request_id, seed, params)
        return [PoolTask(sender=f"{task.sender}!", task_uuid=task.task_uuid, request_id=task.request_id, seed=task.seed) for task in tasks] if name == "shout" else tasks

    def task_name_of(self, task: PoolTask) -> str:
        return "shout" if task.sender.endswith("!") else "echo"


def test_a_subsystem_with_two_kinds_of_request_takes_both_and_is_told_which_one_it_is():
    processes: Dict[str, Any] = {}
    service = offline(TwoRequestService(CONNECTION, GEOFENCE, 2, NAME, pool_factory=manual_pool_factory(processes)))
    assert service.requests == ("echo", "shout")
    deliver(service, service.exec_command_topic, request("r1", "u1", task="echo"))
    deliver(service, service.exec_command_topic, request("r2", "u2", task="shout"))
    deliver(service, service.exec_command_topic, request("r3", "u3", task="whisper"))
    assert [(task.request_id, service.task_name_of(task)) for task in service.current_tasks] == [("r1", "echo"), ("r2", "shout")], "a name it does not take is not its request"
    service.pool.step()
    service.publish_heartbeat_and_sensor_info()
    info = [message for topic, message in service.client.published if topic == service.direct_execution_topic][-1]
    assert info["tasks-available"] == [{"name": "echo", "signals": ["cancel", "start"]}, {"name": "shout", "signals": ["cancel", "start"]}]
    assert info["tasks-executing"] == [{"name": "echo", "uuid": "u1"}, {"name": "shout", "uuid": "u2"}]


def test_a_subsystem_with_one_kind_of_request_names_it_alone(service):
    assert service.requests == ("echo",) and service.task_name_of(service.make_tasks("u", "r", 1, {})[0]) == "echo"
