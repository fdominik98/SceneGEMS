"""Run records, verdicts, coverage and findings as the result store takes and returns them."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from scenegems_tool.persistence.schema import (
    CampaignClassState,
    CaseState,
    MonitorImplementation,
    RunRecordRow,
    RunSource,
    StepKind,
    TrajectoryGeneratorImplementation,
    VerdictRow,
    VerdictState,
)


@dataclass(frozen=True)
class NewRunRecord:
    case_id: int
    run_index: int
    trajectory_generator: Optional[TrajectoryGeneratorImplementation]  # None for trajectories from an input item or a live session
    trajectories_complete: bool
    stack: Dict[str, Any]
    environment: Dict[str, Any]
    seed: int
    repeat_index: int = 0
    repeatability_tier: Optional[str] = None
    dt: Optional[float] = None
    steps: Optional[int] = None
    state_digest: Optional[str] = None
    artifacts: Dict[str, str] = field(default_factory=dict)  # role to sha256
    job_id: Optional[str] = None
    node_id: Optional[str] = None
    fingerprints: Dict[str, str] = field(default_factory=dict)
    durations_s: Dict[str, float] = field(default_factory=dict)
    source: RunSource = RunSource.JOB


@dataclass(frozen=True)
class RunRecord:
    run_record_id: int
    case_id: int
    campaign_id: str
    class_id: str
    run_index: int
    repeat_index: int
    trajectory_generator: Optional[TrajectoryGeneratorImplementation]
    trajectories_complete: bool
    stack: Dict[str, Any]
    repeatability_tier: Optional[str]
    environment: Dict[str, Any]
    seed: int
    dt: Optional[float]
    steps: Optional[int]
    state_digest: Optional[str]
    artifacts: Dict[str, str]
    job_id: Optional[str]
    node_id: Optional[str]
    fingerprints: Dict[str, str]
    durations_s: Dict[str, float]
    created_at: datetime
    case_index: Optional[int] = None  # the case's index in its class, joined in by the store
    source: RunSource = RunSource.JOB

    @classmethod
    def from_row(cls, row: RunRecordRow, case_index: Optional[int] = None) -> "RunRecord":
        return cls(
            run_record_id=row.id,
            case_id=row.case_id,
            campaign_id=row.campaign_id,
            class_id=row.class_id,
            run_index=row.run_index,
            repeat_index=row.repeat_index,
            trajectory_generator=row.trajectory_generator,
            trajectories_complete=row.trajectories_complete,
            stack=dict(row.stack),
            repeatability_tier=row.repeatability_tier,
            environment=dict(row.environment),
            seed=row.seed,
            dt=row.dt,
            steps=row.steps,
            state_digest=row.state_digest,
            artifacts=dict(row.artifacts),
            job_id=row.job_id,
            node_id=row.node_id,
            fingerprints=dict(row.fingerprints),
            durations_s=dict(row.durations_s),
            created_at=row.created_at,
            case_index=case_index,
            source=row.source,
        )


@dataclass(frozen=True)
class NewVerdict:
    case_id: int
    run_index: int
    state: VerdictState
    monitor: MonitorImplementation
    rule_outcomes: Dict[str, Any] = field(default_factory=dict)
    failed_rules: Tuple[str, ...] = ()
    first_failure_time_s: Optional[float] = None
    margin: Optional[float] = None
    sensitive: bool = False
    early_stop_time_s: Optional[float] = None
    run_record_id: Optional[int] = None
    step: StepKind = StepKind.SIMULATION  # the scene and trajectory steps have run index 0
    encounters: Optional[Dict[str, List[str]]] = None  # per relation, the COLREGSType names in order of first appearance; None when the monitor did not say
    encounter_roles: Optional[Dict[str, Dict[str, Dict[str, List[str]]]]] = None  # per relation and COLREGSType name, the vessels by role (give_way, stand_on); None when the monitor did not say


@dataclass(frozen=True)
class VerdictRecord:
    verdict_id: int
    case_id: int
    campaign_id: str
    class_id: str
    run_index: int
    run_record_id: Optional[int]
    state: VerdictState
    monitor: MonitorImplementation
    rule_outcomes: Dict[str, Any]
    failed_rules: Tuple[str, ...]
    first_failure_time_s: Optional[float]
    margin: Optional[float]
    sensitive: bool
    early_stop_time_s: Optional[float]
    created_at: datetime
    case_index: Optional[int] = None  # the case's index in its class, joined in by the store
    step: StepKind = StepKind.SIMULATION
    encounters: Optional[Dict[str, List[str]]] = None
    encounter_roles: Optional[Dict[str, Dict[str, Dict[str, List[str]]]]] = None

    @classmethod
    def from_row(cls, row: VerdictRow, case_index: Optional[int] = None) -> "VerdictRecord":
        return cls(
            verdict_id=row.id,
            case_id=row.case_id,
            campaign_id=row.campaign_id,
            class_id=row.class_id,
            run_index=row.run_index,
            run_record_id=row.run_record_id,
            state=row.state,
            monitor=row.monitor,
            rule_outcomes=dict(row.rule_outcomes),
            failed_rules=tuple(row.failed_rules),
            first_failure_time_s=row.first_failure_time_s,
            margin=row.margin,
            sensitive=row.sensitive,
            early_stop_time_s=row.early_stop_time_s,
            created_at=row.created_at,
            case_index=case_index,
            step=row.step,
            encounters=None if row.encounters is None else {relation: list(types) for relation, types in row.encounters.items()},
            encounter_roles=None if row.encounter_roles is None else dict(row.encounter_roles),
        )


@dataclass(frozen=True)
class ClassCoverage:
    """Where one class of a campaign stands: its counts, and its verdicts per run and state."""

    class_id: str
    state: CampaignClassState
    quota: int
    failure_budget: Optional[int]  # None: unlimited
    complete: int
    dropped: int
    in_flight: int
    verdicts: Dict[int, Dict[VerdictState, int]]  # run index to verdict state to count

    def verdict_count(self, state: Optional[VerdictState] = None, run_index: Optional[int] = None) -> int:
        return sum(count for run, states in self.verdicts.items() if run_index is None or run == run_index for verdict_state, count in states.items() if state is None or verdict_state == state)


@dataclass(frozen=True)
class RuleFindings:
    """One rule over the failed verdicts of a step: in how many it failed, and when it failed first (min and median over those verdicts)."""

    rule: str
    count: int
    first_failure_time_min_s: Optional[float]
    first_failure_time_median_s: Optional[float]


@dataclass(frozen=True)
class ClassFindings:
    class_id: str
    cases: int
    passed: int
    failed: int


@dataclass(frozen=True)
class StepFindings:
    """The summary of one step of a campaign that Results shows (operator API `findings`).

    An unmonitored step has statistics only: verdicts, failed_rules and encounter_types stay empty. outputs
    counts the step's outputs (count), the usable ones (valid) and the complete ones;
    durations_s are the running times of the step's finished jobs.
    """

    step: StepKind
    monitored: bool
    cases: Dict[CaseState, int]
    outputs_count: int
    outputs_valid: int
    outputs_complete: int
    verdicts: Dict[VerdictState, int]
    failed_rules: Tuple[RuleFindings, ...]
    encounter_types: Dict[str, int]  # vessel pairs by the first encounter type of each (COLREGSType name); empty without monitored encounters
    classes: Tuple[ClassFindings, ...]
    duration_median_s: Optional[float]
    duration_p90_s: Optional[float]
