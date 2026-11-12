"""calibration.deviation: how far K repeats of one case on one stack drift apart, by the worker node's simulation pool.

The job is one compare-repeats request to the worker node's simulation subsystem (jobs/pool_client.py
run_pool_request), so the daemon only relays it. The subsystem's task runs compare below; it starts no container.

The payload holds the K runs' trajectories (the simulation results, inline or referenced),
a free description of the stack and the name of the reference. The runs are exact when
every state of every repeat is bit-identical; otherwise the result bounds the distance
between any two repeats at equal scenario time, per vessel and overall
(vessel_stack/calibration/repeat_analysis.py).
"""

import hashlib
import struct
import threading
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from pydantic import Field

from scenegems_tool.cluster.protocol.artifacts import ArtifactField, ArtifactKind
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.cluster.worker_node.job_report import JobFailed, JobReport, JobResultData
from scenegems_tool.cluster.worker_node.jobs.job_payload import TrajectoriesInput, parse_payload, to_trajectories
from scenegems_tool.cluster.worker_node.jobs.pool_client import run_pool_request
from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.subsystems.simulation.simulation_types import COMPARE_REPEATS_TASK, SIMULATION_RESULT_STREAM

ARTIFACT_INPUT_FIELDS: Tuple[ArtifactField, ...] = (ArtifactField("trajectories", ArtifactKind.TRAJECTORIES, many=True),)
ARTIFACT_RESULT_FIELDS: Tuple[ArtifactField, ...] = ()


class CalibrationDeviationPayload(ProtocolModel):
    trajectories: List[TrajectoriesInput] = Field(min_length=2)  # the K repeats of one case on one stack, each inline or a reference
    stack: Dict[str, Any] = Field(default_factory=dict)  # free description of the stack (and release), returned as given
    reference: str = Field(min_length=1)  # name of the reference scenario or case
    timeout_s: float = Field(default=600.0, gt=0.0)


PAYLOAD_MODEL = CalibrationDeviationPayload


def run(job: JobSpec, worker_node: WorkerNodeContext, report: JobReport, cancel: Optional[threading.Event] = None) -> JobResultData:
    payload = parse_payload(CalibrationDeviationPayload, job)
    reply = run_pool_request(
        job,
        worker_node,
        report,
        cancel,
        subsystem=Subsystem.SIMULATION,
        task_name=COMPARE_REPEATS_TASK,
        params={"payload": job.payload},
        seed=None,  # nothing is drawn at random; the request still carries a seed, as every request does
        streams=(SIMULATION_RESULT_STREAM,),
        is_result=lambda stream, message: bool(message.get("final", True)),
        timeout_s=payload.timeout_s,
        pool_description="simulation pool",
        reply_description="comparison of the repeats",
        relay_feedback=True,
    )
    return comparison_of(reply.result)


def comparison_of(message: Mapping[str, Any]) -> JobResultData:
    """The job's result from the subsystem's message; a comparison that failed with a reason fails the job with it and its retry rule."""
    if message.get("error"):
        raise JobFailed(str(message["error"]), retryable=bool(message.get("retryable", False)))
    result = message.get("result")
    if not isinstance(result, Mapping):
        raise JobFailed("the simulation pool answered without a comparison", retryable=True)
    return dict(result)


def trajectories_digest(trajectories) -> str:
    """SHA-256 over the time step and the exact float64 bits of every vessel's states, vessels by id."""
    digest = hashlib.sha256(struct.pack("<d", float(trajectories.time_step)))
    for vessel in sorted(trajectories.initial_scene.vessels, key=lambda vessel: vessel.id):
        digest.update(struct.pack("<q", vessel.id))
        for state in trajectories.state_list(vessel):
            digest.update(struct.pack("<4d", float(state.x), float(state.y), float(state.speed), float(state.heading)))
    return digest.hexdigest()


def _track(trajectories, vessel):
    import numpy as np

    from scenegems_tool.vessel_stack.calibration.repeat_analysis import TrackSamples

    states = trajectories.state_list(vessel)
    return TrackSamples(
        time_s=np.arange(len(states), dtype=float) * float(trajectories.time_step),
        x=np.array([float(state.x) for state in states]),
        y=np.array([float(state.y) for state in states]),
        speed=np.array([float(state.speed) for state in states]),
    )


def compare(payload: CalibrationDeviationPayload, status: Callable[..., None]) -> JobResultData:
    """Compare the repeats at equal scenario time, vessel by vessel: what a compare-repeats task of the simulation subsystem runs. status(message, progress=None)."""
    from scenegems_tool.vessel_stack.calibration.repeat_analysis import GRID_STEP_S, repeat_deviation

    repeats = [to_trajectories(data) for data in payload.trajectories]
    vessel_sets = [sorted(vessel.id for vessel in trajectories.initial_scene.vessels) for trajectories in repeats]
    if any(vessels != vessel_sets[0] for vessels in vessel_sets):
        raise JobFailed(f"The repeats do not hold the same vessels: {vessel_sets}", retryable=False)
    status(f"comparing {len(repeats)} repeats of {payload.reference}")

    digests = [trajectories_digest(trajectories) for trajectories in repeats]
    per_vessel: Dict[str, Dict[str, Any]] = {}
    for vessel_id in vessel_sets[0]:
        tracks = [_track(trajectories, next(vessel for vessel in trajectories.initial_scene.vessels if vessel.id == vessel_id)) for trajectories in repeats]
        try:
            summary = repeat_deviation(tracks, alignment="scenario_time")
        except ValueError:
            summary = None  # the repeats share no time span long enough to compare
        per_vessel[str(vessel_id)] = (
            {"max_m": summary.max_m, "rms_m": summary.rms_m, "compared_duration_s": summary.compared_duration_s, "compared_samples": int(round(summary.compared_duration_s / GRID_STEP_S))}
            if summary is not None
            else {"max_m": None, "rms_m": None, "compared_duration_s": 0.0, "compared_samples": 0}
        )
    bounds = [entry["max_m"] for entry in per_vessel.values() if entry["max_m"] is not None]
    status("comparison finished", 1.0)
    return {
        "reference": payload.reference,
        "stack": payload.stack,
        "repeats": len(repeats),
        "exact": len(set(digests)) == 1,
        "trajectory_digests": digests,
        "alignment": "scenario_time",
        "deviation_bound_m": max(bounds) if bounds else None,  # the largest distance between two repeats of any vessel
        "per_vessel": per_vessel,
        "samples_per_repeat": [len(trajectories.scene_list) for trajectories in repeats],
    }
