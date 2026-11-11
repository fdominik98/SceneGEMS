"""monitoring.post_hoc against the monitoring subsystem in process: the series the job sends, the result shape the pipeline reads, frames on request, and a scene judged as a one-scene log.

The job talks to the real monitoring service and its real worker; only the broker and the worker process are
replaced (MonitoringSubsystem below), so what the job sends is what the subsystem takes.
"""

import math
import threading
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest
from pydantic import ValidationError

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_scene import ConcreteScene
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs import monitoring_post_hoc_job
from scenegems_tool.cluster.worker_node.jobs.job_payload import validate_structure
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.messaging import mqtt_pool_client
from scenegems_tool.messaging.mqtt_monitor_service import MqttMonitoringService
from scenegems_tool.subsystems.pool.pool_task import MAX_SEED, TaskState
from scenegems_tool.vessel_stack.calibration.reference_scenarios import make_vessel
from tests.scenegems_tool.messaging.generation_fakes import CONNECTION, GEOFENCE, deliver, offline
from tests.scenegems_tool.subsystems.pool.pool_fakes import manual_pool_factory

POOL_NAME = "monitoring-subsystem-3"  # the worker node's pool as the control node numbered it
POOL_TOPIC = f"waraps/service/virtual/real/{POOL_NAME}"
RESULT_KEYS = {"scenes", "monitored_scenes", "time_step", "rules", "failed_rules", "encounters", "encounter_roles", "passed", "seed"}


class _Report:
    def __init__(self):
        self.messages = []

    def status(self, message, progress=None):
        self.messages.append(message)


class MonitoringSubsystem:
    """The monitoring service with a pool whose workers run when the test says so, and what happened in it (events).

    A series' worker runs when its close signal arrives, on the signals sent until then; `on_close` replaces that.
    """

    def __init__(self, max_workers: int = 1):
        self.processes: Dict[str, Any] = {}
        self.service = offline(MqttMonitoringService(CONNECTION, GEOFENCE, max_workers, name=POOL_NAME, pool_factory=manual_pool_factory(self.processes)))
        self.clients: List["PoolClient"] = []
        self.events: List[tuple] = []  # ("request", params), ("state", request id, state), ("signal", name, data), ("cancel", request id)
        self.on_close = self.work
        self.on_scenes = lambda request_id: None
        self._relayed = 0
        self._lock = threading.RLock()

    def command(self, command: Dict[str, Any]) -> None:
        with self._lock:
            deliver(self.service, self.service.exec_command_topic, {"execution-unit": POOL_NAME, **command})
            self.relay()

    def work(self, request_id: str) -> None:
        """Let the series' worker run to its end, as its process would."""
        with self._lock:
            self.processes[request_id].work()
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
                for client in self.clients:
                    client.receive(topic, message)

    def signals(self, name: str) -> List[Any]:
        return [data for kind, signal, data in (event for event in self.events if event[0] == "signal") if signal == name]

    def states(self, request_id: str) -> List[str]:
        return [state for kind, request, state in (event for event in self.events if event[0] == "state") if request == request_id]


class PoolClient:
    """Stands in for the job's pool client: what the job publishes goes straight to the subsystem, what the subsystem publishes comes straight back."""

    subsystem: MonitoringSubsystem
    is_connected = is_heartbeat_valid = True

    def __init__(self, mqtt_connection, topic, reference_geofence, service_name, *, streams=(), on_state=None, on_stream=None):
        assert (topic, service_name) == (POOL_TOPIC, POOL_NAME), "the job talks to its own worker node's pool"
        self.streams, self.on_state, self.on_stream = streams, on_state, on_stream
        self.subsystem.clients.append(self)

    def connect(self):
        pass

    def disconnect(self):
        pass

    def receive(self, topic: str, message: Dict[str, Any]) -> None:
        service = self.subsystem.service
        if topic == service.exec_response_topic:
            self.on_state(message["request-id"], TaskState(message["response"]), message["fail-reason"], message["seed"])
        for stream in self.streams:
            if topic == service.stream_topic(stream):
                self.on_stream(stream, message)

    def publish_start_task(self, task_name, request_id, params, seed):
        self.subsystem.events.append(("request", dict(params), seed))
        self.subsystem.command({"command": "start-task", "task-uuid": f"u-{request_id}", "task": {"name": task_name, "params": {**params, "request-id": request_id, "seed": seed}}})
        return f"u-{request_id}"

    def publish_signal(self, signal_name, request_id, data=None):
        self.subsystem.events.append(("signal", signal_name, data))
        self.subsystem.command({"command": "signal-task", "signal": {"name": signal_name, "request-id": request_id, "data": data}})
        if signal_name == "scenes":
            self.subsystem.on_scenes(request_id)
        if signal_name == "close":
            self.subsystem.on_close(request_id)

    def publish_cancel(self, request_id):
        self.subsystem.events.append(("cancel", request_id))
        self.subsystem.command({"command": "signal-task", "signal": {"name": "cancel", "request-id": request_id}})


@pytest.fixture
def subsystem(monkeypatch, worker_node):
    """The worker node's monitoring pool, in process."""
    made = MonitoringSubsystem()
    monkeypatch.setattr(mqtt_pool_client, "MqttPoolClient", type("Client", (PoolClient,), {"subsystem": made}))
    asked = []

    def pool_of(subsystem):
        asked.append(subsystem)
        return SimpleNamespace(mqtt_connection=worker_node.mqtt_connection, service_name=POOL_NAME, service_topic=POOL_TOPIC)

    monkeypatch.setattr(worker_node, "pools", SimpleNamespace(get=pool_of))
    made.asked = asked
    return made


@pytest.fixture
def judge(subsystem, worker_node, make_job):
    """Run a monitoring.post_hoc job with this payload on the subsystem."""

    def run(payload, report=None, cancel=None, **job):
        return monitoring_post_hoc_job.run(make_job(JobType.MONITORING_POST_HOC, payload, **job), worker_node, report or _Report(), cancel)

    return run


def test_the_result_summarizes_the_rules(judge, subsystem, head_on_trajectories):
    result = judge({"trajectories": head_on_trajectories.to_dict()})
    assert set(result) == RESULT_KEYS and subsystem.asked == [Subsystem.MONITORING]
    assert (result["scenes"], result["monitored_scenes"], result["time_step"]) == (121, 121, 1)
    assert not result["passed"]
    assert {(item["rule"], item["first_failed_at"]) for item in result["failed_rules"]} == {
        ("Rule 16: Give-Way Vessel Takes Early and Substantial Action (os)", 61),
        ("Rule 16: Give-Way Vessel Takes Early and Substantial Action (ts1)", 61),
    }
    for item in result["failed_rules"]:
        assert result["rules"][item["relation"]][item["rule"]]["failed"] == item["first_failed_at"]
    assert result["encounters"] == {"os - ts1": ["HEAD_ON"]}  # keyed like rules
    assert result["encounter_roles"] == {"os - ts1": {"HEAD_ON": {"give_way": ["os", "ts1"], "stand_on": []}}}
    assert all(set(item) == {"relation", "rule", "first_failed_at"} for item in result["failed_rules"])
    assert [item["first_failed_at"] for item in result["failed_rules"]] == sorted(item["first_failed_at"] for item in result["failed_rules"])


def test_the_job_is_one_request_then_the_scenes_in_batches_in_time_order_then_the_close(judge, subsystem, head_on_trajectories):
    report = _Report()
    result = judge({"trajectories": head_on_trajectories.to_dict(), "scenario_id": "case-1#run0", "colregs_constraints_content": None}, report)
    [(_, params, seed)] = [event for event in subsystem.events if event[0] == "request"]
    assert params == {"scenario-id": "case-1#run0", "time-step": 1, "colregs-constraints-content": None, "include-frames": False}
    assert 0 <= seed <= MAX_SEED and result["seed"] == seed, "every request carries a seed, and the result names it"
    first, second = subsystem.signals("scenes")
    assert (first["index"], first["first-timestamp"], len(first["scenes"])) == (0, 0, 100)
    assert (second["index"], second["first-timestamp"], len(second["scenes"])) == (1, 100, 21)
    assert first["scenes"] + second["scenes"] == head_on_trajectories.to_dict()["scene_list"]
    assert subsystem.signals("close") == [{"batches": 2}]
    kinds = [event[0] if event[0] != "state" else event[2] for event in subsystem.events]
    assert kinds == ["request", "received", "queued", "running", "signal", "signal", "signal", "finished"], "nothing is sent before the task runs"
    assert [message for message in report.messages if message.startswith("monitored")] == ["monitored 100 of 121 scenes", "monitored 121 of 121 scenes"]
    assert not [event for event in subsystem.events if event[0] == "cancel"]


def test_a_job_without_a_scenario_is_a_scenario_of_its_own(judge, subsystem, head_on_trajectories):
    """Two direct jobs never wait for each other: each is ordered by its own request id."""
    result = judge({"trajectories": head_on_trajectories.to_dict(), "include_frames": True}, job_id="abc", attempt=2)
    [(_, params, _)] = [event for event in subsystem.events if event[0] == "request"]
    assert params["scenario-id"] == "abc-2"
    assert {frame["scenarioId"] for frame in result["frames"]} == {"abc-2"}


def test_frames_are_added_on_request_in_time_order(judge, head_on_trajectories):
    result = judge({"trajectories": head_on_trajectories.to_dict(), "include_frames": True, "scenario_id": "case-1"})
    assert len(result["frames"]) == result["monitored_scenes"] == 121
    assert [frame["timestamp"] for frame in result["frames"]] == list(range(121)) and {frame["scenarioId"] for frame in result["frames"]} == {"case-1"}
    assert "frames" not in judge({"trajectories": head_on_trajectories.to_dict()}, job_id="job-2")


def test_the_series_waits_in_the_queue_behind_another_series_of_its_scenario(judge, subsystem, head_on_trajectories):
    """The pool keeps two series of one scenario apart; the job sends its scenes only once its own task runs."""
    subsystem.service.pool.size = 2
    subsystem.command(
        {
            "command": "start-task",
            "task-uuid": "u-earlier",
            "task": {"name": "monitor-scenario", "params": {"scenario-id": "case-1", "time-step": 1, "colregs-constraints-content": None, "request-id": "earlier"}},
        }
    )
    subsystem.command({"command": "signal-task", "signal": {"name": "close", "request-id": "earlier"}})
    client_class = mqtt_pool_client.MqttPoolClient
    start_task = client_class.publish_start_task

    def start_then_end_the_earlier_series(self, *arguments):
        task_uuid = start_task(self, *arguments)
        assert subsystem.states("job-1-1") == ["received", "queued"] and subsystem.signals("scenes") == []
        threading.Thread(target=subsystem.work, args=("earlier",)).start()  # the earlier series ends while the job waits
        return task_uuid

    client_class.publish_start_task = start_then_end_the_earlier_series
    result = judge({"trajectories": head_on_trajectories.to_dict(), "scenario_id": "case-1"})
    assert result["scenes"] == 121
    assert subsystem.states("earlier")[-1] == "finished" and subsystem.states("job-1-1") == ["received", "queued", "running", "finished"]
    events = subsystem.events
    first_scenes = next(index for index, event in enumerate(events) if event[:2] == ("signal", "scenes"))
    assert events.index(("state", "earlier", "finished")) < events.index(("state", "job-1-1", "running")) < first_scenes


def test_a_task_that_fails_fails_the_attempt_with_the_subsystems_reason(judge, subsystem, head_on_trajectories):
    def lose_the_worker(request_id):
        subsystem.processes[request_id].die()
        subsystem.relay()

    subsystem.on_close = lose_the_worker
    with pytest.raises(JobFailed, match="The task of the monitoring pool failed: the worker process ended without a result") as failure:
        judge({"trajectories": head_on_trajectories.to_dict()})
    assert failure.value.retryable and not [event for event in subsystem.events if event[0] == "cancel"], "the task is over: there is nothing to cancel"


def test_a_cancelled_job_stops_sending_and_cancels_its_own_series(judge, subsystem, head_on_trajectories):
    cancel = threading.Event()
    subsystem.on_scenes = lambda request_id: cancel.set()  # the lease is cancelled while the job sends its scenes
    with pytest.raises(JobFailed, match="cancelled") as failure:
        judge({"trajectories": head_on_trajectories.to_dict()}, cancel=cancel)
    assert not failure.value.retryable
    assert len(subsystem.signals("scenes")) == 1 and subsystem.signals("close") == []
    assert ("cancel", "job-1-1") in subsystem.events and subsystem.states("job-1-1")[-1] == "running"
    subsystem.work("job-1-1")
    assert subsystem.states("job-1-1")[-1] == "aborted", "the worker sees the cancel and ends its series"


def test_an_unresolved_state_log_fails_for_good(judge, subsystem):
    with pytest.raises(JobFailed) as failure:
        judge({"trajectories": {"sha256": "ab" * 32, "size_bytes": 1, "kind": "trajectories"}})
    assert not failure.value.retryable and subsystem.events == [], "nothing is asked of the pool"


def _scene(head_on_trajectories):
    return head_on_trajectories.scene_list[0].to_dict()


@pytest.mark.parametrize("document", ["evaluation_data", "scene", "initial_scene"])
def test_a_scene_is_judged_as_a_one_scene_log(judge, subsystem, head_on_trajectories, document):
    scene = _scene(head_on_trajectories)
    payload = {"scene": {"best_scene": scene, "random_seed": 3} if document == "evaluation_data" else (scene if document == "scene" else {"initial_scene": scene})}
    result = judge(payload)
    assert set(result) == RESULT_KEYS
    assert (result["scenes"], result["monitored_scenes"], result["time_step"]) == (1, 1, 1)
    # the pair is 3 km apart: the rules on the motion stay unknown and SafeDistance holds, so nothing fails
    assert result["passed"] and result["failed_rules"] == [] and isinstance(result["rules"], dict)
    assert result["encounters"] == {"os - ts1": ["HEAD_ON"]}  # the scene's type per pair
    assert result["encounter_roles"] == {"os - ts1": {"HEAD_ON": {"give_way": ["os", "ts1"], "stand_on": []}}}  # known without any decided rule
    [batch] = subsystem.signals("scenes")
    assert (batch["index"], batch["first-timestamp"], batch["scenes"]) == (0, 0, [scene]) and subsystem.signals("close") == [{"batches": 1}]


def _scene_at(distance):
    """The head-on pair of head_on_trajectories, `distance` apart (safety radius 120 m)."""
    scene = ConcreteScene({make_vessel(0, True): ActorState(0.0, 0.0, 8.0, 0.0), make_vessel(1, False): ActorState(distance, 0.0, 8.0, math.pi)})
    return scene.to_dict()


def test_a_scene_starting_inside_the_safe_distance_fails_at_0(judge):
    result = judge({"scene": _scene_at(80.0)})
    assert not result["passed"]
    assert result["failed_rules"] == [{"relation": "os - ts1", "rule": "Rule 8(d): Passing at a Safe Distance (os - ts1)", "first_failed_at": 0}]
    assert result["encounters"] == {"os - ts1": ["OTHER"]}  # inside its encounter's own domain a pair is OTHER
    assert result["encounter_roles"] == {}


def test_the_roles_come_from_the_encounter_not_from_the_order_of_the_relation(judge):
    """The target ship has the own ship on its starboard bow, so it gives way, though the relation names the own ship first."""
    scene = ConcreteScene({make_vessel(0, True): ActorState(0.0, 0.0, 8.0, 0.0), make_vessel(1, False): ActorState(1500.0, 1500.0, 8.0, -math.pi / 2)}).to_dict()
    result = judge({"scene": scene})
    assert result["encounters"] == {"os - ts1": ["CROSSING_FROM_PORT"]}
    assert result["encounter_roles"] == {"os - ts1": {"CROSSING_FROM_PORT": {"give_way": ["ts1"], "stand_on": ["os"]}}}


def test_a_scene_inside_the_head_on_domain_but_outside_the_circle_passes(judge):
    """The safety domain guard: inside its encounter's domain the pair is OTHER, and SafeDistance judges the default circle."""
    result = judge({"scene": _scene_at(200.0)})
    assert result["passed"] and result["failed_rules"] == []
    assert result["encounters"] == {"os - ts1": ["OTHER"]}


def test_a_scene_gets_its_frame_on_request(judge, head_on_trajectories):
    result = judge({"scene": _scene(head_on_trajectories), "include_frames": True, "scenario_id": "case-1#scene"})
    assert len(result["frames"]) == result["monitored_scenes"] == 1


@pytest.mark.parametrize("payload", [{}, {"trajectories": "both", "scene": "both"}])
def test_exactly_one_of_trajectories_and_scene(head_on_trajectories, payload):
    if payload:
        payload = {"trajectories": head_on_trajectories.to_dict(), "scene": _scene(head_on_trajectories)}
    with pytest.raises(ValidationError, match="exactly one of trajectories and scene"):
        validate_structure(monitoring_post_hoc_job.PostHocMonitoringPayload, payload)


def test_a_scenario_id_is_not_empty(head_on_trajectories):
    with pytest.raises(ValidationError, match="scenario_id"):
        validate_structure(monitoring_post_hoc_job.PostHocMonitoringPayload, {"trajectories": head_on_trajectories.to_dict(), "scenario_id": ""})


def test_a_scene_reference_is_checked_for_shape_and_must_be_resolved(judge):
    reference = {"sha256": "cd" * 32, "size_bytes": 1, "kind": "scene"}
    validate_structure(monitoring_post_hoc_job.PostHocMonitoringPayload, {"scene": reference})
    with pytest.raises(JobFailed) as failure:
        judge({"scene": reference})
    assert not failure.value.retryable


def test_a_document_without_a_scene_fails_for_good(judge, subsystem):
    with pytest.raises(JobFailed, match="holds no scene") as failure:
        judge({"scene": {"random_seed": 3}})
    assert not failure.value.retryable and subsystem.events == []
