"""Verdicts, run records, calibration results and artifact references, from the jobs' results.

A verdict judges one step of a case: a run of the simulation step, or the generated scene or
trajectory set when the campaign monitors that step (StepKind scene, trajectories; run index
0). A run's verdict comes from its monitor:

    post_hoc  the monitoring.post_hoc result: passed, failed_rules, rules
    live      the simulation result's monitor section (the same shape), with early_stop_time_s
              from its stopped_early_at
    empty     unmonitored, judging nothing

A scene or trajectory verdict always comes from a monitoring.post_hoc result; an unmonitored
generation step gets no verdict. Each waits in the case's progress as a pending verdict (JSON)
until the coverage controller completes the case; new_verdict turns it into the stored one,
with its sensitivity then: false on an exact stack and for the generation steps, and on a
bounded stack true while no calibration result exists for the stack on the run's
fingerprints.

A run record describes one simulation (every repeat): the simulation's run_record, steps
and state digest, its artifacts as {role: sha256} for referenced ones, the job, the node
that held its lease, its fingerprints and the job's durations. A run recorded from a live
session has source live_session and no job.

Every reference in a result gets an artifact reference for its holder (the case for the
scene, the generated trajectories and the frames of the scene and trajectory monitors, the
run record for the state log and frames), so the sweep keeps the file. The artifact store
records an upload as held by its job (role result:<field>) until then; the engine takes the
job's references over in the same transaction, so retention decides what stays. Inline
results add none.
"""

from typing import Any, Dict, Mapping, Optional

from sqlalchemy.orm import Session

from scenegems_tool.cluster.protocol.artifacts import find_references
from scenegems_tool.persistence.schema import ArtifactHolderKind, MonitorImplementation, RunSource, StepKind, TrajectoryGeneratorImplementation, VerdictState
from scenegems_tool.persistence.stores import AssuranceStores, NewCalibrationResult, NewRunRecord, NewVerdict

EXACT_TIER = "exact"

# The role a reference in a result field has for its holder
RESULT_FIELD_ROLES = {
    "evaluation_data": "scene",
    "trajectory_data": "trajectory_data",
    "trajectories": "state_log",
    "states": "state_log",
    "frames": "frames",
}
RESULT_ROLE_PREFIX = "result:"  # the job's own reference to an uploaded result field (persistence/artifacts/recorded_artifacts.py)
# The frames of the scene and trajectory monitors, held by the case
STEP_FRAME_ROLES = {StepKind.SCENE: "scene_frames", StepKind.TRAJECTORIES: "trajectory_frames"}
# Roles retention may remove: the generated trajectories and the generation monitors' frames (held by the case) and what the runs produced
CASE_TRAJECTORY_ROLES = ("trajectory_data",)
RUN_LOG_ROLES = ("state_log", "frames")


def step_roles(step: StepKind) -> Dict[str, str]:
    """The roles of a scene or trajectory monitor's result fields: its frames under the step's own role, so the two monitors' frames stay apart."""
    return {**RESULT_FIELD_ROLES, "frames": STEP_FRAME_ROLES[step]}


class ResultError(ValueError):
    """A succeeded job's result lacks what its stage needs."""


# Verdicts


def _pending(monitor: MonitorImplementation, outcomes: Mapping[str, Any], early_stop_time_s: Optional[float] = None) -> Dict[str, Any]:
    if "passed" not in outcomes:
        raise ResultError(f"the {monitor.value} monitor's result has no passed")
    failed = list(outcomes.get("failed_rules") or [])
    passed = bool(outcomes["passed"]) and not failed
    times = [float(rule["first_failed_at"]) for rule in failed if rule.get("first_failed_at") is not None]
    return {
        "state": (VerdictState.PASSED if passed else VerdictState.FAILED).value,
        "monitor": monitor.value,
        "rule_outcomes": dict(outcomes.get("rules") or {}),
        "failed_rules": [f"{rule.get('relation')}: {rule.get('rule')}" for rule in failed],
        "first_failure_time_s": None if passed or not times else min(times),
        "early_stop_time_s": early_stop_time_s,
        "encounters": {relation: list(types) for relation, types in outcomes["encounters"].items()} if outcomes.get("encounters") else None,  # a result of an older node has none
    }


def pending_from_post_hoc(monitoring_result: Mapping[str, Any]) -> Dict[str, Any]:
    return _pending(MonitorImplementation.POST_HOC, monitoring_result)


def pending_from_live(simulation_result: Mapping[str, Any]) -> Dict[str, Any]:
    section = simulation_result.get("monitor")
    if not isinstance(section, Mapping):
        raise ResultError("a simulation with the live monitor returned no monitor section")
    stopped = section.get("stopped_early_at")
    return _pending(MonitorImplementation.LIVE, section, None if stopped is None else float(stopped))


def pending_unmonitored() -> Dict[str, Any]:
    return {
        "state": VerdictState.UNMONITORED.value,
        "monitor": MonitorImplementation.EMPTY.value,
        "rule_outcomes": {},
        "failed_rules": [],
        "first_failure_time_s": None,
        "early_stop_time_s": None,
        "encounters": None,
    }


def new_verdict(case_id: int, run_index: int, pending: Mapping[str, Any], run_record_id: Optional[int], sensitive: bool, step: StepKind = StepKind.SIMULATION) -> NewVerdict:
    return NewVerdict(
        step=step,
        case_id=case_id,
        run_index=run_index,
        state=VerdictState(pending["state"]),
        monitor=MonitorImplementation(pending["monitor"]),
        rule_outcomes=dict(pending.get("rule_outcomes") or {}),
        failed_rules=tuple(pending.get("failed_rules") or ()),
        first_failure_time_s=pending.get("first_failure_time_s"),
        sensitive=sensitive,
        early_stop_time_s=pending.get("early_stop_time_s"),
        run_record_id=run_record_id,
        encounters=pending.get("encounters"),
    )


def is_sensitive(stores: AssuranceStores, session: Session, tier: Optional[str], stack: Mapping[str, Any], fingerprints: Mapping[str, str]) -> bool:
    """False on an exact stack; otherwise true while no calibration exists for the stack on these fingerprints."""
    if tier == EXACT_TIER:
        return False
    return not stores.calibrations.find(stack, fingerprints, session=session)


# Run records


def referenced_hash(value: Any) -> Optional[str]:
    references = find_references(value)
    return references[0][1].sha256 if references else None


def new_run_record(
    case_id: int,
    run_index: int,
    repeat_index: int,
    generator: Optional[TrajectoryGeneratorImplementation],
    trajectories_complete: bool,
    stack: Mapping[str, Any],
    environment: Mapping[str, Any],
    seed: int,
    simulation_result: Mapping[str, Any],
    input_trajectories_hash: Optional[str],
    job_id: Optional[str],
    node_id: Optional[str],
    fingerprints: Mapping[str, str],
    durations_s: Mapping[str, float],
    tier: Optional[str],
    source: RunSource = RunSource.JOB,
) -> NewRunRecord:
    record = dict(simulation_result.get("run_record") or {})
    artifacts = {}
    if input_trajectories_hash is not None:
        artifacts["trajectories"] = input_trajectories_hash
    state_log = referenced_hash(simulation_result.get("trajectories"))
    if state_log is not None:
        artifacts["state_log"] = state_log
    steps = simulation_result.get("steps", record.get("steps"))
    return NewRunRecord(
        case_id=case_id,
        run_index=run_index,
        repeat_index=repeat_index,
        trajectory_generator=generator,
        trajectories_complete=trajectories_complete,
        stack={"config": dict(stack), "run_record": record},
        environment=dict(record.get("environment") or environment),
        seed=seed,
        repeatability_tier=record.get("repeatability_tier", tier),
        dt=record.get("dt"),
        steps=steps,
        state_digest=simulation_result.get("state_digest", record.get("state_digest")),
        artifacts=artifacts,
        job_id=job_id,
        node_id=node_id,
        fingerprints=dict(fingerprints),
        durations_s=dict(durations_s),
        source=source,
    )


# Calibration


def new_calibration_result(result: Mapping[str, Any], stack: Mapping[str, Any], fingerprints: Mapping[str, str], environment: Mapping[str, Any], campaign_id: str) -> NewCalibrationResult:
    for field in ("reference", "repeats", "exact"):
        if field not in result:
            raise ResultError(f"the calibration result has no {field}")
    envelope = {key: result[key] for key in ("per_vessel", "trajectory_digests", "alignment", "samples_per_repeat") if key in result}
    return NewCalibrationResult(
        stack=dict(stack),
        fingerprints=dict(fingerprints),
        environment=dict(environment),
        reference_scenario=str(result["reference"]),
        repeats=int(result["repeats"]),
        exact=bool(result["exact"]),
        deviation_bound_m=result.get("deviation_bound_m"),
        envelope=envelope,
        campaign_id=campaign_id,
    )


# Artifact references


def record_references(
    stores: AssuranceStores,
    session: Session,
    result: Mapping[str, Any],
    holder_kind: ArtifactHolderKind,
    holder_id: Any,
    campaign_id: str,
    job_id: Optional[str] = None,
    field_roles: Mapping[str, str] = RESULT_FIELD_ROLES,
) -> Dict[str, str]:
    """Adds an artifact reference for every reference in the result and drops the job's own; returns {role: sha256}.

    The artifact's record is added when it is missing (the artifact store records an upload
    before the node reports its result, so this only repairs a missing record).
    """
    roles: Dict[str, str] = {}
    for path, reference in find_references(result):
        field = str(path[0]) if path else "result"
        role = field_roles.get(field, field)
        if len(path) > 1:
            role = f"{role}:{'/'.join(str(part) for part in path[1:])}"
        stores.artifacts.insert_if_absent(reference.sha256, reference.kind.value, reference.size_bytes, reference.media_type, session=session)
        stores.artifacts.add_reference(reference.sha256, holder_kind, str(holder_id), role, campaign_id, session=session)
        roles[role] = reference.sha256
    if job_id is not None:
        release_job_references(stores, session, job_id)
    return roles


def release_job_references(stores: AssuranceStores, session: Session, job_id: str) -> None:
    """Drops the references the artifact store recorded for the job's uploads, once the case or run holds what it needs."""
    stores.artifacts.remove_references_of(ArtifactHolderKind.JOB, job_id, session=session)
