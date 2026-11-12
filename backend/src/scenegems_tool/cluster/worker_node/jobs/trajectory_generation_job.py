"""trajectory_generation: trajectories for a concrete scene, by the worker node's trajectory generation pool.

The job is one generate-trajectories request to the worker node's trajectory generation subsystem
(jobs/pool_client.py run_pool_request). The pool queues requests for its workers, one per
trajectory_generation slot. A job that stops waiting without its result (cancelled, lost, released,
timed out) cancels its own search by request id, so the pool's other searches keep running and the
worker is free for the next job. The seed fixes the search; a job that names none gets one drawn,
and the result names the seed used.

params.generator picks the generator: monitor_driven_rrt (the monitor-guided planner, the default) or
straight (every vessel straight on up to params.timespan, at once). The result's complete is
true for a complete plan; a search that ends with its best partial path reports valid true
and complete false.
"""

import threading
from typing import Any, Dict, Mapping, Optional, Tuple

from pydantic import Field, field_validator

from scenegems_tool.cluster.protocol.artifacts import ArtifactContent, ArtifactField, ArtifactKind, artifact_or
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.cluster.worker_node.job_report import JobReport, JobResultData
from scenegems_tool.cluster.worker_node.jobs.job_payload import parse_payload
from scenegems_tool.cluster.worker_node.jobs.pool_client import run_pool_request
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.subsystems.pool.pool_task import MAX_SEED
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import (
    GENERATE_TRAJECTORIES_TASK,
    TRAJECTORY_PREVIEW_STREAM,
    TRAJECTORY_RESULT_STREAM,
    TrajectoryGenerationParams,
)

# The keys TrajectoryGenerationParams.from_wire reads, as the workbench sends them.
PARAM_KEYS = frozenset(
    {
        "timeStep",
        "timeout",
        "maxIterations",
        "directionThreshold",
        "bestRandomNodesK",
        "previewInterval",
        "includeMonitorResults",
        "generator",
        "timespan",
    }
)
# Keys of the old RRT search that the planner never read. Stored campaigns and workbench runs still
# carry them, so they are accepted and dropped instead of rejected as unknown.
RETIRED_PARAM_KEYS = frozenset({"goalSampleRate", "bestLeafSampleRate", "maxLeafs"})

# scenario_content is a string (the EvaluationData JSON); a reference to a scene artifact resolves to its text.
ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("scenario_content", ArtifactKind.SCENE, ArtifactContent.TEXT),)
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectory_data", ArtifactKind.TRAJECTORY_DATA),)


class TrajectoryGenerationPayload(ProtocolModel):
    scenario_content: artifact_or(str)  # the generated scene as the workbench sends it (EvaluationData or scene JSON)
    colregs_constraints_content: str  # COLREGS constants YAML
    params: Dict[str, Any] = Field(default_factory=dict)  # TrajectoryGenerationParams in wire form; search defaults when empty
    seed: Optional[int] = Field(default=None, ge=0, le=MAX_SEED)  # the request's seed, which fixes the search; one is drawn for the request when None
    timeout_s: float = Field(default=1800.0, gt=0.0)  # how long the job waits for the result

    @field_validator("params")
    @classmethod
    def _known_params(cls, params: Dict[str, Any]) -> Dict[str, Any]:
        params = without_retired_params(params)
        unknown = sorted(set(params) - PARAM_KEYS)
        if unknown:
            raise ValueError(f"unknown search parameters {unknown}")
        try:
            TrajectoryGenerationParams.from_wire(params)
        except TypeError as error:  # a value of the wrong kind, such as a list for a number
            raise ValueError(f"bad search parameters ({error})") from error
        return params


PAYLOAD_MODEL = TrajectoryGenerationPayload


def without_retired_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """The search parameters without the RETIRED_PARAM_KEYS."""
    return {key: value for key, value in params.items() if key not in RETIRED_PARAM_KEYS}


def run(job: JobSpec, worker_node: WorkerNodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    payload = parse_payload(TrajectoryGenerationPayload, job)
    previews = 0

    def preview(stream: str, message: Mapping[str, Any]) -> str:
        nonlocal previews
        previews += 1
        return f"search preview {previews}"

    reply = run_pool_request(
        job,
        worker_node,
        report,
        cancel,
        subsystem=Subsystem.TRAJECTORY_GENERATION,
        task_name=GENERATE_TRAJECTORIES_TASK,
        params={
            "scenario-content": payload.scenario_content,
            "colregs-constraints-content": payload.colregs_constraints_content,
            "params": TrajectoryGenerationParams.from_wire(payload.params).to_wire(),
        },
        seed=payload.seed,
        streams=(TRAJECTORY_RESULT_STREAM, TRAJECTORY_PREVIEW_STREAM),
        is_result=lambda stream, message: stream == TRAJECTORY_RESULT_STREAM,
        timeout_s=payload.timeout_s,
        pool_description="trajectory generation pool",
        reply_description="trajectory generation result",
        progress=preview,
    )
    result = reply.result
    valid = bool(result.get("valid", False))
    # A search that plans nothing is a result (valid false, with the reason), not a failed job.
    return {
        "request_id": reply.request_id,
        "valid": valid,
        "complete": bool(result.get("complete", False)),
        "trajectory_data": result.get("trajectory-data"),
        "error_message": result.get("error-message"),
        "seed": reply.seed,
    }
