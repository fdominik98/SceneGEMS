"""SQLAlchemy tables of the control node's database.

The migrations create exactly these tables; a test compares them.

    base.py             declarative base with constraint names, enum and timestamp columns
    worker_node_tables.py      worker node, worker_node_capability, worker_node_fingerprint and the worker node status
    job_tables.py       job, job_event and the job event kinds
    campaign_tables.py  campaign, campaign_config_version, campaign_class, scenario_case, pipeline_job,
                        pipeline_cursor, run_record, verdict, campaign_event, their states, kinds and steps
    artifact_tables.py  artifact, artifact_reference, calibration_result and the sha256 hex format
    setting_tables.py   cluster_domain (the cluster's domain configuration) and campaign_preset (saved presets)
"""

from scenegems_tool.persistence.schema.artifact_tables import ArtifactHolderKind, ArtifactReferenceRow, ArtifactRow, CalibrationResultRow
from scenegems_tool.persistence.schema.base import Base
from scenegems_tool.persistence.schema.campaign_tables import (
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
    MonitorImplementation,
    PipelineCursorRow,
    PipelineJobRow,
    PipelineStage,
    RunRecordRow,
    RunSource,
    ScenarioCaseRow,
    StepKind,
    TrajectoryGeneratorImplementation,
    VerdictRow,
    VerdictState,
)
from scenegems_tool.persistence.schema.job_tables import HELD_UNTIL, JobEventKind, JobEventRow, JobRow
from scenegems_tool.persistence.schema.setting_tables import CLUSTER_DOMAIN_ROW_ID, CampaignPresetRow, ClusterDomainRow
from scenegems_tool.persistence.schema.worker_node_tables import WorkerNodeCapabilityRow, WorkerNodeComponentRow, WorkerNodeFingerprintRow, WorkerNodeRow, WorkerNodeStatus

__all__ = [
    "CLUSTER_DOMAIN_ROW_ID",
    "HELD_UNTIL",
    "ArtifactHolderKind",
    "ArtifactReferenceRow",
    "ArtifactRow",
    "Base",
    "CalibrationResultRow",
    "CampaignActualState",
    "CampaignClassRow",
    "CampaignClassState",
    "CampaignConfigVersionRow",
    "CampaignDesiredState",
    "CampaignEventKind",
    "CampaignEventRow",
    "CampaignKind",
    "CampaignOrigin",
    "CampaignPresetRow",
    "CampaignRow",
    "CaseState",
    "ClusterDomainRow",
    "JobEventKind",
    "JobEventRow",
    "JobRow",
    "MonitorImplementation",
    "WorkerNodeCapabilityRow",
    "WorkerNodeComponentRow",
    "WorkerNodeFingerprintRow",
    "WorkerNodeRow",
    "WorkerNodeStatus",
    "PipelineCursorRow",
    "PipelineJobRow",
    "PipelineStage",
    "RunRecordRow",
    "RunSource",
    "ScenarioCaseRow",
    "StepKind",
    "TrajectoryGeneratorImplementation",
    "VerdictRow",
    "VerdictState",
]
