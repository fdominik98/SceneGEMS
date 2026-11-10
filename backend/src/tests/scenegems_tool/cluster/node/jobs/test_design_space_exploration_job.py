"""design_space_exploration: its payload, the result it makes of the generator's, how it starts the generator, and a run in the real image."""

import os
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from functional_level.models.model_parser import ModelParser
from scenegems_tool.cluster.node.job_report import JobFailed
from scenegems_tool.cluster.node.jobs import design_space_exploration_job
from scenegems_tool.cluster.node.jobs.design_space_exploration_job import DesignSpaceExplorationPayload, exploration_result
from scenegems_tool.cluster.node.jobs.job_runner import run_job
from scenegems_tool.cluster.node.jobs.job_types import artifact_result_fields, payload_components
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.node.subsystem import IMAGE_ENVIRONMENT_VARIABLES, Subsystem, subsystem_image
from scenegems_tool.cluster.protocol.artifacts import ArtifactContent, ArtifactKind, ArtifactRef, store_results
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.messages import LogStream
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.subsystems.design_space_exploration.design_space import default_specification, parse_scope
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

MODEL = (Path(__file__).parents[3] / "subsystems" / "design_space_exploration" / "data" / "generated_model.problem").read_text(encoding="utf-8")
# The fields the generator rejects everything else next to (scenegems/README.md of the Refinery repository)
GENERATOR_FIELDS = {"problem", "max_models", "scopes", "scope_overrides", "random_seed", "timeout_s", "load_timeout_s", "state_coder_depth", "status_interval_s", "include_sources"}


def _generated(models, **summary):
    result = {"stop_reason": "exhausted", "complete": True, "models_found": len(models), "max_models": None, "random_seed": 1, "elapsed_s": 1.5, "message": None}
    result.update(summary)
    result["models"] = [{"index": index, "file": f"models/model_{index:05d}.problem", "source": source} for index, source in enumerate(models)]
    return result


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


def test_the_result_lists_the_models_as_functional_scenarios_with_their_counts():
    result = exploration_result(_generated([MODEL, MODEL.replace("\n", "\r\n")], stop_reason="cap_reached", complete=False, max_models=2))
    assert result["functional_scenarios"] == [MODEL, MODEL]
    assert result["fecs"] == [{"index": 0, "vessel_count": 3, "obstacle_count": 1}, {"index": 1, "vessel_count": 3, "obstacle_count": 1}]
    assert {key: result[key] for key in ("stop_reason", "complete", "models_found", "max_models", "random_seed", "elapsed_s", "message")} == {
        "stop_reason": "cap_reached",
        "complete": False,
        "models_found": 2,
        "max_models": 2,
        "random_seed": 1,
        "elapsed_s": 1.5,
        "message": None,
    }
    assert "models" not in result


def test_a_specification_without_a_model_gives_an_empty_list():
    result = exploration_result(_generated([], stop_reason="unsatisfiable", message="the partial model is inconsistent"))
    assert (result["functional_scenarios"], result["fecs"], result["stop_reason"], result["message"]) == ([], [], "unsatisfiable", "the partial model is inconsistent")


@pytest.mark.parametrize("generated", [{"stop_reason": "exhausted"}, {"models": [{"index": 0, "file": "models/model_00000.problem", "source": None}]}, {"models": ["text"]}])
def test_a_generator_result_without_sources_fails_for_good(generated):
    with pytest.raises(JobFailed) as failure:
        exploration_result(generated)
    assert not failure.value.retryable


def test_each_functional_scenario_is_stored_as_an_artifact_of_its_own():
    fields = artifact_result_fields(JobType.DESIGN_SPACE_EXPLORATION)
    assert [(field.name, field.kind, field.content, field.many) for field in fields] == [("functional_scenarios", ArtifactKind.FUNCTIONAL_SCENARIO, ArtifactContent.TEXT, True)]
    stored_bytes = []

    def put(field, data):
        stored_bytes.append(data)
        return ArtifactRef(sha256=f"{len(stored_bytes):064x}", size_bytes=len(data), kind=field.kind, media_type="text/plain; charset=utf-8")

    stored = store_results(exploration_result(_generated([MODEL, "class B.\n"])), fields, put)
    assert stored_bytes == [MODEL.encode("utf-8"), b"class B.\n"]
    assert [item["sha256"] for item in stored["functional_scenarios"]] == [f"{1:064x}", f"{2:064x}"]
    assert stored["fecs"][0]["vessel_count"] == 3


def test_the_generator_is_started_with_its_own_command_the_validated_payload_and_room_to_stop(make_job, node, monkeypatch):
    calls = {}

    def run_in_runner_container(job, node_, report, subsystem, *, timeout_s, cancel=None, command=None, environment=None):
        calls.update(job=job, subsystem=subsystem, timeout_s=timeout_s, command=command, environment=environment)
        return _generated([MODEL])

    monkeypatch.setattr(design_space_exploration_job, "run_in_runner_container", run_in_runner_container)
    job = make_job(JobType.DESIGN_SPACE_EXPLORATION, {"problem": "class A.", "scopes": ["A=1"], "max_models": 5, "timeout_s": 30})
    result = design_space_exploration_job.run(job, node, report=None)
    assert calls["subsystem"] == Subsystem.DESIGN_SPACE_EXPLORATION
    assert calls["command"] == ["generate-models", "job"] and calls["environment"] == {}
    assert calls["timeout_s"] == 120.0 + 30 + 60.0  # the load limit, the generation limit and the margin
    assert calls["job"].payload == {
        "problem": "class A.",
        "max_models": 5,
        "scopes": ["A=1"],
        "scope_overrides": [],
        "random_seed": 1,
        "timeout_s": 30.0,
        "load_timeout_s": 120.0,
        "status_interval_s": 1.0,
    }
    assert set(calls["job"].payload) <= GENERATOR_FIELDS
    assert (calls["job"].job_id, calls["job"].attempt) == (job.job_id, job.attempt)
    assert result["models_found"] == 1 and result["functional_scenarios"] == [MODEL]


# In the real image


class _Report:
    def __init__(self):
        self.statuses = []
        self.lines = []

    def status(self, message, progress=None):
        self.statuses.append((message, progress))

    def log(self, source, text, stream=LogStream.STDOUT):
        self.lines.append(text)


@pytest.fixture
def exploration_image():
    """The image under SCENEGEMS_TEST_IMAGE_TAG (latest by default), unless DESIGN_SPACE_EXPLORATION_IMAGE names one."""
    variable = IMAGE_ENVIRONMENT_VARIABLES[Subsystem.DESIGN_SPACE_EXPLORATION]
    previous = os.environ.get(variable)
    if previous is None:
        os.environ[variable] = subsystem_image(Subsystem.DESIGN_SPACE_EXPLORATION).rsplit(":", 1)[0] + ":" + os.environ.get("SCENEGEMS_TEST_IMAGE_TAG", "latest")
    yield
    if previous is None:
        os.environ.pop(variable, None)


def _docker_node() -> NodeContext:
    master_id = f"t{uuid.uuid4().hex[:6]}"
    connection = MQttConnectionInfo("", "", "host.docker.internal", "localhost", 1883, False, False)
    return NodeContext(master_id=master_id, node_id="explorer", mqtt_connection=connection, reference_geofence=Geofence(57.7, 11.9, 2000.0), slots={JobType.DESIGN_SPACE_EXPLORATION: 1})


@pytest.mark.docker
def test_the_default_specification_with_one_target_ship_gives_the_seven_two_vessel_fecs(make_job, exploration_image):
    report = _Report()
    job = make_job(
        JobType.DESIGN_SPACE_EXPLORATION, {"problem": default_specification(), "scopes": list(parse_scope("TS = 1, StaticObstacle = 0")), "timeout_s": 120}, job_id=f"explore-{uuid.uuid4().hex[:6]}"
    )
    result = run_job(job, _docker_node(), report)
    assert (result["stop_reason"], result["complete"], result["models_found"]) == ("exhausted", True, 7)
    assert result["fecs"] == [{"index": index, "vessel_count": 2, "obstacle_count": 0} for index in range(7)]
    scenarios = [ModelParser.parse_problem(source) for source in result["functional_scenarios"]]
    assert len({scenario.fec_shape_hash() for scenario in scenarios}) == 7
    assert all(source.startswith(default_specification().split("declare", 1)[0].rstrip()) for source in result["functional_scenarios"])  # the metamodel and constraints as given, then the model
    finished = [message for message, _ in report.statuses if message.startswith("finished")]
    assert finished and report.statuses[-1][1] == 1.0


@pytest.mark.docker
def test_a_specification_that_does_not_parse_fails_for_good_with_the_generators_reason(make_job, exploration_image):
    job = make_job(JobType.DESIGN_SPACE_EXPLORATION, {"problem": "class A extends Missing.", "scopes": ["A=1"], "timeout_s": 60}, job_id=f"explore-{uuid.uuid4().hex[:6]}")
    with pytest.raises(JobFailed) as failure:
        run_job(job, _docker_node(), _Report())
    assert not failure.value.retryable
    assert str(failure.value)
