"""The link between cases and their jobs, and the engine's cursor over the job events.

Submission is two steps around JobStore.submit: add_intent writes the pipeline job with its
idempotency key (in the transaction that moves the case), link_job records the job id once
the job store returned it. A crash in between leaves an intent without a job; the engine
resubmits it under the same key, and the job store returns the job it may have created.

The cursor is a position (transaction id, event id) in job_event. events_after returns the
events of pipeline jobs after a position, joined with their pipeline job and the job's
current state and result, and the position to advance to. It reads only events of
transactions that have ended (older than the oldest running one), in (tx_id, id) order:
an event that commits after a later id became visible is still read, so no event is skipped,
and a batch never returns an event twice. advance_cursor moves the cursor in the caller's
transaction, so case updates and the cursor commit together.

Every method takes an optional session (see store_session).
"""

from typing import Collection, Dict, List, Optional, Sequence

from sqlalchemy import func, or_, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from scenegems_tool.cluster.protocol.jobs import JobState
from scenegems_tool.persistence.clock import Clock, utc_now
from scenegems_tool.persistence.schema import JobEventKind, JobEventRow, JobRow, PipelineCursorRow, PipelineJobRow, PipelineStage
from scenegems_tool.persistence.stores.campaign_records import START_OF_EVENTS, CursorPosition, EventBatch, IntentOutcome, PipelineJobEvent, PipelineJobRecord
from scenegems_tool.persistence.stores.store_session import session_scope

ENGINE_CURSOR = "pipeline_engine"
TERMINAL_EVENT_KINDS = (JobEventKind.SUCCEEDED, JobEventKind.FAILED, JobEventKind.CANCELLED)
# Transactions with an id below this have all ended, committed or not
SNAPSHOT_HORIZON = text("SELECT pg_snapshot_xmin(pg_current_snapshot())::text::bigint")


class UnknownPipelineJob(LookupError):
    pass


class PipelineJobConflict(ValueError):
    """An intent is linked to another job already, or an idempotency key names another case or stage."""


class CursorConflict(ValueError):
    """The cursor is not where the caller read it: another engine advanced it."""


class PipelineStore:
    def __init__(self, session_factory: sessionmaker[Session], clock: Clock = utc_now):
        self._sessions = session_factory
        self._clock = clock

    # Intents and links

    def add_intent(
        self,
        campaign_id: str,
        case_id: int,
        stage: PipelineStage,
        idempotency_key: str,
        run_index: Optional[int] = None,
        repeat_index: Optional[int] = None,
        submission: Optional[Dict] = None,
        *,
        session: Optional[Session] = None,
    ) -> IntentOutcome:
        """Writes the intent to submit a job for the case's stage, once per idempotency key.

        submission is the JobSubmission as JSON, kept until the job is linked. A second
        intent with the same key returns the first one; one that names another case, stage
        or run raises PipelineJobConflict.
        """
        if stage == PipelineStage.VERDICT:
            raise ValueError("the verdict stage runs no job")
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            statement = (
                insert(PipelineJobRow)
                .values(
                    idempotency_key=idempotency_key,
                    campaign_id=campaign_id,
                    case_id=case_id,
                    stage=stage,
                    run_index=run_index,
                    repeat_index=repeat_index,
                    submission=submission,
                    created_at=now,
                )
                .on_conflict_do_nothing(index_elements=[PipelineJobRow.idempotency_key])
                .returning(PipelineJobRow.id)
            )
            created = scope.execute(statement).scalar_one_or_none() is not None
            row = self._by_key(scope, idempotency_key)
            if not created and (row.campaign_id, row.case_id, row.stage, row.run_index, row.repeat_index) != (campaign_id, case_id, stage, run_index, repeat_index):
                raise PipelineJobConflict(f"idempotency key {idempotency_key!r} belongs to case {row.case_id}, stage {row.stage.value}, run {row.run_index}")
            return IntentOutcome(pipeline_job=PipelineJobRecord.from_row(row), created=created)

    def link_job(self, idempotency_key: str, job_id: str, *, session: Optional[Session] = None) -> PipelineJobRecord:
        """Records the submitted job of an intent and drops the kept submission. Linking the same job again changes nothing."""
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            row = scope.execute(select(PipelineJobRow).where(PipelineJobRow.idempotency_key == idempotency_key).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
            if row is None:
                raise UnknownPipelineJob(idempotency_key)
            if row.job_id is not None and row.job_id != job_id:
                raise PipelineJobConflict(f"pipeline job {idempotency_key!r} is linked to job {row.job_id}, not {job_id}")
            if row.job_id is None:
                row.job_id = job_id
                row.submitted_at = now
                row.submission = None
                scope.flush()
            return PipelineJobRecord.from_row(row)

    def intents_without_job(self, campaign_id: Optional[str] = None, limit: Optional[int] = None, *, session: Optional[Session] = None) -> List[PipelineJobRecord]:
        """Intents not linked to a job yet, oldest first: the ones to (re)submit."""
        with session_scope(self._sessions, session) as scope:
            query = select(PipelineJobRow).where(PipelineJobRow.job_id.is_(None))
            if campaign_id is not None:
                query = query.where(PipelineJobRow.campaign_id == campaign_id)
            return [PipelineJobRecord.from_row(row) for row in scope.execute(query.order_by(PipelineJobRow.id).limit(limit)).scalars()]

    def get_by_key(self, idempotency_key: str, *, session: Optional[Session] = None) -> Optional[PipelineJobRecord]:
        with session_scope(self._sessions, session) as scope:
            row = self._by_key(scope, idempotency_key)
            return None if row is None else PipelineJobRecord.from_row(row)

    def get_by_job_id(self, job_id: str, *, session: Optional[Session] = None) -> Optional[PipelineJobRecord]:
        with session_scope(self._sessions, session) as scope:
            row = scope.execute(select(PipelineJobRow).where(PipelineJobRow.job_id == job_id)).scalar_one_or_none()
            return None if row is None else PipelineJobRecord.from_row(row)

    def pipeline_jobs_of_case(self, case_id: int, *, session: Optional[Session] = None) -> List[PipelineJobRecord]:
        with session_scope(self._sessions, session) as scope:
            query = select(PipelineJobRow).where(PipelineJobRow.case_id == case_id).order_by(PipelineJobRow.id)
            return [PipelineJobRecord.from_row(row) for row in scope.execute(query).scalars()]

    def job_ids_of_campaign(self, campaign_id: str, states: Optional[Collection[JobState]] = None, *, session: Optional[Session] = None) -> List[str]:
        """Ids of the campaign's submitted jobs, optionally only those in some states: what pause holds and stop cancels."""
        with session_scope(self._sessions, session) as scope:
            query = select(PipelineJobRow.job_id).join(JobRow, JobRow.id == PipelineJobRow.job_id).where(PipelineJobRow.campaign_id == campaign_id)
            if states is not None:
                query = query.where(JobRow.state.in_(list(states)))
            return sorted(scope.execute(query).scalars())

    def queued_jobs_by_stage(self, campaign_id: str, *, session: Optional[Session] = None) -> Dict[PipelineStage, int]:
        """Per stage, the campaign's jobs waiting in the queue plus its intents not submitted yet: what backpressure caps."""
        with session_scope(self._sessions, session) as scope:
            waiting = (
                select(PipelineJobRow.stage, func.count())
                .outerjoin(JobRow, JobRow.id == PipelineJobRow.job_id)
                .where(PipelineJobRow.campaign_id == campaign_id, or_(PipelineJobRow.job_id.is_(None), JobRow.state == JobState.QUEUED))
                .group_by(PipelineJobRow.stage)
            )
            return {stage: count for stage, count in scope.execute(waiting)}

    # Event cursor

    def read_cursor(self, name: str = ENGINE_CURSOR, *, lock: bool = False, session: Optional[Session] = None) -> CursorPosition:
        """The cursor's position, the start of the events for a new cursor (which it creates).

        lock holds the cursor row for the caller's transaction, so a second engine waits
        instead of processing the same events.
        """
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            scope.execute(
                insert(PipelineCursorRow)
                .values(name=name, last_tx_id=START_OF_EVENTS.tx_id, last_event_id=START_OF_EVENTS.event_id, updated_at=now)
                .on_conflict_do_nothing(index_elements=[PipelineCursorRow.name])
            )
            query = select(PipelineCursorRow).where(PipelineCursorRow.name == name).execution_options(populate_existing=True)
            if lock:
                query = query.with_for_update()
            row = scope.execute(query).scalar_one()
            return CursorPosition(tx_id=row.last_tx_id, event_id=row.last_event_id)

    def advance_cursor(self, name: str, expected: CursorPosition, to: CursorPosition, *, session: Optional[Session] = None) -> CursorPosition:
        """Moves the cursor from expected to `to`; raises CursorConflict when it is not at expected.

        Moving back is refused, moving to where it is changes nothing.
        """
        if to < expected:
            raise ValueError(f"the cursor moves forward only, from {expected} to {to}")
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            row = scope.execute(select(PipelineCursorRow).where(PipelineCursorRow.name == name).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
            if row is None:
                raise CursorConflict(f"cursor {name!r} does not exist; read it first")
            current = CursorPosition(tx_id=row.last_tx_id, event_id=row.last_event_id)
            if current != expected:
                raise CursorConflict(f"cursor {name!r} is at {current}, not {expected}")
            if to != current:
                row.last_tx_id, row.last_event_id, row.updated_at = to.tx_id, to.event_id, now
                scope.flush()
            return to

    def events_after(self, position: CursorPosition, limit: int = 500, kinds: Optional[Sequence[JobEventKind]] = TERMINAL_EVENT_KINDS, *, session: Optional[Session] = None) -> EventBatch:
        """Up to limit events of pipeline jobs after position, of the given kinds (all with None).

        The batch's position is that of its last event when the batch is full; otherwise it
        is the last event of any job any kind that has ended its transaction, so the cursor
        passes over events that need no processing.
        """
        if limit < 1:
            raise ValueError(f"limit must be at least 1, got {limit}")
        with session_scope(self._sessions, session) as scope:
            # One horizon for both queries: every transaction below it has ended, so both see the same events below it
            horizon = scope.execute(SNAPSHOT_HORIZON).scalar_one()
            after = tuple_(JobEventRow.tx_id, JobEventRow.id) > tuple_(position.tx_id, position.event_id)
            query = (
                select(JobEventRow, PipelineJobRow, JobRow.state, JobRow.result, JobRow.error)
                .join(PipelineJobRow, PipelineJobRow.job_id == JobEventRow.job_id)
                .join(JobRow, JobRow.id == JobEventRow.job_id)
                .where(after, JobEventRow.tx_id < horizon)
                .order_by(JobEventRow.tx_id, JobEventRow.id)
                .limit(limit)
            )
            if kinds is not None:
                query = query.where(JobEventRow.kind.in_(list(kinds)))
            events = tuple(
                PipelineJobEvent(
                    position=CursorPosition(tx_id=event.tx_id, event_id=event.id),
                    event_id=event.id,
                    job_id=event.job_id,
                    at=event.at,
                    kind=event.kind,
                    attempt=event.attempt,
                    worker_node_id=event.worker_node_id,
                    detail=dict(event.detail),
                    pipeline_job=PipelineJobRecord.from_row(pipeline_job),
                    job_state=job_state,
                    job_result=None if job_result is None else dict(job_result),
                    job_error=job_error,
                )
                for event, pipeline_job, job_state, job_result, job_error in scope.execute(query)
            )
            if len(events) == limit:
                return EventBatch(events=events, position=events[-1].position)
            last = scope.execute(select(JobEventRow.tx_id, JobEventRow.id).where(after, JobEventRow.tx_id < horizon).order_by(JobEventRow.tx_id.desc(), JobEventRow.id.desc()).limit(1)).first()
            return EventBatch(events=events, position=position if last is None else CursorPosition(tx_id=last[0], event_id=last[1]))

    # Helpers

    @staticmethod
    def _by_key(session: Session, idempotency_key: str) -> Optional[PipelineJobRow]:
        return session.execute(select(PipelineJobRow).where(PipelineJobRow.idempotency_key == idempotency_key).execution_options(populate_existing=True)).scalar_one_or_none()
