"""scene_generation and trajectory_generation jobs against a scripted pool: the request the job sends, the result it takes and how it ends without one."""

import hashlib
import threading
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from scenegems_tool.cluster.protocol.artifacts import ArtifactRef, resolve_references
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs import pool_client, scene_generation_job, trajectory_generation_job
from scenegems_tool.cluster.worker_node.jobs.job_payload import validate_structure
from scenegems_tool.messaging import mqtt_pool_client
from scenegems_tool.subsystems.pool.pool_task import MAX_SEED, TaskState
from tests.scenegems_tool.cluster.payloads import valid_payload


class _Report:
    def __init__(self):
        self.messages = []

    def status(self, message, progress=None):
        self.messages.append(message)


POOL_NAME = "scene-generation-subsystem-3"  # the worker node's pool as the control node numbered it
POOL_TOPIC = f"scenegems/service/virtual/real/{POOL_NAME}"


class _ScriptedClient:
    """Stands in for the pool client; `answer(client, request)` plays the subsystem's replies on a thread of its own."""

    answer = None
    requests = []
    cancels = []
    ready = True  # the pool heartbeats

    def __init__(self, mqtt_connection, topic, reference_geofence, service_name, *, streams=(), on_state=None, on_stream=None):
        self.topic, self.service_name, self.streams = topic, service_name, streams
        self.on_state, self.on_stream = on_state, on_stream
        self.is_connected = self.is_heartbeat_valid = type(self).ready

    def connect(self):
        pass

    def disconnect(self):
        pass

    def publish_start_task(self, task_name, request_id, params, seed):
        request = SimpleNamespace(task_name=task_name, request_id=request_id, params=dict(params), seed=seed)
        type(self).requests.append(request)
        threading.Thread(target=type(self).answer, args=(self, request)).start()
        return "task-uuid"

    def publish_cancel(self, request_id):
        type(self).cancels.append(request_id)

    def scene(self, request_id, evaluation_data, valid=True, final=True):
        self.on_stream("generated_scene", {"request-id": request_id, "evaluation-data": evaluation_data, "valid": valid, "final": final})

    def state(self, request_id, state, reason=None):
        self.on_state(request_id, state, reason, None)


@pytest.fixture
def pool(monkeypatch, worker_node):
    def install(answer):
        client = type("Client", (_ScriptedClient,), {"answer": staticmethod(answer), "requests": [], "cancels": []})
        monkeypatch.setattr(mqtt_pool_client, "MqttPoolClient", client)
        monkeypatch.setattr(worker_node, "pools", SimpleNamespace(get=lambda subsystem: SimpleNamespace(mqtt_connection=worker_node.mqtt_connection, service_name=POOL_NAME, service_topic=POOL_TOPIC)))
        return client

    return install


def scene_job(make_job, **payload):
    return make_job(JobType.SCENE_GENERATION, valid_payload(JobType.SCENE_GENERATION, **payload))


def test_the_scene_job_sends_the_request_with_its_seed_and_takes_the_final_scene(pool, worker_node, make_job):
    def answer(client, request):
        client.scene("someone-else", {"sample": 0})
        client.scene(request.request_id, {"sample": 1}, valid=False, final=False)
        client.scene(request.request_id, {"sample": 2}, valid=False, final=False)
        client.scene(request.request_id, {"sample": 3})
        client.scene(request.request_id, {"sample": 4})  # never twice
        client.state(request.request_id, TaskState.FINISHED)

    client = pool(answer)
    report = _Report()
    result = scene_generation_job.run(scene_job(make_job, seed=17), worker_node, report)
    assert result == {"request_id": "job-1-1", "valid": True, "evaluation_data": {"sample": 3}, "seed": 17}
    [request] = client.requests
    assert (request.task_name, request.request_id, request.seed) == ("generate-scene", "job-1-1", 17)
    assert set(request.params) == {"functional-scenario-content", "colregs-constraints-content", "vessel-types-content", "obstacle-types-content", "timeout", "enforce-low-tcpa"}
    assert "search sample 2" in report.messages and client.cancels == []


def test_a_job_without_a_seed_gets_one_drawn_and_its_result_names_it(pool, worker_node, make_job):
    client = pool(lambda client, request: client.scene(request.request_id, {"sample": 1}))
    result = scene_generation_job.run(scene_job(make_job), worker_node, _Report())
    assert 0 <= result["seed"] <= MAX_SEED and client.requests[0].seed == result["seed"], "every request carries a seed"


def test_a_generation_job_talks_to_its_own_worker_nodes_pool(pool, worker_node, make_job):
    addressed = {}

    def answer(client, request):
        addressed.update(topic=client.topic, name=client.service_name, streams=client.streams)
        client.scene(request.request_id, {})

    pool(answer)
    scene_generation_job.run(scene_job(make_job, seed=1), worker_node, _Report())
    assert addressed == {"topic": POOL_TOPIC, "name": POOL_NAME, "streams": ("generated_scene",)}, "another worker node's pool never takes the task"


def test_the_trajectory_job_returns_complete(pool, worker_node, make_job):
    def answer(client, request):
        client.on_stream("planned_trajectory_preview", {"request-id": request.request_id, "trajectory-data": {}})
        client.on_stream("planned_trajectory", {"request-id": request.request_id, "trajectory-data": {"trajectories": {}}, "valid": True, "complete": False, "error-message": None})

    client = pool(answer)
    report = _Report()
    payload = valid_payload(JobType.TRAJECTORY_GENERATION, seed=3, params={"generator": "straight", "timespan": 300})
    result = trajectory_generation_job.run(make_job(JobType.TRAJECTORY_GENERATION, payload), worker_node, report)
    assert result == {"request_id": "job-1-1", "valid": True, "complete": False, "trajectory_data": {"trajectories": {}}, "error_message": None, "seed": 3}
    [request] = client.requests
    assert (request.task_name, request.seed) == ("generate-trajectories", 3)
    assert request.params["params"]["generator"] == "straight" and request.params["params"]["timespan"] == 300.0
    assert "search preview 1" in report.messages
    assert client.cancels == []  # the search ended on its own


def test_a_search_that_plans_nothing_is_a_result_not_a_failed_job(pool, worker_node, make_job):
    def answer(client, request):
        client.on_stream("planned_trajectory", {"request-id": request.request_id, "trajectory-data": None, "valid": False, "complete": False, "error-message": "No trajectory could be planned"})

    pool(answer)
    result = trajectory_generation_job.run(make_job(JobType.TRAJECTORY_GENERATION, valid_payload(JobType.TRAJECTORY_GENERATION, seed=3)), worker_node, _Report())
    assert (result["valid"], result["trajectory_data"], result["error_message"]) == (False, None, "No trajectory could be planned")


@pytest.mark.parametrize(
    "state, reason, expected",
    [
        (TaskState.FAILED, "the worker process ended without a result", "The task of the scene generation pool failed: the worker process ended without a result"),
        (TaskState.FAILED, "the request was refused: missing 'timeout'", "failed: the request was refused"),
        (TaskState.ABORTED, None, "The task of the scene generation pool was aborted"),
    ],
)
def test_a_task_that_fails_or_is_aborted_fails_the_attempt_at_once_with_the_subsystems_reason(pool, worker_node, make_job, state, reason, expected):
    client = pool(lambda client, request: client.state(request.request_id, state, reason))
    with pytest.raises(JobFailed, match=expected) as failure:
        scene_generation_job.run(scene_job(make_job, seed=1), worker_node, _Report())
    assert failure.value.retryable and client.cancels == [], "the task is over: there is nothing to cancel"


def test_a_task_that_finishes_without_a_result_fails_the_attempt(pool, worker_node, make_job, monkeypatch):
    monkeypatch.setattr(pool_client, "RESULT_GRACE_S", 0.0)
    pool(lambda client, request: client.state(request.request_id, TaskState.FINISHED))
    with pytest.raises(JobFailed, match="it finished without a result"):
        scene_generation_job.run(scene_job(make_job, seed=1), worker_node, _Report())


def test_another_requests_states_are_not_this_jobs(pool, worker_node, make_job):
    def answer(client, request):
        client.state("someone-else", TaskState.FAILED, "not ours")
        client.scene(request.request_id, {"sample": 1})

    pool(answer)
    assert scene_generation_job.run(scene_job(make_job, seed=1), worker_node, _Report())["valid"]


def test_a_cancelled_trajectory_job_cancels_its_own_search_only(pool, worker_node, make_job):
    cancel = threading.Event()
    client = pool(lambda client, request: cancel.set())  # the lease is cancelled mid-search
    with pytest.raises(JobFailed, match="cancelled"):
        trajectory_generation_job.run(make_job(JobType.TRAJECTORY_GENERATION, valid_payload(JobType.TRAJECTORY_GENERATION)), worker_node, _Report(), cancel)
    assert client.cancels == ["job-1-1"]


def test_a_job_cancelled_before_its_search_started_sends_no_cancel(pool, worker_node, make_job):
    cancel = threading.Event()
    cancel.set()
    client = pool(lambda client, request: None)
    client.ready = False  # cancelled while the job waits for the pool's heartbeat
    with pytest.raises(JobFailed, match="cancelled"):
        trajectory_generation_job.run(make_job(JobType.TRAJECTORY_GENERATION, valid_payload(JobType.TRAJECTORY_GENERATION)), worker_node, _Report(), cancel)
    assert client.requests == [] and client.cancels == []


def test_a_cancelled_scene_job_cancels_its_own_generation_only(pool, worker_node, make_job):
    cancel = threading.Event()
    client = pool(lambda client, request: cancel.set())  # the lease is cancelled mid-generation
    with pytest.raises(JobFailed, match="cancelled"):
        scene_generation_job.run(scene_job(make_job), worker_node, _Report(), cancel)
    assert client.cancels == ["job-1-1"]


def test_a_scene_job_cancelled_before_its_generation_started_sends_no_cancel(pool, worker_node, make_job):
    cancel = threading.Event()
    cancel.set()
    client = pool(lambda client, request: None)
    client.ready = False  # cancelled while the job waits for the pool's heartbeat
    with pytest.raises(JobFailed, match="cancelled"):
        scene_generation_job.run(scene_job(make_job), worker_node, _Report(), cancel)
    assert client.requests == [] and client.cancels == []


def _scenario_reference(text: str):
    data = text.encode("utf-8")
    reference = {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data), "kind": "functional_scenario", "media_type": "text/plain; charset=utf-8"}
    return reference, {reference["sha256"]: data}


def test_the_scene_job_takes_the_scenario_as_a_reference_the_worker_node_resolves(pool, worker_node, make_job):
    client = pool(lambda client, request: client.scene(request.request_id, {"sample": 1}))
    text = valid_payload(JobType.SCENE_GENERATION)["functional_scenario_content"]
    reference, stored = _scenario_reference(text)
    payload = valid_payload(JobType.SCENE_GENERATION, functional_scenario_content=reference, seed=5)
    validate_structure(scene_generation_job.SceneGenerationPayload, payload)  # the control node checks the reference's shape only
    resolved = resolve_references(payload, scene_generation_job.ARTIFACT_INPUT_FIELDS, lambda ref: stored[ref.sha256])
    assert resolved["functional_scenario_content"] == text
    result = scene_generation_job.run(make_job(JobType.SCENE_GENERATION, resolved), worker_node, _Report())
    assert result["valid"] and client.requests[0].params["functional-scenario-content"] == text


def test_an_unresolved_scenario_reference_fails_for_good(make_job, worker_node):
    reference, _ = _scenario_reference("not used")
    with pytest.raises(JobFailed) as failure:
        scene_generation_job.run(make_job(JobType.SCENE_GENERATION, valid_payload(JobType.SCENE_GENERATION, functional_scenario_content=reference)), worker_node, _Report())
    assert not failure.value.retryable and "still holds artifact references" in str(failure.value)


def test_a_resolved_scenario_must_parse():
    reference, stored = _scenario_reference("this is not a functional scenario")
    resolved = resolve_references(valid_payload(JobType.SCENE_GENERATION, functional_scenario_content=reference), scene_generation_job.ARTIFACT_INPUT_FIELDS, lambda ref: stored[ref.sha256])
    with pytest.raises(ValidationError, match="does not parse"):
        validate_structure(scene_generation_job.SceneGenerationPayload, resolved)
    assert isinstance(ArtifactRef.model_validate(reference), ArtifactRef)
