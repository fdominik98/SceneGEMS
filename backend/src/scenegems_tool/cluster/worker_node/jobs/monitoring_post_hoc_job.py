"""monitoring.post_hoc: judge a finished state log, or one scene, against COLREGS, by the worker node's monitoring pool.

The job is one monitor-scenario request to the worker node's monitoring subsystem (jobs/pool_client.py
run_pool_request), so the daemon only relays it. Once the request's task runs, the job sends the scenes in
time order, SCENES_PER_BATCH at a time, and closes the series; the task judges them with one monitor from the
first scene to the last and answers with the verdict (subsystems/monitoring/monitoring_worker.py). The pool
judges as many series at once as the worker node has monitoring.post_hoc slots, and two series of one scenario
never at the same time: the later one waits. A job that names no scenario is a scenario of its own.

The result lists, per vessel pair and rule, when each outcome first held (subsystems/monitoring/rule_outcomes.py,
the same summary as the live monitor of a kinematic simulation); the monitored frames are added on request.

The payload names exactly one of trajectories (a state log or planned trajectories) and
scene (a generated scene: a scene generation's EvaluationData, a scene, or a document with
the scene under scene or initial_scene, inline or as a reference). A scene is judged as a
one-scene log with time step 1, so its result has the same shape: the initial situation's
rule outcomes at time 0. At time 0 only the rules that need one scene's state are judged
(SafeDistance: a pair that starts inside its safety domain fails); the rules on how the
vessels move stay unknown, so a scene alone either fails or passes with no outcome listed.
The safety domain guard applies: a pair inside its encounter's own domain is OTHER, so
SafeDistance judges it against the default circle.

A job that stops waiting without its verdict (cancelled, lost, released, timed out) cancels its own
series by request id, so the pool's other series keep running.
"""

import threading
from typing import Any, Dict, List, Mapping, Optional, Tuple

from pydantic import Field, model_validator

from scenegems_tool.cluster.protocol.artifacts import ArtifactField, ArtifactKind, ArtifactRef, artifact_or
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.cluster.worker_node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.worker_node.jobs.job_payload import TrajectoriesInput, parse_payload
from scenegems_tool.cluster.worker_node.jobs.pool_client import request_id_of, run_pool_request
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.subsystems.monitoring.monitoring_types import CLOSE_SIGNAL, MONITOR_RESULT_STREAM, MONITOR_SCENARIO_TASK, MONITORED_SCENE_STREAM, SCENES_PER_BATCH, SCENES_SIGNAL

SCENE_KEYS = ("best_scene", "scene", "initial_scene")  # where a document keeps its scene (EvaluationData uses best_scene)
SCENE_TIME_STEP = 1  # the time step of a one-scene log

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES), ArtifactField("scene", ArtifactKind.SCENE))
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("frames", ArtifactKind.FRAMES),)


class PostHocMonitoringPayload(ProtocolModel):
    trajectories: Optional[TrajectoriesInput] = None  # the state log or planned trajectories to judge
    scene: Optional[artifact_or(Dict[str, Any])] = None  # a scene to judge as a one-scene log: EvaluationData or scene JSON
    colregs_constraints_content: Optional[str] = None  # COLREGS constants YAML; the general maritime defaults when None
    # scenarioId of the returned frames, and what orders the series of one scenario; the job's request id when None
    scenario_id: Optional[str] = Field(default=None, min_length=1)
    include_frames: bool = False  # add every monitored frame in the workbench's wire format
    timeout_s: float = Field(default=600.0, gt=0.0)  # for the whole series, its wait in the pool's queue included

    @model_validator(mode="after")
    def _one_input(self) -> "PostHocMonitoringPayload":
        if (self.trajectories is None) == (self.scene is None):
            raise ValueError("a post-hoc monitoring payload names exactly one of trajectories and scene")
        return self


PAYLOAD_MODEL = PostHocMonitoringPayload


def scene_document(document: Mapping[str, Any]) -> Mapping[str, Any]:
    """The scene of an EvaluationData, a scene, or a document holding one under best_scene, scene or initial_scene."""
    if isinstance(document.get("_data"), list):
        return document
    for key in SCENE_KEYS:
        if isinstance(document.get(key), Mapping):
            return scene_document(document[key])
    raise JobFailed("the scene input holds no scene (expected EvaluationData or a scene)", retryable=False)


def scene_as_trajectories(document: Any):
    """A scene input as a one-scene log."""
    from concrete_level.models.concrete_scene import ConcreteScene
    from concrete_level.models.trajectories import Trajectories

    if isinstance(document, ArtifactRef):
        raise JobFailed(f"Artifact {document.sha256} was not resolved before the job ran", retryable=False)
    try:
        scene = ConcreteScene.from_dict(dict(scene_document(document)))
    except JobFailed:
        raise
    except Exception as error:
        raise JobFailed(f"the scene input does not parse ({type(error).__name__}: {error})", retryable=False) from error
    return Trajectories(scene_list=[scene], time_step=SCENE_TIME_STEP)


def series_of(payload: PostHocMonitoringPayload) -> Tuple[List[Dict[str, Any]], int]:
    """The scenes to judge, in time order and as they travel, and their time step."""
    if payload.trajectories is not None:
        if isinstance(payload.trajectories, ArtifactRef):
            raise JobFailed(f"Artifact {payload.trajectories.sha256} was not resolved before the job ran", retryable=False)
        return list(payload.trajectories["scene_list"]), int(payload.trajectories["time_step"])  # checked when the payload was parsed
    trajectories = scene_as_trajectories(payload.scene)
    return [scene.to_dict() for scene in trajectories.scene_list], trajectories.time_step


class _Series:
    """What the job has heard of its series: the batches the monitor judged, with their frames, and the verdict."""

    def __init__(self, scene_count: int, report: JobReport):
        self.scene_count = scene_count
        self._report = report
        self.judged: Dict[int, List[Dict[str, Any]]] = {}  # batch index: its monitored frames (none unless asked for)
        self.verdict: Optional[Mapping[str, Any]] = None

    def take(self, stream: str, message: Mapping[str, Any]) -> bool:
        """Keep a message of the series; True once the verdict and every batch it counts are here."""
        if stream == MONITORED_SCENE_STREAM:
            index = int(message["index"])
            if index not in self.judged:
                self.judged[index] = list(message.get("monitored-frames") or [])
                monitored = int(message.get("monitored-scenes", 0))
                self._report.status(f"monitored {monitored} of {self.scene_count} scenes", min(1.0, monitored / self.scene_count))
        elif stream == MONITOR_RESULT_STREAM:
            self.verdict = message
        return self.verdict is not None and len(self.judged) >= int(self.verdict["batches"])

    def frames(self) -> List[Dict[str, Any]]:
        return [frame for index in sorted(self.judged) for frame in self.judged[index]]


def run(job: JobSpec, worker_node: WorkerNodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    payload = parse_payload(PostHocMonitoringPayload, job)
    scenes, time_step = series_of(payload)
    series = _Series(len(scenes), report)
    starts = range(0, len(scenes), SCENES_PER_BATCH)

    def send_series(client: Any, request_id: str) -> None:
        for index, start in enumerate(starts):
            if cancel is not None and cancel.is_set():
                raise JobFailed("cancelled", retryable=False)
            client.publish_signal(SCENES_SIGNAL, request_id, {"index": index, "first-timestamp": start * time_step, "scenes": scenes[start : start + SCENES_PER_BATCH]})
        client.publish_signal(CLOSE_SIGNAL, request_id, {"batches": len(starts)})

    reply = run_pool_request(
        job,
        worker_node,
        report,
        cancel,
        subsystem=Subsystem.MONITORING,
        task_name=MONITOR_SCENARIO_TASK,
        params={
            "scenario-id": payload.scenario_id or request_id_of(job),
            "time-step": time_step,
            "colregs-constraints-content": payload.colregs_constraints_content,
            "include-frames": bool(payload.include_frames),
        },
        seed=None,  # the monitor draws nothing at random; the request still carries a seed, as every request does
        streams=(MONITORED_SCENE_STREAM, MONITOR_RESULT_STREAM),
        is_result=series.take,
        timeout_s=payload.timeout_s,
        pool_description="monitoring pool",
        reply_description="monitor result",
        on_running=send_series,
    )
    verdict = series.verdict or {}
    data: Dict[str, Any] = {
        "scenes": int(verdict["scenes"]),
        "monitored_scenes": int(verdict["monitored-scenes"]),
        "time_step": int(verdict["time-step"]),
        **verdict["summary"],
        "seed": reply.seed,
    }
    if payload.include_frames:
        data["frames"] = series.frames()
    return data
