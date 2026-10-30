"""Campaigns, their classes and cases, the jobs of each case, and what the runs produced.

A campaign runs one immutable, versioned config over a set of classes (functional
scenarios), each with a quota of complete cases and a failure budget. A case is one
scenario of one class, numbered per class, with a seed derived from the campaign seed. The
pipeline engine moves each case through its stages; pipeline_job links a case to the jobs
it submitted, and pipeline_cursor is how far the engine has read the job events. Run
records and verdicts are the results, one per case and run (and repeat, for run records).

A campaign runs a consecutive part of the chain scene generation, trajectory generation,
simulation (Phase 6). Its kind says whether it is a campaign or a workbench entry (a run
of one step) and its origin who made it. A case's input is the content its first step
takes (a functional scenario, a scene or trajectories); verdicts carry the step they judge.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Float, ForeignKey, ForeignKeyConstraint, Identity, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from scenegems_tool.persistence.schema.artifact_tables import SHA256_HEX_LENGTH, sha256_hex_check
from scenegems_tool.persistence.schema.base import Base, enum_column, utc_timestamp


class CampaignKind(str, Enum):
    CAMPAIGN = "campaign"  # defined in the wizard or the CLI
    WORKBENCH = "workbench"  # one workbench run or a recorded live session


class CampaignOrigin(str, Enum):
    """Who made the campaign: the wizard or the CLI for campaigns, a workbench page or a live session for workbench entries."""

    WIZARD = "wizard"
    CLI = "cli"
    SCENE_GENERATION = "scene_generation"
    TRAJECTORY_GENERATION = "trajectory_generation"
    SIMULATION = "simulation"
    LIVE_SESSION = "live_session"

    @property
    def kind(self) -> "CampaignKind":
        return CampaignKind.CAMPAIGN if self in (CampaignOrigin.WIZARD, CampaignOrigin.CLI) else CampaignKind.WORKBENCH


class StepKind(str, Enum):
    """The step a verdict judges or an output belongs to: the generated scene, the planned trajectories or a simulated run."""

    SCENE = "scene"
    TRAJECTORIES = "trajectories"
    SIMULATION = "simulation"


class RunSource(str, Enum):
    JOB = "job"  # a simulation job of the cluster
    LIVE_SESSION = "live_session"  # a live session the gateway recorded


class CampaignDesiredState(str, Enum):
    """What the operator wants; the engine converges the actual state to it."""

    RUNNING = "running"
    PAUSED = "paused"  # queued jobs held, no new cases
    DRAINING = "draining"  # started cases finish, no new ones
    STOPPED = "stopped"  # queued and leased jobs cancelled; final


class CampaignActualState(str, Enum):
    CREATED = "created"  # not started by the engine yet
    RUNNING = "running"
    PAUSED = "paused"
    DRAINING = "draining"
    STALLED = "stalled"  # wants to run, but no node runs the campaign's pinned release
    STOPPED = "stopped"  # final: stopped by the operator
    COMPLETED = "completed"  # final: every class complete or abandoned

    @property
    def is_final(self) -> bool:
        return self in (CampaignActualState.STOPPED, CampaignActualState.COMPLETED)


class CampaignClassState(str, Enum):
    OPEN = "open"
    COMPLETE = "complete"  # its quota of complete cases is known
    ABANDONED = "abandoned"  # its failure budget is used up, or the campaign stopped first


class PipelineStage(str, Enum):
    """The stages of a case. Every stage but verdict runs as a job; verdict is written by the engine."""

    GENERATE_SCENE = "generate_scene"
    MONITOR_SCENE = "monitor_scene"  # post_hoc monitor over the scene as a one-scene log
    GENERATE_TRAJECTORIES = "generate_trajectories"
    MONITOR_TRAJECTORIES = "monitor_trajectories"  # post_hoc monitor over the planned trajectories
    SIMULATE = "simulate"
    MONITOR = "monitor"  # post_hoc monitor only; live runs inside simulate, empty has no job
    CALIBRATE = "calibrate"  # calibration.deviation over the repeats of one run
    VERDICT = "verdict"


class CaseState(str, Enum):
    ACTIVE = "active"  # started, in flight
    COMPLETE = "complete"  # every run has its verdict
    DROPPED = "dropped"  # invalid scene or no complete trajectory; replaced within the failure budget
    FAILED = "failed"  # a job ran out of attempts; quarantined with the error, counts against the failure budget
    CANCELLED = "cancelled"  # above the quota, or the campaign stopped

    @property
    def is_final(self) -> bool:
        return self != CaseState.ACTIVE


class TrajectoryGeneratorImplementation(str, Enum):
    MONITOR_DRIVEN_RRT = "monitor_driven_rrt"
    STRAIGHT = "straight"


class MonitorImplementation(str, Enum):
    POST_HOC = "post_hoc"
    LIVE = "live"
    EMPTY = "empty"  # judges nothing; the verdict is unmonitored


class VerdictState(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNMONITORED = "unmonitored"  # the empty monitor


class CampaignEventKind(str, Enum):
    CREATED = "created"
    DESIRED_STATE_CHANGED = "desired_state_changed"  # an operator control
    STARTED = "started"
    PAUSED = "paused"
    RESUMED = "resumed"
    DRAINING = "draining"
    STALLED = "stalled"
    STOPPED = "stopped"
    COMPLETED = "completed"
    CLASS_COMPLETE = "class_complete"
    CLASS_ABANDONED = "class_abandoned"
    ENGINE_STARTED = "engine_started"  # the engine (re)started and reconciled the campaign
    NOTE = "note"


# A campaign's origin is the wizard or the CLI, a workbench entry's one of the others
KIND_OF_ORIGIN_CHECK = "origin IS NULL OR (kind = 'campaign') = (origin IN ('wizard', 'cli'))"


class CampaignRow(Base):
    __tablename__ = "campaign"
    __table_args__ = (
        CheckConstraint("config_version >= 1", name="config_version_positive"),
        CheckConstraint("actual_state NOT IN ('stopped', 'completed') OR finished_at IS NOT NULL", name="finished_when_final"),
        CheckConstraint(KIND_OF_ORIGIN_CHECK, name="origin_of_the_kind"),
        Index("ix_campaign_created_at", "created_at"),
        Index("ix_campaign_kind_created_at", "kind", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    kind: Mapped[CampaignKind] = mapped_column(enum_column(CampaignKind, "kind"))
    origin: Mapped[Optional[CampaignOrigin]] = mapped_column(enum_column(CampaignOrigin, "origin"))  # None for campaigns made before Phase 6
    desired_state: Mapped[CampaignDesiredState] = mapped_column(enum_column(CampaignDesiredState, "desired_state"))
    actual_state: Mapped[CampaignActualState] = mapped_column(enum_column(CampaignActualState, "actual_state"))
    state_reason: Mapped[Optional[str]] = mapped_column(Text)  # why it is stalled, for example
    config_version: Mapped[int] = mapped_column(Integer)  # the current campaign_config_version
    pinned_fingerprints: Mapped[Dict[str, str]] = mapped_column(JSONB)  # image name to fingerprint; every job of the campaign requires them
    created_at: Mapped[datetime] = mapped_column(utc_timestamp())
    updated_at: Mapped[datetime] = mapped_column(utc_timestamp())
    started_at: Mapped[Optional[datetime]] = mapped_column(utc_timestamp())
    finished_at: Mapped[Optional[datetime]] = mapped_column(utc_timestamp())


class CampaignConfigVersionRow(Base):
    """A campaign config as validated at creation; versions are only ever added."""

    __tablename__ = "campaign_config_version"
    __table_args__ = (
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(sha256_hex_check("config_hash"), name="config_hash_is_sha256_hex"),
    )

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaign.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    config: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    config_hash: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH))  # sha256 of the config's canonical JSON
    created_at: Mapped[datetime] = mapped_column(utc_timestamp())


class CampaignClassRow(Base):
    """One class of a campaign, its content pinned by hash, with its quota and its counts.

    The counts follow the case states (the case store updates them with every case change):
    complete counts complete cases, dropped counts dropped and failed ones (the failure
    budget's use), in flight counts active ones.
    """

    __tablename__ = "campaign_class"
    __table_args__ = (
        CheckConstraint(sha256_hex_check("content_hash"), name="content_hash_is_sha256_hex"),
        CheckConstraint("quota >= 1", name="quota_positive"),
        CheckConstraint("failure_budget >= 0", name="failure_budget_not_negative"),
        CheckConstraint("vessel_count >= 1 AND obstacle_count >= 0", name="counts_of_the_scenario"),
        CheckConstraint("complete_count >= 0 AND dropped_count >= 0 AND in_flight_count >= 0", name="case_counts_not_negative"),
        CheckConstraint("state = 'open' OR finished_at IS NOT NULL", name="finished_when_closed"),
        Index("ix_campaign_class_campaign_id_state", "campaign_id", "state"),
    )

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaign.id", ondelete="CASCADE"), primary_key=True)
    class_id: Mapped[str] = mapped_column(String(256), primary_key=True)  # path in the catalog without extension
    content_hash: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH))
    vessel_count: Mapped[int] = mapped_column(Integer)
    obstacle_count: Mapped[int] = mapped_column(Integer)
    quota: Mapped[int] = mapped_column(Integer)
    failure_budget: Mapped[Optional[int]] = mapped_column(Integer)  # NULL: unlimited, the class is never abandoned
    complete_count: Mapped[int] = mapped_column(Integer)
    dropped_count: Mapped[int] = mapped_column(Integer)
    in_flight_count: Mapped[int] = mapped_column(Integer)
    state: Mapped[CampaignClassState] = mapped_column(enum_column(CampaignClassState, "state"))
    state_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(utc_timestamp())
    updated_at: Mapped[datetime] = mapped_column(utc_timestamp())
    finished_at: Mapped[Optional[datetime]] = mapped_column(utc_timestamp())


class ScenarioCaseRow(Base):
    __tablename__ = "scenario_case"
    __table_args__ = (
        ForeignKeyConstraint(["campaign_id", "class_id"], ["campaign_class.campaign_id", "campaign_class.class_id"], name="fk_scenario_case_campaign_class", ondelete="CASCADE"),
        UniqueConstraint("campaign_id", "class_id", "case_index"),
        CheckConstraint("case_index >= 0", name="case_index_not_negative"),
        CheckConstraint("seed >= 0", name="seed_not_negative"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint(sha256_hex_check("scene_artifact", nullable=True), name="scene_artifact_is_sha256_hex"),
        CheckConstraint(sha256_hex_check("trajectories_artifact", nullable=True), name="trajectories_artifact_is_sha256_hex"),
        CheckConstraint(sha256_hex_check("input_artifact", nullable=True), name="input_artifact_is_sha256_hex"),
        CheckConstraint("(state = 'active') = (finished_at IS NULL)", name="finished_when_final"),
        Index("ix_scenario_case_campaign_id_state", "campaign_id", "state"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaign.id", ondelete="CASCADE"))
    class_id: Mapped[str] = mapped_column(String(256))
    case_index: Mapped[int] = mapped_column(Integer)  # 0, 1, 2, ... per class
    seed: Mapped[int] = mapped_column(BigInteger)  # from the campaign seed, the class id and the index
    config_version: Mapped[int] = mapped_column(Integer)  # the config version the case started under
    stage: Mapped[PipelineStage] = mapped_column(enum_column(PipelineStage, "stage"))
    state: Mapped[CaseState] = mapped_column(enum_column(CaseState, "state"))
    version: Mapped[int] = mapped_column(Integer)  # raised by every change, for optimistic updates
    # What the first configured step takes: a functional scenario given as content, a scene or trajectories; None for catalog classes
    input_artifact: Mapped[Optional[str]] = mapped_column(String(SHA256_HEX_LENGTH))
    input_source: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)  # where the input came from: {campaign_id, case_id, step} or {file}
    scene_artifact: Mapped[Optional[str]] = mapped_column(String(SHA256_HEX_LENGTH))
    trajectories_artifact: Mapped[Optional[str]] = mapped_column(String(SHA256_HEX_LENGTH))  # the generator's output, input to every run
    trajectories_complete: Mapped[Optional[bool]] = mapped_column(Boolean)
    progress: Mapped[Dict[str, Any]] = mapped_column(JSONB)  # the engine's per-run bookkeeping
    reason: Mapped[Optional[str]] = mapped_column(Text)  # why it dropped out, failed or was cancelled
    created_at: Mapped[datetime] = mapped_column(utc_timestamp())
    updated_at: Mapped[datetime] = mapped_column(utc_timestamp())
    finished_at: Mapped[Optional[datetime]] = mapped_column(utc_timestamp())


class PipelineJobRow(Base):
    """A job a case needs, written as an intent before submission and linked to the job after it.

    The engine writes the intent with its idempotency key first, so a crash between the
    intent and the submission resubmits under the same key, which the job store
    deduplicates.
    """

    __tablename__ = "pipeline_job"
    __table_args__ = (
        CheckConstraint("run_index IS NULL OR run_index >= 0", name="run_index_not_negative"),
        CheckConstraint("stage <> 'verdict'", name="stage_runs_as_a_job"),
        CheckConstraint("(job_id IS NULL) = (submitted_at IS NULL)", name="submitted_when_linked"),
        Index("ix_pipeline_job_case_id", "case_id"),
        Index("ix_pipeline_job_campaign_id_stage", "campaign_id", "stage"),
        Index("ix_pipeline_job_intents", "campaign_id", "id", postgresql_where=text("job_id IS NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(256), unique=True)  # also the job's idempotency key
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaign.id", ondelete="CASCADE"))
    case_id: Mapped[int] = mapped_column(ForeignKey("scenario_case.id", ondelete="CASCADE"))
    stage: Mapped[PipelineStage] = mapped_column(enum_column(PipelineStage, "stage"))
    run_index: Mapped[Optional[int]] = mapped_column(Integer)  # for the per-run stages
    repeat_index: Mapped[Optional[int]] = mapped_column(Integer)
    submission: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)  # the JobSubmission to send, kept until the job is linked
    job_id: Mapped[Optional[str]] = mapped_column(ForeignKey("job.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(utc_timestamp())
    submitted_at: Mapped[Optional[datetime]] = mapped_column(utc_timestamp())


class PipelineCursorRow(Base):
    """How far a reader (the engine) has processed the job events.

    The position is (transaction id, event id) of the last event processed: events are
    read in that order and only from transactions that have ended, so an event that
    commits late is never skipped (see job_tables.JobEventRow.tx_id).
    """

    __tablename__ = "pipeline_cursor"
    __table_args__ = (CheckConstraint("last_tx_id >= 0 AND last_event_id >= 0", name="position_not_negative"),)

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_tx_id: Mapped[int] = mapped_column(BigInteger)
    last_event_id: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(utc_timestamp())


class RunRecordRow(Base):
    """One simulation run of a case: everything needed to repeat it and to trust it."""

    __tablename__ = "run_record"
    __table_args__ = (
        UniqueConstraint("case_id", "run_index", "repeat_index"),
        CheckConstraint("run_index >= 0 AND repeat_index >= 0", name="indexes_not_negative"),
        CheckConstraint("seed >= 0", name="seed_not_negative"),
        CheckConstraint("steps IS NULL OR steps >= 0", name="steps_not_negative"),
        Index("ix_run_record_campaign_id_class_id", "campaign_id", "class_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("scenario_case.id", ondelete="CASCADE"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaign.id", ondelete="CASCADE"))  # the case's, for queries
    class_id: Mapped[str] = mapped_column(String(256))  # the case's, for queries
    run_index: Mapped[int] = mapped_column(Integer)  # the run of the config's execution section
    repeat_index: Mapped[int] = mapped_column(Integer)
    source: Mapped[RunSource] = mapped_column(enum_column(RunSource, "source"))
    # None when the trajectories came from an input item or a live session
    trajectory_generator: Mapped[Optional[TrajectoryGeneratorImplementation]] = mapped_column(enum_column(TrajectoryGeneratorImplementation, "trajectory_generator"))
    trajectories_complete: Mapped[bool] = mapped_column(Boolean)  # whether the generator found complete trajectories
    stack: Mapped[Dict[str, Any]] = mapped_column(JSONB)  # the triple per vessel, adapters and stack parameters
    repeatability_tier: Mapped[Optional[str]] = mapped_column(String(32))  # exact, bounded or none, from the resolver
    environment: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    seed: Mapped[int] = mapped_column(BigInteger)  # the run seed
    dt: Mapped[Optional[float]] = mapped_column(Float)
    steps: Mapped[Optional[int]] = mapped_column(Integer)
    state_digest: Mapped[Optional[str]] = mapped_column(String(128))
    artifacts: Mapped[Dict[str, str]] = mapped_column(JSONB)  # role (trajectories, state_log, frames) to sha256
    job_id: Mapped[Optional[str]] = mapped_column(ForeignKey("job.id"))  # the simulation job
    node_id: Mapped[Optional[str]] = mapped_column(String(128))  # no foreign key: a node may be removed later
    fingerprints: Mapped[Dict[str, str]] = mapped_column(JSONB)  # image name to fingerprint the run used
    durations_s: Mapped[Dict[str, float]] = mapped_column(JSONB)  # seconds per stage and job phase
    created_at: Mapped[datetime] = mapped_column(utc_timestamp())


class VerdictRow(Base):
    """The judgement of one step of a case by its monitor: of the scene, of the trajectories, or of one run."""

    __tablename__ = "verdict"
    __table_args__ = (
        UniqueConstraint("case_id", "step", "run_index"),
        CheckConstraint("run_index >= 0", name="run_index_not_negative"),
        CheckConstraint("step = 'simulation' OR run_index = 0", name="one_verdict_per_generation_step"),
        CheckConstraint("(state = 'unmonitored') = (monitor = 'empty')", name="unmonitored_by_the_empty_monitor"),
        CheckConstraint("early_stop_time_s IS NULL OR monitor = 'live'", name="early_stop_by_the_live_monitor"),
        CheckConstraint("first_failure_time_s IS NULL OR state = 'failed'", name="failure_time_only_when_failed"),
        Index("ix_verdict_campaign_id_class_id_state", "campaign_id", "class_id", "state"),
        Index("ix_verdict_campaign_id_state", "campaign_id", "state"),
        Index("ix_verdict_campaign_id_step_state", "campaign_id", "step", "state"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("scenario_case.id", ondelete="CASCADE"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaign.id", ondelete="CASCADE"))
    class_id: Mapped[str] = mapped_column(String(256))
    step: Mapped[StepKind] = mapped_column(enum_column(StepKind, "step"))
    run_index: Mapped[int] = mapped_column(Integer)  # 0 for the scene and trajectory steps
    run_record_id: Mapped[Optional[int]] = mapped_column(ForeignKey("run_record.id", ondelete="SET NULL"))  # the run judged
    state: Mapped[VerdictState] = mapped_column(enum_column(VerdictState, "state"))
    monitor: Mapped[MonitorImplementation] = mapped_column(enum_column(MonitorImplementation, "monitor"))
    rule_outcomes: Mapped[Dict[str, Any]] = mapped_column(JSONB)  # per rule outcome as the monitor reports it
    failed_rules: Mapped[List[str]] = mapped_column(JSONB)
    first_failure_time_s: Mapped[Optional[float]] = mapped_column(Float)  # earliest failure over all rules
    margin: Mapped[Optional[float]] = mapped_column(Float)  # empty until the monitor reports margins
    sensitive: Mapped[bool] = mapped_column(Boolean)  # the run's stack is bounded and not calibrated, or the margin is small
    early_stop_time_s: Mapped[Optional[float]] = mapped_column(Float)  # when the live monitor stopped the run
    encounters: Mapped[Optional[Dict[str, List[str]]]] = mapped_column(
        JSONB(none_as_null=True)
    )  # per relation, as in rule_outcomes, the COLREGSType names in order of first appearance; NULL before 0010
    created_at: Mapped[datetime] = mapped_column(utc_timestamp())


class CampaignEventRow(Base):
    """The audit trail of a campaign. Rows are only ever inserted."""

    __tablename__ = "campaign_event"
    __table_args__ = (Index("ix_campaign_event_campaign_id_id", "campaign_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaign.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(utc_timestamp())
    kind: Mapped[CampaignEventKind] = mapped_column(enum_column(CampaignEventKind, "kind"))
    class_id: Mapped[Optional[str]] = mapped_column(String(256))
    detail: Mapped[Dict[str, Any]] = mapped_column(JSONB)
