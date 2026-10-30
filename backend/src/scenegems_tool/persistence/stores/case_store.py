"""Classes and cases of a campaign: case creation, optimistic moves between stages and states, counts.

A class's counts follow its cases: every creation and every state change of a case updates
them in the same transaction (active cases count as in flight, complete as complete,
dropped and failed as dropped, cancelled in none), so they never drift from the cases.
recount_classes rebuilds them from the cases, for checks after a restart.

A case is moved with the version it was read at. When another writer changed it since,
move_case raises CaseConflict and changes nothing. A final case (complete, dropped, failed,
cancelled) keeps its state; its other fields (artifacts after retention, progress) may
still change.

The outputs of a step (list_outputs) are what the history browses: per case its scene or
its trajectories, or per run record its state log, with the step's verdict. A case belongs
to a step's outputs once it reached the step (its stage is the step's or a later one) or
has the step's output. The rule is meant for steps the campaign runs: asked for a step
before the campaign's first, it lists the cases that started later too.

Every method takes an optional session (see store_session).
"""

from typing import Any, Collection, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from scenegems_tool.persistence.clock import Clock, utc_now
from scenegems_tool.persistence.schema import ArtifactRow, CampaignClassRow, CampaignClassState, CaseState, PipelineStage, RunRecordRow, ScenarioCaseRow, StepKind, VerdictRow
from scenegems_tool.persistence.schema.artifact_tables import require_sha256_hex
from scenegems_tool.persistence.stores.campaign_records import CaseRecord, ClassCounts, ClassRecord, NewCase, OutputArtifact, OutputRecord
from scenegems_tool.persistence.stores.store_session import session_scope

# The class count each case state adds to; cancelled cases count in none
COUNT_COLUMN_OF_STATE = {
    CaseState.ACTIVE: "in_flight_count",
    CaseState.COMPLETE: "complete_count",
    CaseState.DROPPED: "dropped_count",
    CaseState.FAILED: "dropped_count",
}

# The stages of a case in chain order; a case at a stage has reached every step that starts at or before it
STAGE_ORDER = (
    PipelineStage.GENERATE_SCENE,
    PipelineStage.MONITOR_SCENE,
    PipelineStage.GENERATE_TRAJECTORIES,
    PipelineStage.MONITOR_TRAJECTORIES,
    PipelineStage.SIMULATE,
    PipelineStage.MONITOR,
    PipelineStage.CALIBRATE,
    PipelineStage.VERDICT,
)
FIRST_STAGE_OF_STEP = {StepKind.SCENE: PipelineStage.GENERATE_SCENE, StepKind.TRAJECTORIES: PipelineStage.GENERATE_TRAJECTORIES, StepKind.SIMULATION: PipelineStage.SIMULATE}
TRAJECTORIES_POINTER = "/trajectories"  # where the trajectories are in a trajectory generation's trajectory data
STATE_LOG_ROLE = "state_log"  # the run record's artifact role of the simulated states


def stages_from(stage: PipelineStage) -> Tuple[PipelineStage, ...]:
    return STAGE_ORDER[STAGE_ORDER.index(stage) :]


def output_hash_of(step: StepKind):
    """The column of a step's output: the case's scene or trajectories, or the run record's state log."""
    if step == StepKind.SCENE:
        return ScenarioCaseRow.scene_artifact
    if step == StepKind.TRAJECTORIES:
        return ScenarioCaseRow.trajectories_artifact
    return RunRecordRow.artifacts[STATE_LOG_ROLE].astext


def dropped_at_step(step: StepKind):
    """The case dropped out at the step's own stage, so the step's output is not usable."""
    return and_(ScenarioCaseRow.state == CaseState.DROPPED, ScenarioCaseRow.stage == FIRST_STAGE_OF_STEP[step])


def step_outputs_query(columns, campaign_id: str, step: StepKind, states: Optional[Collection[CaseState]] = None, class_id: Optional[str] = None):
    """The rows of a step's outputs with the given columns: the campaign's cases that reached the step or have its output,
    joined with their run records (simulation), the output's artifact record and the step's verdict (all outer joins).
    """
    output_hash = output_hash_of(step)
    query = select(*columns).select_from(ScenarioCaseRow)
    if step == StepKind.SIMULATION:
        query = query.outerjoin(RunRecordRow, RunRecordRow.case_id == ScenarioCaseRow.id)
        verdict_run_index, has_output = RunRecordRow.run_index, RunRecordRow.id.is_not(None)
    else:
        verdict_run_index, has_output = 0, output_hash.is_not(None)
    query = query.outerjoin(ArtifactRow, ArtifactRow.hash == output_hash).outerjoin(
        VerdictRow, and_(VerdictRow.case_id == ScenarioCaseRow.id, VerdictRow.step == step, VerdictRow.run_index == verdict_run_index)
    )
    query = query.where(ScenarioCaseRow.campaign_id == campaign_id, or_(ScenarioCaseRow.stage.in_(stages_from(FIRST_STAGE_OF_STEP[step])), has_output))
    if class_id is not None:
        query = query.where(ScenarioCaseRow.class_id == class_id)
    if states is not None:
        query = query.where(ScenarioCaseRow.state.in_(list(states)))
    return query


class UnknownClass(LookupError):
    pass


class UnknownCase(LookupError):
    pass


class ClassStateConflict(ValueError):
    pass


class CaseConflict(ValueError):
    """The case changed since it was read, or is not in the expected stage or state."""

    def __init__(self, message: str, current: Optional[CaseRecord]):
        super().__init__(message)
        self.current = current


class _Unset:
    def __repr__(self) -> str:
        return "UNSET"


UNSET: Any = _Unset()  # leaves a field of move_case as it is


def _check_move(row: ScenarioCaseRow, expected_version: int, expected_stage: Optional[PipelineStage], expected_state: Optional[CaseState], new_state: CaseState) -> None:
    problem = None
    if row.version != expected_version:
        problem = f"is at version {row.version}, not {expected_version}"
    elif expected_stage is not None and row.stage != expected_stage:
        problem = f"is at stage {row.stage.value}, not {expected_stage.value}"
    elif expected_state is not None and row.state != expected_state:
        problem = f"is {row.state.value}, not {expected_state.value}"
    elif row.state.is_final and new_state != row.state:
        problem = f"is {row.state.value} and stays so"
    if problem is not None:
        raise CaseConflict(f"case {row.id} {problem}", CaseRecord.from_row(row))


class CaseStore:
    def __init__(self, session_factory: sessionmaker[Session], clock: Clock = utc_now):
        self._sessions = session_factory
        self._clock = clock

    # Classes

    def get_class(self, campaign_id: str, class_id: str, *, lock: bool = False, session: Optional[Session] = None) -> Optional[ClassRecord]:
        with session_scope(self._sessions, session) as scope:
            row = self._load_class(scope, campaign_id, class_id, lock)
            return None if row is None else ClassRecord.from_row(row)

    def list_classes(self, campaign_id: str, states: Optional[Collection[CampaignClassState]] = None, *, session: Optional[Session] = None) -> List[ClassRecord]:
        """The campaign's classes ordered by class id, optionally only those in the given states."""
        with session_scope(self._sessions, session) as scope:
            query = select(CampaignClassRow).where(CampaignClassRow.campaign_id == campaign_id).order_by(CampaignClassRow.class_id)
            if states is not None:
                query = query.where(CampaignClassRow.state.in_(list(states)))
            return [ClassRecord.from_row(row) for row in scope.execute(query.execution_options(populate_existing=True)).scalars()]

    def set_class_state(
        self,
        campaign_id: str,
        class_id: str,
        state: CampaignClassState,
        reason: Optional[str] = None,
        expected: Optional[CampaignClassState] = None,
        *,
        session: Optional[Session] = None,
    ) -> ClassRecord:
        """Closes a class as complete or abandoned (or sets the state it has). A closed class stays closed."""
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            row = self._require_class(scope, campaign_id, class_id, lock=True)
            if expected is not None and row.state != expected:
                raise ClassStateConflict(f"FEC {class_id} of campaign {campaign_id} is {row.state.value}, not {expected.value}")
            if row.state == state:
                return ClassRecord.from_row(row)
            if row.state != CampaignClassState.OPEN:
                raise ClassStateConflict(f"FEC {class_id} of campaign {campaign_id} is {row.state.value} and stays so")
            row.state = state
            row.state_reason = reason
            row.updated_at = now
            row.finished_at = now
            scope.flush()
            return ClassRecord.from_row(row)

    def class_counts_from_cases(self, campaign_id: str, *, session: Optional[Session] = None) -> Dict[str, ClassCounts]:
        """Counts of every class of the campaign, counted from its cases instead of read from the class."""
        with session_scope(self._sessions, session) as scope:
            counts: Dict[str, Dict[str, int]] = {class_id: {} for class_id in scope.execute(select(CampaignClassRow.class_id).where(CampaignClassRow.campaign_id == campaign_id)).scalars()}
            query = select(ScenarioCaseRow.class_id, ScenarioCaseRow.state, func.count()).where(ScenarioCaseRow.campaign_id == campaign_id).group_by(ScenarioCaseRow.class_id, ScenarioCaseRow.state)
            for class_id, state, count in scope.execute(query):
                column = COUNT_COLUMN_OF_STATE.get(state)
                if column is not None:
                    counts[class_id][column] = counts[class_id].get(column, 0) + count
            return {
                class_id: ClassCounts(complete=values.get("complete_count", 0), dropped=values.get("dropped_count", 0), in_flight=values.get("in_flight_count", 0))
                for class_id, values in sorted(counts.items())
            }

    def recount_classes(self, campaign_id: str, *, session: Optional[Session] = None) -> List[ClassRecord]:
        """Sets the stored counts of every class from its cases; returns the classes whose counts were off."""
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            counted = self.class_counts_from_cases(campaign_id, session=scope)
            corrected = []
            rows = scope.execute(select(CampaignClassRow).where(CampaignClassRow.campaign_id == campaign_id).order_by(CampaignClassRow.class_id).with_for_update(key_share=True)).scalars()
            for row in rows:
                counts = counted.get(row.class_id, ClassCounts())
                if (row.complete_count, row.dropped_count, row.in_flight_count) != (counts.complete, counts.dropped, counts.in_flight):
                    row.complete_count, row.dropped_count, row.in_flight_count = counts.complete, counts.dropped, counts.in_flight
                    row.updated_at = now
                    corrected.append(row)
            scope.flush()
            return [ClassRecord.from_row(row) for row in corrected]

    # Cases

    def create_cases(self, campaign_id: str, cases: Sequence[NewCase], *, session: Optional[Session] = None) -> List[CaseRecord]:
        """Creates active cases in open classes of the campaign; their classes count them in flight.

        Raises UnknownClass for a class the campaign does not have, ClassStateConflict for a
        closed one; an index taken already violates the unique constraint.
        """
        for case in cases:
            if case.input_artifact is not None:
                require_sha256_hex(case.input_artifact)
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            for class_id in sorted({case.class_id for case in cases}):
                row = self._require_class(scope, campaign_id, class_id, lock=True)
                if row.state != CampaignClassState.OPEN:
                    raise ClassStateConflict(f"FEC {class_id} of campaign {campaign_id} is {row.state.value}; it takes no new cases")
            rows = [
                ScenarioCaseRow(
                    campaign_id=campaign_id,
                    class_id=case.class_id,
                    case_index=case.case_index,
                    seed=case.seed,
                    config_version=case.config_version,
                    stage=case.stage,
                    state=CaseState.ACTIVE,
                    version=1,
                    input_artifact=case.input_artifact,
                    input_source=None if case.input_source is None else dict(case.input_source),
                    progress={},
                    created_at=now,
                    updated_at=now,
                )
                for case in cases
            ]
            scope.add_all(rows)
            scope.flush()
            for row in rows:
                self._count(scope, campaign_id, row.class_id, CaseState.ACTIVE, 1, now)
            return [CaseRecord.from_row(row) for row in rows]

    def create_case(self, campaign_id: str, case: NewCase, *, session: Optional[Session] = None) -> CaseRecord:
        (record,) = self.create_cases(campaign_id, [case], session=session)
        return record

    def get_case(self, case_id: int, *, session: Optional[Session] = None) -> Optional[CaseRecord]:
        with session_scope(self._sessions, session) as scope:
            row = scope.get(ScenarioCaseRow, case_id, populate_existing=True)
            return None if row is None else CaseRecord.from_row(row)

    def find_case(self, campaign_id: str, class_id: str, case_index: int, *, session: Optional[Session] = None) -> Optional[CaseRecord]:
        with session_scope(self._sessions, session) as scope:
            query = select(ScenarioCaseRow).where(ScenarioCaseRow.campaign_id == campaign_id, ScenarioCaseRow.class_id == class_id, ScenarioCaseRow.case_index == case_index)
            row = scope.execute(query).scalar_one_or_none()
            return None if row is None else CaseRecord.from_row(row)

    def list_cases(
        self,
        campaign_id: str,
        class_id: Optional[str] = None,
        states: Optional[Collection[CaseState]] = None,
        stages: Optional[Collection[PipelineStage]] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        *,
        session: Optional[Session] = None,
    ) -> List[CaseRecord]:
        """Cases of the campaign ordered by class and index, optionally of one class, in some states or stages."""
        with session_scope(self._sessions, session) as scope:
            query = self._case_filtered(select(ScenarioCaseRow), campaign_id, class_id, states, stages)
            query = query.order_by(ScenarioCaseRow.class_id, ScenarioCaseRow.case_index).offset(offset).limit(limit).execution_options(populate_existing=True)
            return [CaseRecord.from_row(row) for row in scope.execute(query).scalars()]

    def count_cases(
        self,
        campaign_id: str,
        states: Optional[Collection[CaseState]] = None,
        *,
        class_id: Optional[str] = None,
        stages: Optional[Collection[PipelineStage]] = None,
        session: Optional[Session] = None,
    ) -> int:
        """How many cases list_cases would return for the same filters without a page."""
        with session_scope(self._sessions, session) as scope:
            return scope.execute(self._case_filtered(select(func.count()).select_from(ScenarioCaseRow), campaign_id, class_id, states, stages)).scalar_one()

    def next_case_index(self, campaign_id: str, class_id: str, *, session: Optional[Session] = None) -> int:
        """One past the highest case index of the class, 0 for a class without cases."""
        with session_scope(self._sessions, session) as scope:
            query = select(func.max(ScenarioCaseRow.case_index)).where(ScenarioCaseRow.campaign_id == campaign_id, ScenarioCaseRow.class_id == class_id)
            highest = scope.execute(query).scalar_one()
            return 0 if highest is None else highest + 1

    def move_case(
        self,
        case_id: int,
        expected_version: int,
        *,
        stage: Optional[PipelineStage] = None,
        state: Optional[CaseState] = None,
        expected_stage: Optional[PipelineStage] = None,
        expected_state: Optional[CaseState] = None,
        scene_artifact: Any = UNSET,
        trajectories_artifact: Any = UNSET,
        trajectories_complete: Any = UNSET,
        progress: Any = UNSET,
        reason: Any = UNSET,
        session: Optional[Session] = None,
    ) -> CaseRecord:
        """Moves the case to a stage and state and sets the given fields, if it is still at expected_version.

        stage and state default to the case's own; fields left UNSET keep their value.
        Raises UnknownCase, or CaseConflict when the version, expected_stage or
        expected_state do not match, or when a final case would change its state.
        """
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            row = scope.execute(select(ScenarioCaseRow).where(ScenarioCaseRow.id == case_id).with_for_update(key_share=True).execution_options(populate_existing=True)).scalar_one_or_none()
            if row is None:
                raise UnknownCase(case_id)
            new_state = row.state if state is None else state
            _check_move(row, expected_version, expected_stage, expected_state, new_state)
            if stage is not None:
                row.stage = stage
            for name, value in (("scene_artifact", scene_artifact), ("trajectories_artifact", trajectories_artifact)):
                if value is not UNSET:
                    setattr(row, name, None if value is None else require_sha256_hex(value))
            for name, value in (("trajectories_complete", trajectories_complete), ("progress", progress), ("reason", reason)):
                if value is not UNSET:
                    setattr(row, name, dict(value) if name == "progress" else value)
            if new_state != row.state:
                self._count(scope, row.campaign_id, row.class_id, row.state, -1, now)
                self._count(scope, row.campaign_id, row.class_id, new_state, 1, now)
                row.state = new_state
                if new_state.is_final:
                    row.finished_at = now
            row.version += 1
            row.updated_at = now
            scope.flush()
            return CaseRecord.from_row(row)

    # Outputs

    def list_outputs(
        self,
        campaign_id: str,
        step: StepKind,
        states: Optional[Collection[CaseState]] = None,
        class_id: Optional[str] = None,
        limit: Optional[int] = 100,
        offset: int = 0,
        *,
        session: Optional[Session] = None,
    ) -> List[OutputRecord]:
        """The outputs of one step ordered by class and case (and run and repeat): a row per case for the scene and
        trajectory steps, a row per run record for the simulation step (one without a run for a case that has none yet).
        Optionally of cases in some states or of one class.
        """
        with session_scope(self._sessions, session) as scope:
            columns = [
                ScenarioCaseRow,
                output_hash_of(step).label("output_hash"),
                ArtifactRow.size_bytes.label("size_bytes"),
                ArtifactRow.kind.label("artifact_kind"),
                ArtifactRow.media_type.label("media_type"),
                VerdictRow.state.label("verdict_state"),
                VerdictRow.failed_rules.label("failed_rules"),
            ]
            order = [ScenarioCaseRow.class_id, ScenarioCaseRow.case_index]
            if step == StepKind.SIMULATION:
                columns += [
                    RunRecordRow.id.label("run_record_id"),
                    RunRecordRow.run_index.label("run_index"),
                    RunRecordRow.repeat_index.label("repeat_index"),
                    RunRecordRow.trajectories_complete.label("run_trajectories_complete"),
                ]
                order += [RunRecordRow.run_index, RunRecordRow.repeat_index]
            query = step_outputs_query(columns, campaign_id, step, states, class_id).order_by(*order).offset(offset).limit(limit)
            return [self._output(step, values) for values in scope.execute(query.execution_options(populate_existing=True))]

    def count_outputs(self, campaign_id: str, step: StepKind, states: Optional[Collection[CaseState]] = None, class_id: Optional[str] = None, *, session: Optional[Session] = None) -> int:
        """How many rows list_outputs would return for the same filters without a page."""
        with session_scope(self._sessions, session) as scope:
            return scope.execute(step_outputs_query([func.count()], campaign_id, step, states, class_id)).scalar_one()

    # Helpers

    @staticmethod
    def _output(step: StepKind, values) -> OutputRecord:
        case: ScenarioCaseRow = values[0]
        output_hash = values.output_hash
        artifact = None
        if output_hash is not None:
            pointer = TRAJECTORIES_POINTER if step == StepKind.TRAJECTORIES else None
            artifact = OutputArtifact(sha256=output_hash, size_bytes=values.size_bytes, kind=values.artifact_kind, media_type=values.media_type, pointer=pointer)
        run_record_id = run_index = repeat_index = None
        if step == StepKind.SIMULATION:
            run_record_id, run_index, repeat_index = values.run_record_id, values.run_index, values.repeat_index
            valid, complete = output_hash is not None, values.run_trajectories_complete
        else:
            dropped_here = case.state == CaseState.DROPPED and case.stage == FIRST_STAGE_OF_STEP[step]
            valid = output_hash is not None and not dropped_here
            complete = case.trajectories_complete if step == StepKind.TRAJECTORIES else None
        return OutputRecord(
            step=step,
            case_id=case.id,
            case_index=case.case_index,
            class_id=case.class_id,
            state=case.state,
            reason=case.reason,
            artifact=artifact,
            valid=valid,
            complete=complete,
            run_index=run_index,
            repeat_index=repeat_index,
            run_record_id=run_record_id,
            verdict_state=values.verdict_state,
            failed_rules=tuple(values.failed_rules or ()),
            input_source=None if case.input_source is None else dict(case.input_source),
        )

    @staticmethod
    def _case_filtered(query, campaign_id: str, class_id: Optional[str], states: Optional[Collection[CaseState]], stages: Optional[Collection[PipelineStage]]):
        query = query.where(ScenarioCaseRow.campaign_id == campaign_id)
        if class_id is not None:
            query = query.where(ScenarioCaseRow.class_id == class_id)
        if states is not None:
            query = query.where(ScenarioCaseRow.state.in_(list(states)))
        if stages is not None:
            query = query.where(ScenarioCaseRow.stage.in_(list(stages)))
        return query

    @staticmethod
    def _count(session: Session, campaign_id: str, class_id: str, state: CaseState, delta: int, now) -> None:
        column = COUNT_COLUMN_OF_STATE.get(state)
        if column is None:
            return
        counter = getattr(CampaignClassRow, column)
        session.execute(
            update(CampaignClassRow)
            .where(CampaignClassRow.campaign_id == campaign_id, CampaignClassRow.class_id == class_id)
            .values({column: counter + delta, "updated_at": now})
            .execution_options(synchronize_session=False)
        )

    @staticmethod
    def _load_class(session: Session, campaign_id: str, class_id: str, lock: bool = False) -> Optional[CampaignClassRow]:
        query = select(CampaignClassRow).where(CampaignClassRow.campaign_id == campaign_id, CampaignClassRow.class_id == class_id).execution_options(populate_existing=True)
        if lock:
            query = query.with_for_update(key_share=True)
        return session.execute(query).scalar_one_or_none()

    def _require_class(self, session: Session, campaign_id: str, class_id: str, lock: bool = False) -> CampaignClassRow:
        row = self._load_class(session, campaign_id, class_id, lock)
        if row is None:
            raise UnknownClass(f"campaign {campaign_id} has no FEC {class_id}")
        return row
