"""design_space_exploration: every model of a specification within a scope, by the worker node's design space exploration pool.

The job is one explore-design-space request to the worker node's design space exploration subsystem
(jobs/pool_client.py run_pool_request), so the daemon only relays it. The subsystem runs the Refinery model
generator for the request (subsystems/design_space_exploration/design_space_exploration_worker.py); the pool
runs as many explorations at once as the worker node has design_space_exploration slots. The generator's status
lines, one a second, are the job's status while it runs.

The generator rejects payload fields it does not know, so the payload model here has exactly its fields.

A model is a functional equivalence class (FEC): the result lists them as functional_scenarios (texts, each
stored as a functional scenario artifact of its own) with their vessel and obstacle counts under fecs, in the
order they were found, the objects the generator named (tS1, staticObstacle1) with the catalog's names (ts1, obst1):

    stop_reason   exhausted (these are all), unsatisfiable (the specification has no model), cap_reached
                  (max_models found, there may be more), timeout, stopped
    complete      whether the list is the whole design space
    models_found, max_models, random_seed, elapsed_s, message

The exploration order, and so the list of a capped run, is fixed by random_seed: it is the seed of the request.

A specification that does not parse, or a scope the generator refuses, fails the job for good with the
generator's reason: another attempt fails the same way. A job that stops waiting without its design space
(cancelled, lost, released, timed out) cancels its own exploration by request id, which ends its generator.
"""

import threading
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pydantic import Field, field_validator

from scenegems_tool.cluster.protocol.artifacts import ArtifactContent, ArtifactField, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.cluster.worker_node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.worker_node.jobs.job_payload import parse_payload
from scenegems_tool.cluster.worker_node.jobs.pool_client import run_pool_request
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.subsystems.design_space_exploration.design_space_exploration_types import DEFAULT_LOAD_TIMEOUT_S, DESIGN_SPACE_STREAM, EXPLORE_DESIGN_SPACE_TASK, STOP_MARGIN_S

DEFAULT_TIMEOUT_S = 600.0

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = ()
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("functional_scenarios", ArtifactKind.FUNCTIONAL_SCENARIO, ArtifactContent.TEXT, many=True),)


class DesignSpaceExplorationPayload(ProtocolModel):
    """The generator's payload (scenegems/README.md of the Refinery repository); include_sources stays at its default, true."""

    problem: str = Field(min_length=1)  # Refinery source: the specification, and the scope when it is not given under scopes
    max_models: Optional[int] = Field(default=None, ge=1)  # the cap; None generates every model
    scopes: List[str] = Field(default_factory=list)  # scope entries such as TS=2 or TS=1..3
    scope_overrides: List[str] = Field(default_factory=list)  # entries that replace the problem's scope of the same class
    random_seed: int = Field(default=1, ge=0)  # the seed of the request, and so of the exploration order
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


def request_params(payload: DesignSpaceExplorationPayload) -> Dict[str, Any]:
    """The payload as the subsystem's request names it; the seed travels as the request's seed."""
    params: Dict[str, Any] = {
        "problem": payload.problem,
        "scopes": list(payload.scopes),
        "scope-overrides": list(payload.scope_overrides),
        "timeout": payload.timeout_s,
        "load-timeout": payload.load_timeout_s,
        "status-interval": payload.status_interval_s,
    }
    if payload.max_models is not None:
        params["max-models"] = payload.max_models
    if payload.state_coder_depth is not None:
        params["state-coder-depth"] = payload.state_coder_depth
    return params


def run(job: JobSpec, worker_node: WorkerNodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    payload = parse_payload(DesignSpaceExplorationPayload, job)
    reply = run_pool_request(
        job,
        worker_node,
        report,
        cancel,
        subsystem=Subsystem.DESIGN_SPACE_EXPLORATION,
        task_name=EXPLORE_DESIGN_SPACE_TASK,
        params=request_params(payload),
        seed=payload.random_seed,
        streams=(DESIGN_SPACE_STREAM,),
        is_result=lambda stream, message: bool(message.get("final", True)),
        # The generator's own limits end the exploration with a result; the job only stops waiting this long after them
        timeout_s=payload.load_timeout_s + payload.timeout_s + STOP_MARGIN_S,
        pool_description="design space exploration pool",
        reply_description="explored design space",
        relay_feedback=True,
    )
    return design_space_of(reply.result)


def design_space_of(message: Mapping[str, Any]) -> JobResultData:
    """The job's result from the subsystem's message: the explored FECs, or the generator's error as the job's failure."""
    error = message.get("error")
    if error:
        raise JobFailed(str(error), retryable=bool(message.get("retryable", False)))
    design_space = message.get("design-space")
    if not isinstance(design_space, Mapping):
        raise JobFailed("the design space exploration pool answered without a design space", retryable=False)
    return dict(design_space)
