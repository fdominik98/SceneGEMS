"""monitoring.post_hoc: judge a finished state log, or one scene, against COLREGS, in a monitoring container.

The monitor runs in process over every scene of the trajectories, as the live monitor does
for streamed batches, but without MQTT in between (the live path is the measured throughput
limit, design doc 10.5). Each job gets its own container, so the node's slots bound the
monitors that run at once. The result lists, per vessel pair and rule, when each outcome
first held (subsystems/monitoring/rule_outcomes.py, the same summary as the live monitor
of a kinematic simulation); the monitored frames are added on request.

The payload names exactly one of trajectories (a state log or planned trajectories) and
scene (a generated scene: a scene generation's EvaluationData, a scene, or a document with
the scene under scene or initial_scene, inline or as a reference). A scene is judged as a
one-scene log with time step 1, so its result has the same shape: the initial situation's
rule outcomes at time 0. At time 0 only the rules that need one scene's state are judged
(SafeDistance: a pair that starts inside its safety domain fails); the rules on how the
vessels move stay unknown, so a scene alone either fails or passes with no outcome listed.
The safety domain guard applies: a pair inside its encounter's own domain is OTHER, so
SafeDistance judges it against the default circle.
"""

import threading
from typing import Any, Dict, Mapping, Optional, Tuple

from pydantic import Field, model_validator

from scenegems_tool.cluster.node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.node.jobs.job_payload import TrajectoriesInput, parse_payload, to_trajectories
from scenegems_tool.cluster.node.jobs.runner_container import StatusCallback, run_in_runner_container
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.cluster.node.subsystem import Subsystem
from scenegems_tool.cluster.protocol.artifacts import ArtifactField, ArtifactKind, ArtifactRef, artifact_or
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel

_PROGRESS_EVERY_SCENES = 100
SCENE_KEYS = ("best_scene", "scene", "initial_scene")  # where a document keeps its scene (EvaluationData uses best_scene)
SCENE_TIME_STEP = 1  # the time step of a one-scene log

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES), ArtifactField("scene", ArtifactKind.SCENE))
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("frames", ArtifactKind.FRAMES),)


class PostHocMonitoringPayload(ProtocolModel):
    trajectories: Optional[TrajectoriesInput] = None  # the state log or planned trajectories to judge
    scene: Optional[artifact_or(Dict[str, Any])] = None  # a scene to judge as a one-scene log: EvaluationData or scene JSON
    colregs_constraints_content: Optional[str] = None  # COLREGS constants YAML; the general maritime defaults when None
    scenario_id: str = "post-hoc"  # scenarioId of the returned frames
    include_frames: bool = False  # add every monitored frame in the workbench's wire format
    timeout_s: float = Field(default=600.0, gt=0.0)

    @model_validator(mode="after")
    def _one_input(self) -> "PostHocMonitoringPayload":
        if (self.trajectories is None) == (self.scene is None):
            raise ValueError("a post-hoc monitoring payload names exactly one of trajectories and scene")
        return self


PAYLOAD_MODEL = PostHocMonitoringPayload


def run(job: JobSpec, node: NodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    payload = parse_payload(PostHocMonitoringPayload, job)
    return run_in_runner_container(job, node, report, Subsystem.MONITORING, timeout_s=payload.timeout_s, cancel=cancel)


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


def execute(job: JobSpec, status: StatusCallback) -> JobResultData:
    """The in-container part: monitor every scene in order and summarize the verdicts."""
    from concrete_level.colregs_monitoring.colregs_monitor_runtime import ColregsMonitorRuntime, MonitoringTask
    from scenegems_tool.gateway.serialization import serialize_monitored_frame
    from scenegems_tool.subsystems.monitoring.rule_outcomes import RuleOutcomes
    from utils.colregs_approximations import COLREGSConstraints

    payload = parse_payload(PostHocMonitoringPayload, job)
    trajectories = to_trajectories(payload.trajectories) if payload.trajectories is not None else scene_as_trajectories(payload.scene)
    constants = COLREGSConstraints.from_file_content(payload.colregs_constraints_content) if payload.colregs_constraints_content else COLREGSConstraints.default_general_maritime()
    runtime = ColregsMonitorRuntime(constants)
    time_step = trajectories.time_step
    scene_count = len(trajectories.scene_list)

    outcomes = RuleOutcomes()
    frames = []
    for index, scene in enumerate(trajectories.scene_list):
        runtime.add_task(MonitoringTask(scene=scene, scene_timestamp=index * time_step, time_step=time_step))
        for monitored_scene in runtime.monitor_current_tasks():
            outcomes.add(monitored_scene)
            if payload.include_frames:
                frames.append(serialize_monitored_frame(scenario_id=payload.scenario_id, monitored_scene=monitored_scene, timestamp=monitored_scene.timestamp, time_step=time_step))
        if (index + 1) % _PROGRESS_EVERY_SCENES == 0:
            status(f"monitored {index + 1} of {scene_count} scenes", (index + 1) / scene_count)

    data: Dict[str, Any] = {"scenes": scene_count, "monitored_scenes": outcomes.monitored_scenes, "time_step": time_step, **outcomes.summary()}
    if payload.include_frames:
        data["frames"] = frames
    return data
