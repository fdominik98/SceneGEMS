"""design_space_exploration: its payload, and the job against the design space exploration subsystem in process.

The job talks to the real exploration service and its real worker; only the broker, the worker process and the
generator are replaced (in_process_subsystem.py, the stand-in generator of the subsystem's tests), so what the
job sends is what the subsystem takes. The run in the real image is in test_jobs_in_containers.py.
"""

import json
import threading

import pytest
from pydantic import ValidationError

from scenegems_tool.cluster.protocol.artifacts import ArtifactContent, ArtifactKind, ArtifactRef, store_results
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs import design_space_exploration_job
from scenegems_tool.cluster.worker_node.jobs.design_space_exploration_job import DesignSpaceExplorationPayload, design_space_of
from scenegems_tool.cluster.worker_node.jobs.job_types import artifact_result_fields, payload_components
from scenegems_tool.cluster.worker_node.jobs.pool_client import PoolReply
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.messaging.mqtt_design_space_exploration_service import REQUEST_FIELDS, MqttDesignSpaceExplorationService
from scenegems_tool.subsystems.design_space_exploration.design_space import explored_fecs
from scenegems_tool.subsystems.design_space_exploration.design_space_exploration_worker import explore
from tests.scenegems_tool.cluster.worker_node.jobs.in_process_subsystem import REQUEST, InProcessSubsystem
from tests.scenegems_tool.subsystems.design_space_exploration.generator_fakes import MODEL, NAMED_MODEL, STAND_IN_COMMAND, generated

POOL_NAME = "design-space-exploration-subsystem-3"  # the worker node's pool as the control node numbered it
# The fields the generator rejects everything else next to (scenegems/README.md of the Refinery repository)
GENERATOR_FIELDS = {"problem", "max_models", "scopes", "scope_overrides", "random_seed", "timeout_s", "load_timeout_s", "state_coder_depth", "status_interval_s", "include_sources"}
RESULT_KEYS = {"stop_reason", "complete", "models_found", "max_models", "random_seed", "elapsed_s", "message", "fecs", "functional_scenarios"}


class _Report:
    def __init__(self):
        self.statuses = []

    def status(self, message, progress=None):
        self.statuses.append((message, progress))


# The payload


def test_the_payload_has_only_fields_the_generator_knows():
    assert set(DesignSpaceExplorationPayload.model_fields) <= GENERATOR_FIELDS
    payload = DesignSpaceExplorationPayload(problem="class A.")
    assert payload.model_dump(mode="json", exclude_none=True) == {
        "problem": "class A.",
        "scopes": [],
        "scope_overrides": [],
        "random_seed": 1,
        "timeout_s": 600.0,
        "load_timeout_s": 120.0,
        "status_interval_s": 1.0,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"problem": ""},
        {"problem": "  \n"},
        {"problem": "class A.", "max_models": 0},
        {"problem": "class A.", "timeout_s": 0},
        {"problem": "class A.", "random_seed": -1},
        {"problem": "class A.", "include_sources": False},
        {"problem": "class A.", "scope": "A = 1"},
    ],
)
def test_a_payload_the_generator_would_refuse_or_that_leaves_the_sources_out_is_refused(payload):
    with pytest.raises(ValidationError):
        payload_components(JobType.DESIGN_SPACE_EXPLORATION, payload)


def test_the_job_needs_the_design_space_exploration_component():
    assert payload_components(JobType.DESIGN_SPACE_EXPLORATION, {"problem": "class A.", "scopes": ["A=1"]}) == ("design_space_exploration",)


def test_the_request_names_every_field_of_the_payload_but_the_seed_which_is_the_requests():
    payload = DesignSpaceExplorationPayload(
        problem="class A.", scopes=["A=1"], scope_overrides=["B=0"], max_models=5, timeout_s=30, load_timeout_s=20, state_coder_depth=6, status_interval_s=0.5, random_seed=9
    )
    params = design_space_exploration_job.request_params(payload)
    assert params == {"problem": "class A.", "scopes": ["A=1"], "scope-overrides": ["B=0"], "max-models": 5, "timeout": 30.0, "load-timeout": 20.0, "state-coder-depth": 6, "status-interval": 0.5}
    assert set(params) == REQUEST_FIELDS, "the subsystem knows every field the job sends, and the job sends every field it takes"
    assert "max-models" not in design_space_exploration_job.request_params(DesignSpaceExplorationPayload(problem="class A.")), "no cap: every model"


def test_each_functional_scenario_is_stored_as_an_artifact_of_its_own():
    fields = artifact_result_fields(JobType.DESIGN_SPACE_EXPLORATION)
    assert [(field.name, field.kind, field.content, field.many) for field in fields] == [("functional_scenarios", ArtifactKind.FUNCTIONAL_SCENARIO, ArtifactContent.TEXT, True)]
    stored_bytes = []

    def put(field, data):
        stored_bytes.append(data)
        return ArtifactRef(sha256=f"{len(stored_bytes):064x}", size_bytes=len(data), kind=field.kind, media_type="text/plain; charset=utf-8")

    stored = store_results(design_space_of({"design-space": explored_fecs(generated([MODEL, "class B.\n"])), "error": None}), fields, put)
    assert stored_bytes == [NAMED_MODEL.encode("utf-8"), b"class B.\n"]
    assert [item["sha256"] for item in stored["functional_scenarios"]] == [f"{1:064x}", f"{2:064x}"]
    assert stored["fecs"][0]["vessel_count"] == 3


# The job on the subsystem


@pytest.fixture
def subsystem(monkeypatch, worker_node):
    """The worker node's design space exploration pool, in process: an exploration runs, with the stand-in generator, as soon as its request is in."""
    made = InProcessSubsystem(MqttDesignSpaceExplorationService, POOL_NAME).serve(monkeypatch, worker_node)
    made.service.pool.worker = lambda task, channel: explore(task, channel, command=STAND_IN_COMMAND, pool_size=1)
    made.hooks[REQUEST] = made.work
    return made


@pytest.fixture
def explore_job(subsystem, worker_node, make_job):
    """Run a design_space_exploration job with this payload on the subsystem."""

    def run(payload, report=None, cancel=None):
        return design_space_exploration_job.run(make_job(JobType.DESIGN_SPACE_EXPLORATION, payload), worker_node, report or _Report(), cancel)

    return run


def test_the_job_is_one_request_and_its_result_is_the_explored_design_space(explore_job, subsystem):
    result = explore_job({"problem": "class A.", "scopes": ["A=1"]})
    assert subsystem.asked == [Subsystem.DESIGN_SPACE_EXPLORATION]
    [(params, seed)] = subsystem.requests()
    assert params == {"problem": "class A.", "scopes": ["A=1"], "scope-overrides": [], "timeout": 600.0, "load-timeout": 120.0, "status-interval": 1.0}
    assert seed == 1, "a job that names no seed explores in the order of seed 1"
    assert set(result) == RESULT_KEYS
    assert result["functional_scenarios"] == [NAMED_MODEL, NAMED_MODEL]
    assert result["fecs"] == [{"index": 0, "vessel_count": 3, "obstacle_count": 1}, {"index": 1, "vessel_count": 3, "obstacle_count": 1}]
    assert (result["stop_reason"], result["complete"], result["models_found"], result["random_seed"]) == ("exhausted", True, 2, 1)
    assert subsystem.states("job-1-1") == ["received", "queued", "running", "finished"] and subsystem.cancels() == []


def test_the_jobs_seed_and_limits_reach_the_generator(explore_job):
    result = explore_job({"problem": "class A.", "scopes": ["A=1"], "max_models": 3, "timeout_s": 30, "random_seed": 9})
    assert json.loads(result["message"]) == {
        "problem": "class A.",
        "scopes": ["A=1"],
        "scope_overrides": [],
        "random_seed": 9,
        "max_models": 3,
        "timeout_s": 30.0,
        "load_timeout_s": 120.0,
        "status_interval_s": 1.0,
    }
    assert (result["models_found"], result["random_seed"], result["stop_reason"], result["complete"]) == (3, 9, "cap_reached", False)


def test_the_generators_progress_is_the_jobs_status(explore_job):
    report = _Report()
    explore_job({"problem": "class A."}, report)
    assert [status for status in report.statuses if not status[0].startswith("waiting")] == [("loading the problem", None), ("generating models: 1 of 2 found", 0.5), ("finished: 2 models", 1.0)]


def test_a_problem_the_generator_cannot_explore_fails_the_job_for_good_with_the_generators_reason(explore_job, subsystem):
    with pytest.raises(JobFailed, match="the problem has errors: line 1: no such class Missing") as failure:
        explore_job({"problem": "// stand-in: error\nclass A extends Missing."})
    assert not failure.value.retryable, "another attempt fails the same way"
    assert subsystem.states("job-1-1")[-1] == "finished" and subsystem.cancels() == []


def test_a_generator_that_dies_fails_the_attempt_which_may_be_retried(explore_job, subsystem):
    with pytest.raises(JobFailed, match="The task of the design space exploration pool failed: GeneratorFailed: the model generator ended with exit code 3") as failure:
        explore_job({"problem": "// stand-in: crash\nclass A."})
    assert failure.value.retryable and subsystem.cancels() == []


def test_a_cancelled_job_cancels_its_own_exploration_which_ends_its_generator(explore_job, subsystem):
    cancel = threading.Event()
    subsystem.hooks[REQUEST] = lambda request_id: cancel.set()  # the lease is cancelled while the generator works
    with pytest.raises(JobFailed, match="cancelled") as failure:
        explore_job({"problem": "// stand-in: hang\nclass A."}, cancel=cancel)
    assert not failure.value.retryable and subsystem.cancels() == ["job-1-1"]
    subsystem.work("job-1-1")
    assert subsystem.states("job-1-1")[-1] == "aborted"


def test_the_job_waits_for_the_generators_own_limits_and_a_margin(make_job, worker_node, monkeypatch):
    calls = {}

    def run_pool_request(job, worker_node_, report, cancel, **request):
        calls.update(request)
        return PoolReply("job-1-1", request["seed"], {"design-space": explored_fecs(generated([MODEL])), "error": None, "retryable": False, "final": True})

    monkeypatch.setattr(design_space_exploration_job, "run_pool_request", run_pool_request)
    job = make_job(JobType.DESIGN_SPACE_EXPLORATION, {"problem": "class A.", "scopes": ["A=1"], "max_models": 5, "timeout_s": 30, "random_seed": 4})
    result = design_space_exploration_job.run(job, worker_node, report=None)
    assert calls["timeout_s"] == 120.0 + 30 + 60.0  # the load limit, the generation limit and the margin
    assert (calls["subsystem"], calls["task_name"], calls["streams"], calls["seed"], calls["relay_feedback"]) == (
        Subsystem.DESIGN_SPACE_EXPLORATION,
        "explore-design-space",
        ("design_space",),
        4,
        True,
    )
    assert calls["is_result"]("design_space", {"final": True}) and result["functional_scenarios"] == [NAMED_MODEL]


@pytest.mark.parametrize("message", [{"design-space": None, "error": None}, {"final": True}, {"design-space": "text"}])
def test_an_answer_without_a_design_space_fails_for_good(message):
    with pytest.raises(JobFailed, match="without a design space") as failure:
        design_space_of(message)
    assert not failure.value.retryable


def test_the_subsystems_error_keeps_whether_it_may_be_retried():
    for retryable in (False, True):
        with pytest.raises(JobFailed, match="out of memory") as failure:
            design_space_of({"design-space": None, "error": "out of memory", "retryable": retryable})
        assert failure.value.retryable is retryable
