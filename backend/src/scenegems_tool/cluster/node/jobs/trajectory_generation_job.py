"""trajectory_generation: trajectories for a concrete scene, by the node's trajectory generation pool.

The job is dispatched to the pooled trajectory generation service over the pool's scoped
topics with today's generate-trajectories task. On a node the pool queues requests for its
workers (one per trajectory_generation slot) instead of superseding the running one. A job that
stops waiting without its result (cancelled, lost, released, timed out) cancels its own search by
request id, so the pool's other searches keep running and the worker is free for the next job.

params.generator picks the generator: monitor_driven_rrt (the monitor-guided planner, the default) or
straight (every vessel straight on up to params.timespan, at once). The result's complete is
true for a complete plan; a search that ends with its best partial path reports valid true
and complete false.
"""

import logging
import threading
from typing import Any, Dict, Optional, Tuple

from pydantic import Field, field_validator

from scenegems_tool.cluster.node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.node.jobs.job_payload import parse_payload
from scenegems_tool.cluster.node.jobs.pool_client import wait_for_pool, wait_for_reply
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.node.subsystem import Subsystem
from scenegems_tool.cluster.protocol.artifacts import ArtifactContent, ArtifactField, ArtifactKind, artifact_or
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.subsystems.trajectory_generation.trajectory_generation_types import (
    TRAJECTORY_GENERATION_SERVICE_NAME,
    TRAJECTORY_GENERATION_SERVICE_TOPIC,
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
MAX_SEED = 2**31 - 1
CANCEL_FLUSH_TIMEOUT_S = 2.0  # how long the job waits for the broker to take its cancel before it disconnects
_logger = logging.getLogger(__name__)

# scenario_content is a string (the EvaluationData JSON); a reference to a scene artifact resolves to its text.
ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("scenario_content", ArtifactKind.SCENE, ArtifactContent.TEXT),)
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectory_data", ArtifactKind.TRAJECTORY_DATA),)


class TrajectoryGenerationPayload(ProtocolModel):
    scenario_content: artifact_or(str)  # the generated scene as the workbench sends it (EvaluationData or scene JSON)
    colregs_constraints_content: str  # COLREGS constants YAML
    params: Dict[str, Any] = Field(default_factory=dict)  # TrajectoryGenerationParams in wire form; search defaults when empty
    seed: Optional[int] = Field(default=None, ge=0, le=MAX_SEED)  # seeds random and numpy at task start; the worker's fixed seed when None
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


def run(job: JobSpec, node: NodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    from scenegems_tool.messaging.mqtt_trajectory_generation_client import MqttTrajectoryGenerationClient

    payload = parse_payload(TrajectoryGenerationPayload, job)
    request_id = f"{job.job_id}-{job.attempt}"
    reply: Dict[str, Any] = {}
    replied = threading.Event()
    previews = 0

    def on_message(message: Dict[str, Any]) -> None:
        nonlocal previews
        if message.get("requestId") == request_id and message.get("type") == "trajectory_generation_preview":
            previews += 1
            report.status(f"search preview {previews}")

    def on_result(result_request_id: str, trajectory_data: Optional[Dict[str, Any]], valid: bool, complete: bool, error_message: Optional[str]) -> None:
        if result_request_id == request_id:
            reply.update(valid=valid, complete=complete, trajectory_data=trajectory_data, error_message=error_message)
            replied.set()

    pool = node.pools.get(Subsystem.TRAJECTORY_GENERATION)
    client = MqttTrajectoryGenerationClient(
        mqtt_connection=pool.mqtt_connection,
        topic=TRAJECTORY_GENERATION_SERVICE_TOPIC,
        reference_geofence=node.reference_geofence,
        parent_service_name=TRAJECTORY_GENERATION_SERVICE_NAME,
        send_payload=on_message,
        on_result=on_result,
    )
    try:
        client.connect()
    except RuntimeError as error:
        raise JobFailed(str(error), retryable=True) from error
    searching = False
    try:
        wait_for_pool(lambda: client.is_connected and client.is_heartbeat_valid, report, "trajectory generation pool", cancel)
        client.publish_generate_trajectories_command(request_id, payload.scenario_content, payload.colregs_constraints_content, TrajectoryGenerationParams.from_wire(payload.params), seed=payload.seed)
        searching = True
        wait_for_reply(replied, report, "trajectory generation result", cancel, payload.timeout_s)
    finally:
        if searching and not replied.is_set():
            _cancel_search(client, request_id)
        client.disconnect()
    # A search that plans nothing is a result (valid false, with the reason), not a failed job.
    return {"request_id": request_id, **reply}


def _cancel_search(client: Any, request_id: str) -> None:
    """Stop this job's search in the pool; a cancel that cannot be sent leaves the job's outcome as it is."""
    try:
        info = client.publish_cancel_command(request_id)
        if info is not None:
            info.wait_for_publish(timeout=CANCEL_FLUSH_TIMEOUT_S)
    except Exception as error:
        _logger.warning("Could not cancel the search of request %s: %s", request_id, error)
