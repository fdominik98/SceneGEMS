"""scene_generation: one concrete scene from a functional scenario, by the node's scene generation pool.

The job is dispatched to the pooled scene generation service over the pool's scoped
topics with today's generate-scene task, so the daemon only relays it. The pool runs as
many generations at once as the node has scene_generation slots.

The worker streams its samples while it searches and marks its last one final; the job's
result is that final scene. With a seed the scene is reproducible (unless the generation
ran into its timeout, which depends on the machine); the seed used is recorded in
evaluation_data.random_seed either way.

A job that stops waiting without its final scene (cancelled, lost, released, timed out)
cancels its own generation by request id, so the pool's other generations keep running and
the worker is free for the next job.

functional_scenario_content is the scenario's text, or a reference to a functional_scenario
artifact that the node resolves to its text before the job runs (a scenario given as content
to a campaign); the text must parse either way, a reference is checked for shape only.
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
from scenegems_tool.cluster.protocol.artifacts import ArtifactContent, ArtifactField, ArtifactKind, artifact_or, is_reference
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.subsystems.scene_generation.scene_generation_types import SCENE_GENERATION_SERVICE_NAME, SCENE_GENERATION_SERVICE_TOPIC

REPLY_MARGIN_S = 60.0  # time beyond the generation timeout for the worker to start and the reply to arrive
MAX_SEED = 2**31 - 1
CANCEL_FLUSH_TIMEOUT_S = 2.0  # how long the job waits for the broker to take its cancel before it disconnects
_logger = logging.getLogger(__name__)

# functional_scenario_content is a string (the .problem text); a reference to a functional scenario artifact resolves to its text.
ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("functional_scenario_content", ArtifactKind.FUNCTIONAL_SCENARIO, ArtifactContent.TEXT),)
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("evaluation_data", ArtifactKind.SCENE),)


class SceneGenerationPayload(ProtocolModel):
    functional_scenario_content: artifact_or(str)  # the .problem text, or a reference to it
    colregs_constraints_content: str  # COLREGS constants YAML
    vessel_types_content: str  # vessel types YAML
    obstacle_types_content: str  # static obstacle types YAML
    timeout_s: int = Field(default=60, gt=0)  # the generation's own time limit
    enforce_low_tcpa: bool = False
    seed: Optional[int] = Field(default=None, ge=0, le=MAX_SEED)  # seeds random and numpy at task start; the worker draws one when None

    @field_validator("functional_scenario_content")
    @classmethod
    def _parses(cls, content: Any) -> Any:
        from functional_level.models.model_parser import ModelParser

        if is_reference(content):
            return content  # its text is checked once the node has resolved it
        try:
            ModelParser.parse_problem(content)
        except Exception as error:
            raise ValueError(f"the functional scenario does not parse ({error})") from error
        return content


PAYLOAD_MODEL = SceneGenerationPayload


def run(job: JobSpec, node: NodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    from scenegems_tool.messaging.mqtt_scene_generation_client import MqttSceneGenerationClient

    payload = parse_payload(SceneGenerationPayload, job)
    request_id = f"{job.job_id}-{job.attempt}"  # an earlier attempt's late reply is never taken for this one
    reply: Dict[str, Any] = {}
    replied = threading.Event()
    samples = 0

    def on_scene_result(scene_request_id: str, evaluation_data: Dict[str, Any], valid: bool, final: bool) -> None:
        nonlocal samples
        if scene_request_id != request_id or replied.is_set():
            return
        if not final:
            samples += 1
            report.status(f"search sample {samples}")
            return
        reply.update(valid=valid, evaluation_data=evaluation_data)
        replied.set()

    pool = node.pools.get(Subsystem.SCENE_GENERATION)
    client = MqttSceneGenerationClient(
        mqtt_connection=pool.mqtt_connection,
        topic=SCENE_GENERATION_SERVICE_TOPIC,
        reference_geofence=node.reference_geofence,
        parent_service_name=SCENE_GENERATION_SERVICE_NAME,
        send_payload=lambda message: None,
        on_generated_scene=lambda request_id, scene, evaluation_data, valid: None,
        on_scene_result=on_scene_result,
    )
    try:
        client.connect()
    except RuntimeError as error:
        raise JobFailed(str(error), retryable=True) from error
    generating = False
    try:
        wait_for_pool(lambda: client.is_connected and client.is_heartbeat_valid, report, "scene generation pool", cancel)
        client.publish_generate_scene_command(
            request_id,
            payload.functional_scenario_content,
            payload.colregs_constraints_content,
            payload.vessel_types_content,
            payload.obstacle_types_content,
            payload.timeout_s,
            payload.enforce_low_tcpa,
            seed=payload.seed,
        )
        generating = True
        wait_for_reply(replied, report, "generated scene", cancel, payload.timeout_s + REPLY_MARGIN_S)
    finally:
        if generating and not replied.is_set():
            _cancel_generation(client, request_id)
        client.disconnect()
    return {"request_id": request_id, **reply}


def _cancel_generation(client: Any, request_id: str) -> None:
    """Stop this job's generation in the pool; a cancel that cannot be sent leaves the job's outcome as it is."""
    try:
        info = client.publish_cancel_command(request_id)
        if info is not None:
            info.wait_for_publish(timeout=CANCEL_FLUSH_TIMEOUT_S)
    except Exception as error:
        _logger.warning("Could not cancel the generation of request %s: %s", request_id, error)
