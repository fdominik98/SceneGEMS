"""The stores of campaigns, their results and the cluster's settings on one database, and the transaction they share.

The pipeline engine and the operator API take one AssuranceStores. Its transaction() opens
the session that every store method accepts, so one step of the engine commits as a whole.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from sqlalchemy.orm import Session, sessionmaker

from scenegems_tool.persistence.clock import Clock, utc_now
from scenegems_tool.persistence.database import transaction as database_transaction
from scenegems_tool.persistence.stores.artifact_records import ArtifactRecordStore
from scenegems_tool.persistence.stores.calibration_store import CalibrationStore
from scenegems_tool.persistence.stores.campaign_store import CampaignStore
from scenegems_tool.persistence.stores.case_store import CaseStore
from scenegems_tool.persistence.stores.pipeline_store import PipelineStore
from scenegems_tool.persistence.stores.result_store import ResultStore
from scenegems_tool.persistence.stores.setting_stores import CampaignPresetStore, DomainStore


@dataclass(frozen=True)
class AssuranceStores:
    session_factory: sessionmaker[Session]
    campaigns: CampaignStore
    cases: CaseStore
    pipeline: PipelineStore
    results: ResultStore
    artifacts: ArtifactRecordStore
    calibrations: CalibrationStore
    domain: DomainStore
    presets: CampaignPresetStore

    @classmethod
    def create(cls, session_factory: sessionmaker[Session], clock: Clock = utc_now) -> "AssuranceStores":
        return cls(
            session_factory=session_factory,
            campaigns=CampaignStore(session_factory, clock),
            cases=CaseStore(session_factory, clock),
            pipeline=PipelineStore(session_factory, clock),
            results=ResultStore(session_factory, clock),
            artifacts=ArtifactRecordStore(session_factory, clock),
            calibrations=CalibrationStore(session_factory, clock),
            domain=DomainStore(session_factory, clock),
            presets=CampaignPresetStore(session_factory, clock),
        )

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """One transaction for several store calls: committed on success, rolled back on error."""
        with database_transaction(self.session_factory) as session:
            yield session
