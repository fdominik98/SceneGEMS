"""Detached snapshots of campaigns, classes, cases, step outputs, pipeline jobs and the engine's event cursor."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from scenegems_tool.cluster.protocol.jobs import JobState
from scenegems_tool.persistence.schema import (
    CampaignActualState,
    CampaignClassRow,
    CampaignClassState,
    CampaignConfigVersionRow,
    CampaignDesiredState,
    CampaignEventKind,
    CampaignEventRow,
    CampaignKind,
    CampaignOrigin,
    CampaignRow,
    CaseState,
    JobEventKind,
    PipelineJobRow,
    PipelineStage,
    ScenarioCaseRow,
    StepKind,
    VerdictState,
)


@dataclass(frozen=True)
class ClassSpec:
    """A class as a new campaign takes it: from the catalog, with its quota and failure budget (None: unlimited)."""

    class_id: str
    content_hash: str
    vessel_count: int
    obstacle_count: int
    quota: int
    failure_budget: Optional[int]


@dataclass(frozen=True)
class CampaignRecord:
    campaign_id: str
    name: str
    desired_state: CampaignDesiredState
    actual_state: CampaignActualState
    state_reason: Optional[str]
    config_version: int
    pinned_fingerprints: Dict[str, str]
    created_at: datetime
    updated_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    kind: CampaignKind = CampaignKind.CAMPAIGN
    origin: Optional[CampaignOrigin] = None  # None for campaigns made before Phase 6

    @classmethod
    def from_row(cls, row: CampaignRow) -> "CampaignRecord":
        return cls(
            campaign_id=row.id,
            name=row.name,
            desired_state=row.desired_state,
            actual_state=row.actual_state,
            state_reason=row.state_reason,
            config_version=row.config_version,
            pinned_fingerprints=dict(row.pinned_fingerprints),
            created_at=row.created_at,
            updated_at=row.updated_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
            kind=row.kind,
            origin=row.origin,
        )


@dataclass(frozen=True)
class CampaignTotals:
    """What a campaign list row shows without a detail call: its cases by state and its verdicts by step and state."""

    cases: Dict[CaseState, int] = field(default_factory=dict)
    verdicts: Dict[StepKind, Dict[VerdictState, int]] = field(default_factory=dict)


@dataclass(frozen=True)
class ConfigVersionRecord:
    campaign_id: str
    version: int
    config: Dict[str, Any]
    config_hash: str
    created_at: datetime

    @classmethod
    def from_row(cls, row: CampaignConfigVersionRow) -> "ConfigVersionRecord":
        return cls(campaign_id=row.campaign_id, version=row.version, config=dict(row.config), config_hash=row.config_hash, created_at=row.created_at)


@dataclass(frozen=True)
class ClassRecord:
    campaign_id: str
    class_id: str
    content_hash: str
    vessel_count: int
    obstacle_count: int
    quota: int
    failure_budget: Optional[int]  # None: unlimited, the class is never abandoned
    complete_count: int
    dropped_count: int  # dropped and failed cases: the failure budget's use
    in_flight_count: int
    state: CampaignClassState
    state_reason: Optional[str]
    created_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime]

    @property
    def failure_budget_left(self) -> Optional[int]:
        return None if self.failure_budget is None else self.failure_budget - self.dropped_count

    @classmethod
    def from_row(cls, row: CampaignClassRow) -> "ClassRecord":
        return cls(
            campaign_id=row.campaign_id,
            class_id=row.class_id,
            content_hash=row.content_hash,
            vessel_count=row.vessel_count,
            obstacle_count=row.obstacle_count,
            quota=row.quota,
            failure_budget=row.failure_budget,
            complete_count=row.complete_count,
            dropped_count=row.dropped_count,
            in_flight_count=row.in_flight_count,
            state=row.state,
            state_reason=row.state_reason,
            created_at=row.created_at,
            updated_at=row.updated_at,
            finished_at=row.finished_at,
        )


@dataclass(frozen=True)
class ClassCounts:
    """Case counts of one class; as stored on the class, or counted from its cases."""

    complete: int = 0
    dropped: int = 0
    in_flight: int = 0


@dataclass(frozen=True)
class CampaignEventRecord:
    event_id: int
    campaign_id: str
    at: datetime
    kind: CampaignEventKind
    class_id: Optional[str]
    detail: Dict[str, Any]

    @classmethod
    def from_row(cls, row: CampaignEventRow) -> "CampaignEventRecord":
        return cls(event_id=row.id, campaign_id=row.campaign_id, at=row.at, kind=row.kind, class_id=row.class_id, detail=dict(row.detail))


@dataclass(frozen=True)
class CaseRecord:
    case_id: int
    campaign_id: str
    class_id: str
    case_index: int
    seed: int
    config_version: int
    stage: PipelineStage
    state: CaseState
    version: int  # pass it back to move_case for an optimistic update
    scene_artifact: Optional[str]
    trajectories_artifact: Optional[str]
    trajectories_complete: Optional[bool]
    progress: Dict[str, Any]
    reason: Optional[str]
    created_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime]
    input_artifact: Optional[str] = None  # what the first configured step took; None for catalog classes
    input_source: Optional[Dict[str, Any]] = None  # {campaign_id, case_id, step} or {file}

    @classmethod
    def from_row(cls, row: ScenarioCaseRow) -> "CaseRecord":
        return cls(
            case_id=row.id,
            campaign_id=row.campaign_id,
            class_id=row.class_id,
            case_index=row.case_index,
            seed=row.seed,
            config_version=row.config_version,
            stage=row.stage,
            state=row.state,
            version=row.version,
            scene_artifact=row.scene_artifact,
            trajectories_artifact=row.trajectories_artifact,
            trajectories_complete=row.trajectories_complete,
            progress=dict(row.progress),
            reason=row.reason,
            created_at=row.created_at,
            updated_at=row.updated_at,
            finished_at=row.finished_at,
            input_artifact=row.input_artifact,
            input_source=None if row.input_source is None else dict(row.input_source),
        )


@dataclass(frozen=True)
class NewCase:
    """A case to create: its class, its index in the class and its seed, and the input of its first step when it has one."""

    class_id: str
    case_index: int
    seed: int
    config_version: int = 1
    stage: PipelineStage = PipelineStage.GENERATE_SCENE
    input_artifact: Optional[str] = None  # sha256 of a functional scenario, a scene or trajectories
    input_source: Optional[Dict[str, Any]] = None


@dataclass(frozen=True)
class OutputArtifact:
    """The artifact an output row points at; size, kind and media type are None once the artifact record is gone."""

    sha256: str
    size_bytes: Optional[int]
    kind: Optional[str]
    media_type: Optional[str]
    pointer: Optional[str] = None  # JSON pointer into the document, such as /trajectories


@dataclass(frozen=True)
class OutputRecord:
    """One output of one step of a case: its scene, its trajectories, or one simulated run (one row per case without runs yet).

    valid says the step gave a usable output: the output exists and the case did not drop at
    the step. complete is the trajectories' completeness (None for scenes). verdict_state and
    failed_rules are the step's verdict, None while the step has none (or is not monitored).
    """

    step: StepKind
    case_id: int
    case_index: int
    class_id: str
    state: CaseState
    reason: Optional[str]
    artifact: Optional[OutputArtifact]
    valid: bool
    complete: Optional[bool]
    run_index: Optional[int]
    repeat_index: Optional[int]
    run_record_id: Optional[int]
    verdict_state: Optional[VerdictState]
    failed_rules: Tuple[str, ...]
    input_source: Optional[Dict[str, Any]]


@dataclass(frozen=True)
class PipelineJobRecord:
    pipeline_job_id: int
    idempotency_key: str
    campaign_id: str
    case_id: int
    stage: PipelineStage
    run_index: Optional[int]
    repeat_index: Optional[int]
    submission: Optional[Dict[str, Any]]  # kept until the job is linked
    job_id: Optional[str]  # None while it is an intent
    created_at: datetime
    submitted_at: Optional[datetime]

    @property
    def is_intent(self) -> bool:
        return self.job_id is None

    @classmethod
    def from_row(cls, row: PipelineJobRow) -> "PipelineJobRecord":
        return cls(
            pipeline_job_id=row.id,
            idempotency_key=row.idempotency_key,
            campaign_id=row.campaign_id,
            case_id=row.case_id,
            stage=row.stage,
            run_index=row.run_index,
            repeat_index=row.repeat_index,
            submission=None if row.submission is None else dict(row.submission),
            job_id=row.job_id,
            created_at=row.created_at,
            submitted_at=row.submitted_at,
        )


@dataclass(frozen=True)
class IntentOutcome:
    pipeline_job: PipelineJobRecord
    created: bool  # False when an intent with the same idempotency key existed


@dataclass(frozen=True, order=True)
class CursorPosition:
    """A position in the job events: (transaction id, event id) of the last event processed."""

    tx_id: int = 0
    event_id: int = 0


START_OF_EVENTS = CursorPosition()


@dataclass(frozen=True)
class PipelineJobEvent:
    """A job event of a pipeline job, with the job's state, result and error at reading time."""

    position: CursorPosition
    event_id: int
    job_id: str
    at: datetime
    kind: JobEventKind
    attempt: int
    node_id: Optional[str]
    detail: Dict[str, Any]
    pipeline_job: PipelineJobRecord
    job_state: JobState
    job_result: Optional[Dict[str, Any]]
    job_error: Optional[str]


@dataclass(frozen=True)
class EventBatch:
    """Events after a cursor, and the position to advance the cursor to once they are processed.

    The position may lie beyond the last event returned: events of other jobs or of other
    kinds in between need no processing, so the cursor skips them.
    """

    events: Tuple[PipelineJobEvent, ...]
    position: CursorPosition
