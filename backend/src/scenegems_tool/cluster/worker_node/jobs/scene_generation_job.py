"""scene_generation: one concrete scene from a functional scenario, by the worker node's scene generation pool.

The job is one generate-scene request to the worker node's scene generation subsystem
(jobs/pool_client.py run_pool_request), so the daemon only relays it. The pool runs as
many generations at once as the worker node has scene_generation slots.

The worker streams its samples while it searches and marks its last one final; the job's
result is that final scene. The seed fixes the scene (unless the generation ran into its
timeout, which depends on the machine); a job that names none gets one drawn, and the seed
used is in the result (seed) and in evaluation_data.random_seed.

A job that stops waiting without its final scene (cancelled, lost, released, timed out)
cancels its own generation by request id, so the pool's other generations keep running and
the worker is free for the next job.

functional_scenario_content is the scenario's text, or a reference to a functional_scenario
artifact that the worker node resolves to its text before the job runs (a scenario given as content
to a campaign); the text must parse either way, a reference is checked for shape only.
"""

import threading
from typing import Any, Mapping, Optional, Tuple

from pydantic import Field, field_validator

from scenegems_tool.cluster.protocol.artifacts import ArtifactContent, ArtifactField, ArtifactKind, artifact_or, is_reference
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.cluster.worker_node.job_report import JobReport, JobResultData
from scenegems_tool.cluster.worker_node.jobs.job_payload import parse_payload
from scenegems_tool.cluster.worker_node.jobs.pool_client import run_pool_request
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.subsystems.pool.pool_task import MAX_SEED
from scenegems_tool.subsystems.scene_generation.scene_generation_types import GENERATE_SCENE_TASK, GENERATED_SCENE_STREAM

REPLY_MARGIN_S = 60.0  # time beyond the generation timeout for the worker to start and the reply to arrive

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
    seed: Optional[int] = Field(default=None, ge=0, le=MAX_SEED)  # the request's seed, which fixes the scene; one is drawn for the request when None

    @field_validator("functional_scenario_content")
    @classmethod
    def _parses(cls, content: Any) -> Any:
        from functional_level.models.model_parser import ModelParser

        if is_reference(content):
            return content  # its text is checked once the worker node has resolved it
        try:
            ModelParser.parse_problem(content)
        except Exception as error:
            raise ValueError(f"the functional scenario does not parse ({error})") from error
        return content


PAYLOAD_MODEL = SceneGenerationPayload


def run(job: JobSpec, worker_node: WorkerNodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    payload = parse_payload(SceneGenerationPayload, job)
    samples = 0

    def sample(stream: str, message: Mapping[str, Any]) -> str:
        nonlocal samples
        samples += 1
        return f"search sample {samples}"

    reply = run_pool_request(
        job,
        worker_node,
        report,
        cancel,
        subsystem=Subsystem.SCENE_GENERATION,
        task_name=GENERATE_SCENE_TASK,
        params={
            "functional-scenario-content": payload.functional_scenario_content,
            "colregs-constraints-content": payload.colregs_constraints_content,
            "vessel-types-content": payload.vessel_types_content,
            "obstacle-types-content": payload.obstacle_types_content,
            "timeout": payload.timeout_s,
            "enforce-low-tcpa": bool(payload.enforce_low_tcpa),
        },
        seed=payload.seed,
        streams=(GENERATED_SCENE_STREAM,),
        is_result=lambda stream, message: bool(message.get("final", True)),  # the worker's samples are search progress; its last scene is final
        timeout_s=payload.timeout_s + REPLY_MARGIN_S,
        pool_description="scene generation pool",
        reply_description="generated scene",
        progress=sample,
    )
    return {"request_id": reply.request_id, "valid": bool(reply.result["valid"]), "evaluation_data": reply.result["evaluation-data"], "seed": reply.seed}
