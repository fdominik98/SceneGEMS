"""design_space_exploration: every model of a specification within a scope, in a container of the Refinery model generator.

The image (scenegems-design-space-exploration-subsystem, built from the pinned Refinery commit) brings its own program,
`generate-models job`, which speaks the job folder protocol of the runner containers: it reads /job/job.json, writes a
status line per second while it generates and leaves /job/result.json. It rejects payload fields it does not know, so
the payload model here has exactly its fields and the job's payload goes in as validated.

The generator returns each model's Refinery source. A model is a functional equivalence class (FEC): the result lists
them as functional_scenarios (texts, each stored as a functional scenario artifact of its own) with their vessel and
obstacle counts under fecs, in the order they were found:

    stop_reason   exhausted (these are all), unsatisfiable (the specification has no model), cap_reached
                  (max_models found, there may be more), timeout, stopped
    complete      whether the list is the whole design space
    models_found, max_models, random_seed, elapsed_s, message

The exploration order, and so the list of a capped run, is fixed by random_seed.
"""

import threading
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pydantic import Field, field_validator

from scenegems_tool.cluster.node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.node.jobs.job_payload import parse_payload
from scenegems_tool.cluster.node.jobs.runner_container import run_in_runner_container
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.node.subsystem import Subsystem
from scenegems_tool.cluster.protocol.artifacts import ArtifactContent, ArtifactField, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.subsystems.design_space_exploration.design_space import count_instances, normalize_newlines

GENERATOR_COMMAND = ["generate-models", "job"]
# The generator's own limits end the run with a result; the container is only killed this long after them
STOP_MARGIN_S = 60.0
DEFAULT_TIMEOUT_S = 600.0
DEFAULT_LOAD_TIMEOUT_S = 120.0
RESULT_SUMMARY_FIELDS = ("stop_reason", "complete", "models_found", "max_models", "random_seed", "elapsed_s", "message")

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = ()
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("functional_scenarios", ArtifactKind.FUNCTIONAL_SCENARIO, ArtifactContent.TEXT, many=True),)


class DesignSpaceExplorationPayload(ProtocolModel):
    """The generator's payload (scenegems/README.md of the Refinery repository); include_sources stays at its default, true."""

    problem: str = Field(min_length=1)  # Refinery source: the specification, and the scope when it is not given under scopes
    max_models: Optional[int] = Field(default=None, ge=1)  # the cap; None generates every model
    scopes: List[str] = Field(default_factory=list)  # scope entries such as TS=2 or TS=1..3
    scope_overrides: List[str] = Field(default_factory=list)  # entries that replace the problem's scope of the same class
    random_seed: int = Field(default=1, ge=0)  # the seed of the exploration order
    timeout_s: float = Field(default=DEFAULT_TIMEOUT_S, gt=0.0)  # the generation's time limit; the models found until then are returned
    load_timeout_s: float = Field(default=DEFAULT_LOAD_TIMEOUT_S, gt=0.0)  # ends a parser that loops on a syntax error
    state_coder_depth: Optional[int] = Field(default=None, ge=1)  # neighborhood depth for telling models apart; Refinery's default when None
    status_interval_s: float = Field(default=1.0, gt=0.0)

    @field_validator("problem")
    @classmethod
    def _not_blank(cls, problem: str) -> str:
        if not problem.strip():
            raise ValueError("the problem is empty")
        return problem


PAYLOAD_MODEL = DesignSpaceExplorationPayload


def run(job: JobSpec, node: NodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    payload = parse_payload(DesignSpaceExplorationPayload, job)
    # The generator gets the validated payload with its defaults, so its limits are the ones the container's timeout counts on
    generator_job = job.model_copy(update={"payload": payload.model_dump(mode="json", exclude_none=True)})
    generated = run_in_runner_container(
        generator_job,
        node,
        report,
        Subsystem.DESIGN_SPACE_EXPLORATION,
        timeout_s=payload.load_timeout_s + payload.timeout_s + STOP_MARGIN_S,
        cancel=cancel,
        command=GENERATOR_COMMAND,
        environment={},
    )
    return exploration_result(generated)


def exploration_result(generated: Mapping[str, Any]) -> JobResultData:
    """The job's result from the generator's: the models' sources as functional scenarios, with their counts."""
    models = generated.get("models")
    if not isinstance(models, list):
        raise JobFailed("the model generator returned no model list", retryable=False)
    fecs: List[Dict[str, int]] = []
    scenarios: List[str] = []
    for index, model in enumerate(models):
        source = model.get("source") if isinstance(model, Mapping) else None
        if not isinstance(source, str) or not source.strip():
            raise JobFailed(f"the model generator returned model {index} without its source", retryable=False)
        source = normalize_newlines(source)
        vessels, obstacles = count_instances(source)
        fecs.append({"index": index, "vessel_count": vessels, "obstacle_count": obstacles})
        scenarios.append(source)
    result: JobResultData = {field: generated.get(field) for field in RESULT_SUMMARY_FIELDS}
    result["fecs"] = fecs
    result["functional_scenarios"] = scenarios
    return result
