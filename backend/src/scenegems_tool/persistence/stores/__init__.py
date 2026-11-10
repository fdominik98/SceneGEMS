"""Transactional primitives the master's node registry, scheduler, lease manager and pipeline engine call.

Every store method returns detached snapshots (records), never ORM rows. Which node gets
which job, and when, is the scheduler's policy (P3.3), and how cases advance is the pipeline
engine's (P4.4); the stores only guarantee that each step is atomic and safe under
concurrency. The node and job stores run each method in its own transaction; the campaign
stores take an optional session, so several calls commit together (store_session).

    node_records.py       snapshots of a node and its capabilities
    node_store.py         register from Hello, heartbeats, status, silent nodes offline
    job_records.py        snapshots of a job, a lease and the outcome of each primitive
    job_lifecycle.py      pure rules: when a lease is current, retries and their backoff, result idempotency
    job_claim.py          what a node can take, and the SKIP LOCKED query that finds it
    job_event_log.py      the append-only history of each job
    job_store.py          submit, claim, accept, renew, release, result, cancel, expire, hold
    store_session.py      the caller's session or a transaction of the method's own
    campaign_records.py   snapshots of campaigns, classes, cases, step outputs, pipeline jobs, cursor positions
    campaign_store.py     campaigns with config versions and classes, kinds, states, events, totals, deletion
    case_store.py         classes with their counts and states, cases and their optimistic moves, step outputs
    pipeline_store.py     intents and links of a case's jobs, the cursor over the job events
    result_records.py     run records, verdicts, coverage and findings
    result_store.py       run records and step verdicts, written once, queries, coverage per class, findings per step
    artifact_records.py   artifact records and references, expiring uploads, unreferenced artifacts for the sweep
    calibration_store.py  calibration results by stack, fingerprints and environment
    setting_stores.py     the cluster's domain configuration and its saved campaign presets
    assurance_stores.py   all campaign and setting stores on one session factory, with a shared transaction
"""

from scenegems_tool.persistence.stores.artifact_records import UPLOAD_ROLE, ArtifactInsert, ArtifactMismatch, ArtifactRecord, ArtifactRecordStore, ArtifactReference, UnknownArtifact
from scenegems_tool.persistence.stores.assurance_stores import AssuranceStores
from scenegems_tool.persistence.stores.calibration_store import CalibrationResult, CalibrationStore, NewCalibrationResult
from scenegems_tool.persistence.stores.campaign_records import (
    EXPLORATION_CLASS_ID,
    EXPLORED_CLASS_PREFIX,
    START_OF_EVENTS,
    CampaignEventRecord,
    CampaignRecord,
    CampaignTotals,
    CaseRecord,
    ClassCounts,
    ClassRecord,
    ClassSpec,
    ConfigVersionRecord,
    CursorPosition,
    EventBatch,
    IntentOutcome,
    NewCase,
    OutputArtifact,
    OutputRecord,
    PipelineJobEvent,
    PipelineJobRecord,
)
from scenegems_tool.persistence.stores.campaign_store import CampaignStateConflict, CampaignStore, UnknownCampaign
from scenegems_tool.persistence.stores.case_store import UNSET, CaseConflict, CaseStore, ClassStateConflict, UnknownCase, UnknownClass
from scenegems_tool.persistence.stores.job_records import CancelOutcome, ExpiredLease, JobEventRecord, JobRecord, Lease, ResultReport, ResultStatus, SubmitOutcome
from scenegems_tool.persistence.stores.job_store import IdempotencyKeyMismatch, JobStore, UnknownJob, UnknownNode
from scenegems_tool.persistence.stores.node_records import NodeRecord, SlotState
from scenegems_tool.persistence.stores.node_store import NodeStore
from scenegems_tool.persistence.stores.pipeline_store import ENGINE_CURSOR, TERMINAL_EVENT_KINDS, CursorConflict, PipelineJobConflict, PipelineStore, UnknownPipelineJob
from scenegems_tool.persistence.stores.result_records import ClassCoverage, ClassFindings, NewRunRecord, NewVerdict, RuleFindings, RunRecord, StepFindings, VerdictRecord
from scenegems_tool.persistence.stores.result_store import ResultStore
from scenegems_tool.persistence.stores.setting_stores import CampaignPresetStore, ClusterDomain, DomainStore, PresetNameTaken, SavedPreset, UnknownPreset

__all__ = [
    "ENGINE_CURSOR",
    "EXPLORATION_CLASS_ID",
    "EXPLORED_CLASS_PREFIX",
    "START_OF_EVENTS",
    "TERMINAL_EVENT_KINDS",
    "UNSET",
    "UPLOAD_ROLE",
    "ArtifactInsert",
    "ArtifactMismatch",
    "ArtifactRecord",
    "ArtifactRecordStore",
    "ArtifactReference",
    "AssuranceStores",
    "CalibrationResult",
    "CalibrationStore",
    "CampaignEventRecord",
    "CampaignPresetStore",
    "CampaignRecord",
    "CampaignStateConflict",
    "CampaignStore",
    "CampaignTotals",
    "CancelOutcome",
    "SlotState",
    "CaseConflict",
    "CaseRecord",
    "CaseStore",
    "ClassCounts",
    "ClassCoverage",
    "ClassFindings",
    "ClassRecord",
    "ClassSpec",
    "ClassStateConflict",
    "ClusterDomain",
    "ConfigVersionRecord",
    "CursorConflict",
    "CursorPosition",
    "DomainStore",
    "EventBatch",
    "ExpiredLease",
    "IdempotencyKeyMismatch",
    "IntentOutcome",
    "JobEventRecord",
    "JobRecord",
    "JobStore",
    "Lease",
    "NewCalibrationResult",
    "NewCase",
    "NewRunRecord",
    "NewVerdict",
    "NodeRecord",
    "NodeStore",
    "OutputArtifact",
    "OutputRecord",
    "PipelineJobConflict",
    "PipelineJobEvent",
    "PipelineJobRecord",
    "PipelineStore",
    "PresetNameTaken",
    "ResultReport",
    "ResultStatus",
    "ResultStore",
    "RuleFindings",
    "RunRecord",
    "SavedPreset",
    "StepFindings",
    "SubmitOutcome",
    "UnknownArtifact",
    "UnknownCampaign",
    "UnknownCase",
    "UnknownClass",
    "UnknownJob",
    "UnknownNode",
    "UnknownPipelineJob",
    "UnknownPreset",
    "VerdictRecord",
]
