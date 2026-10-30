"""Run records and verdicts of the cases, the coverage summary per class and the findings per step.

Writes are idempotent per key, so the engine may process an event twice: a second run
record for the same case, run and repeat, or a second verdict for the same case, step and
run, returns the stored one unchanged. The campaign and class of a result are copied from
its case, for the API's queries. A verdict judges one step: the scene and the trajectories
once per case (run index 0), the simulation once per run.

Every method takes an optional session (see store_session).
"""

import statistics
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple, Type, get_args

from sqlalchemy import and_, case, column, distinct, extract, func, select, true
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.orm import Session, sessionmaker

from scenegems_tool.persistence.clock import Clock, utc_now
from scenegems_tool.persistence.schema import (
    CampaignClassRow,
    JobRow,
    MonitorImplementation,
    PipelineJobRow,
    RunRecordRow,
    ScenarioCaseRow,
    StepKind,
    VerdictRow,
    VerdictState,
)
from scenegems_tool.persistence.schema.artifact_tables import require_sha256_hex
from scenegems_tool.persistence.stores.case_store import FIRST_STAGE_OF_STEP, UnknownCase, dropped_at_step, output_hash_of, step_outputs_query
from scenegems_tool.persistence.stores.result_records import (
    ClassCoverage,
    ClassFindings,
    NewRunRecord,
    NewVerdict,
    RuleFindings,
    RunRecord,
    StepFindings,
    VerdictRecord,
)
from scenegems_tool.persistence.stores.store_session import session_scope

FAILED_RULE_SEPARATOR = ": "  # a verdict's failed rule reads "<relation>: <rule>"
VerdictSort = Literal["fec_id", "state", "first_failure_time_s", "step", "run_index", "case_index", "created_at"]
VERDICT_SORTS: Tuple[str, ...] = get_args(VerdictSort)  # the whitelist of list_verdicts' sort


def check_verdict(verdict: NewVerdict) -> None:
    """The rules the table's constraints hold, with a readable message before the database refuses."""
    if (verdict.state == VerdictState.UNMONITORED) != (verdict.monitor == MonitorImplementation.EMPTY):
        raise ValueError(f"a verdict is unmonitored exactly when its monitor is empty, got {verdict.state.value} from {verdict.monitor.value}")
    if verdict.early_stop_time_s is not None and verdict.monitor != MonitorImplementation.LIVE:
        raise ValueError("only the live monitor stops a run early")
    if verdict.first_failure_time_s is not None and verdict.state != VerdictState.FAILED:
        raise ValueError("a first failure time belongs to a failed verdict")
    if verdict.state == VerdictState.PASSED and verdict.failed_rules:
        raise ValueError(f"a passed verdict has no failed rules, got {list(verdict.failed_rules)}")
    if verdict.step != StepKind.SIMULATION:
        if verdict.run_index != 0:
            raise ValueError(f"the {verdict.step.value} step has one verdict per case, at run index 0, not {verdict.run_index}")
        if verdict.monitor == MonitorImplementation.LIVE:
            raise ValueError("the live monitor judges simulated runs only")


def rule_findings(failed_verdicts: Sequence[Tuple[Sequence[str], Mapping[str, Any]]]) -> Tuple[RuleFindings, ...]:
    """Per rule: in how many failed verdicts it failed, and the min and median of its first failure time over them.

    A verdict's failed rules read "<relation>: <rule>"; its rule outcomes map relation to
    rule to the first time of each outcome. A rule failing for several relations of one run
    counts once, with its earliest failure. Rules sort by count (most first), then name.
    """
    counts: Dict[str, int] = {}
    times: Dict[str, List[float]] = {}
    for failed_rules, rule_outcomes in failed_verdicts:
        earliest: Dict[str, Optional[float]] = {}
        for entry in failed_rules:
            relation, separator, rule = str(entry).partition(FAILED_RULE_SEPARATOR)
            if not separator:
                relation, rule = "", relation
            outcome = ((rule_outcomes or {}).get(relation) or {}).get(rule) or {}
            failed_at = outcome.get("failed") if isinstance(outcome, Mapping) else None
            known = earliest.get(rule)
            if rule not in earliest or (failed_at is not None and (known is None or float(failed_at) < known)):
                earliest[rule] = None if failed_at is None else float(failed_at)
        for rule, failed_at in earliest.items():
            counts[rule] = counts.get(rule, 0) + 1
            if failed_at is not None:
                times.setdefault(rule, []).append(failed_at)
    return tuple(
        RuleFindings(
            rule=rule, count=count, first_failure_time_min_s=min(times[rule]) if rule in times else None, first_failure_time_median_s=statistics.median(times[rule]) if rule in times else None
        )
        for rule, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )


class ResultStore:
    def __init__(self, session_factory: sessionmaker[Session], clock: Clock = utc_now):
        self._sessions = session_factory
        self._clock = clock

    # Run records

    def add_run_record(self, record: NewRunRecord, *, session: Optional[Session] = None) -> RunRecord:
        for artifact_hash in record.artifacts.values():
            require_sha256_hex(artifact_hash)
        values = dict(record.__dict__)
        with session_scope(self._sessions, session) as scope:
            campaign_id, class_id = self._case_of(scope, record.case_id)
            row_id = self._insert_once(scope, RunRecordRow, ["case_id", "run_index", "repeat_index"], dict(values, campaign_id=campaign_id, class_id=class_id, created_at=self._clock()))
            row = scope.get(RunRecordRow, row_id) if row_id is not None else self._run_record_row(scope, record.case_id, record.run_index, record.repeat_index)
            return RunRecord.from_row(row, self._case_index(scope, row.case_id))

    def get_run_record(self, run_record_id: int, *, session: Optional[Session] = None) -> Optional[RunRecord]:
        with session_scope(self._sessions, session) as scope:
            row = scope.get(RunRecordRow, run_record_id)
            return None if row is None else RunRecord.from_row(row, self._case_index(scope, row.case_id))

    def list_run_records(
        self,
        campaign_id: str,
        class_id: Optional[str] = None,
        case_id: Optional[int] = None,
        run_index: Optional[int] = None,
        limit: Optional[int] = 100,
        offset: int = 0,
        *,
        session: Optional[Session] = None,
    ) -> List[RunRecord]:
        """Run records of the campaign ordered by class, case, run and repeat, each with its case index."""
        with session_scope(self._sessions, session) as scope:
            query = self._filtered(
                select(RunRecordRow, ScenarioCaseRow.case_index).join(ScenarioCaseRow, ScenarioCaseRow.id == RunRecordRow.case_id), RunRecordRow, campaign_id, class_id, case_id, run_index
            )
            query = query.order_by(RunRecordRow.class_id, ScenarioCaseRow.case_index, RunRecordRow.run_index, RunRecordRow.repeat_index).offset(offset).limit(limit)
            return [RunRecord.from_row(row, case_index) for row, case_index in scope.execute(query)]

    def count_run_records(self, campaign_id: str, class_id: Optional[str] = None, case_id: Optional[int] = None, run_index: Optional[int] = None, *, session: Optional[Session] = None) -> int:
        """How many run records list_run_records would return for the same filters without a page."""
        with session_scope(self._sessions, session) as scope:
            return scope.execute(self._filtered(select(func.count()).select_from(RunRecordRow), RunRecordRow, campaign_id, class_id, case_id, run_index)).scalar_one()

    # Verdicts

    def add_verdict(self, verdict: NewVerdict, *, session: Optional[Session] = None) -> VerdictRecord:
        check_verdict(verdict)
        values = dict(verdict.__dict__, failed_rules=list(verdict.failed_rules))
        with session_scope(self._sessions, session) as scope:
            campaign_id, class_id = self._case_of(scope, verdict.case_id)
            row_id = self._insert_once(scope, VerdictRow, ["case_id", "step", "run_index"], dict(values, campaign_id=campaign_id, class_id=class_id, created_at=self._clock()))
            if row_id is None:
                query = select(VerdictRow).where(VerdictRow.case_id == verdict.case_id, VerdictRow.step == verdict.step, VerdictRow.run_index == verdict.run_index)
                row = scope.execute(query).scalar_one()
            else:
                row = scope.get(VerdictRow, row_id)
            return VerdictRecord.from_row(row, self._case_index(scope, row.case_id))

    def list_verdicts(
        self,
        campaign_id: str,
        class_id: Optional[str] = None,
        case_id: Optional[int] = None,
        state: Optional[VerdictState] = None,
        run_index: Optional[int] = None,
        sensitive: Optional[bool] = None,
        limit: Optional[int] = 100,
        offset: int = 0,
        *,
        step: Optional[StepKind] = None,
        sort: VerdictSort = "fec_id",
        descending: bool = False,
        session: Optional[Session] = None,
    ) -> List[VerdictRecord]:
        """Verdicts of the campaign, each with its case index; filter on class, case, state, run, sensitivity, step.

        The order is sort (fec_id: class, case, step and run, the default; or one of
        VERDICT_SORTS), ascending or descending. A sort other than fec_id breaks ties by the
        default order and the verdict id, and nulls (first_failure_time_s) come last in
        either direction, so offset paging stays stable.
        """
        if sort not in VERDICT_SORTS:
            raise ValueError(f"cannot sort verdicts by {sort}; use {', '.join(VERDICT_SORTS)}")
        with session_scope(self._sessions, session) as scope:
            query = select(VerdictRow, ScenarioCaseRow.case_index).join(ScenarioCaseRow, ScenarioCaseRow.id == VerdictRow.case_id)
            query = self._verdict_filtered(query, campaign_id, class_id, case_id, state, run_index, sensitive, step)
            query = query.order_by(*self._verdict_order(sort, descending)).offset(offset).limit(limit)
            return [VerdictRecord.from_row(row, case_index) for row, case_index in scope.execute(query)]

    @staticmethod
    def _verdict_order(sort: str, descending: bool) -> list:
        step_order = case({StepKind.SCENE.value: 0, StepKind.TRAJECTORIES.value: 1}, value=VerdictRow.step, else_=2)
        default_order = [VerdictRow.class_id, ScenarioCaseRow.case_index, step_order, VerdictRow.run_index]
        keys = {
            "state": VerdictRow.state,
            "first_failure_time_s": VerdictRow.first_failure_time_s,
            "step": step_order,
            "run_index": VerdictRow.run_index,
            "case_index": ScenarioCaseRow.case_index,
            "created_at": VerdictRow.created_at,
        }
        if sort == "fec_id":
            ordered = [key.desc() if descending else key.asc() for key in default_order]
            return [*ordered, VerdictRow.id.desc() if descending else VerdictRow.id.asc()]
        key = keys[sort]
        return [key.desc().nulls_last() if descending else key.asc().nulls_last(), *default_order, VerdictRow.id]

    def count_verdicts(
        self,
        campaign_id: str,
        state: Optional[VerdictState] = None,
        *,
        class_id: Optional[str] = None,
        case_id: Optional[int] = None,
        run_index: Optional[int] = None,
        sensitive: Optional[bool] = None,
        step: Optional[StepKind] = None,
        session: Optional[Session] = None,
    ) -> int:
        """How many verdicts list_verdicts would return for the same filters without a page."""
        with session_scope(self._sessions, session) as scope:
            query = self._verdict_filtered(select(func.count()).select_from(VerdictRow), campaign_id, class_id, case_id, state, run_index, sensitive, step)
            return scope.execute(query).scalar_one()

    # Coverage

    def coverage(self, campaign_id: str, step: Optional[StepKind] = StepKind.SIMULATION, *, session: Optional[Session] = None) -> List[ClassCoverage]:
        """Per class of the campaign, ordered by class id: state, quota, case counts and verdicts per run and state.

        The verdicts are those of one step, the simulation's by default (None counts every step's).
        """
        with session_scope(self._sessions, session) as scope:
            classes = (
                scope.execute(select(CampaignClassRow).where(CampaignClassRow.campaign_id == campaign_id).order_by(CampaignClassRow.class_id).execution_options(populate_existing=True)).scalars().all()
            )
            verdicts = {row.class_id: {} for row in classes}
            query = (
                select(VerdictRow.class_id, VerdictRow.run_index, VerdictRow.state, func.count())
                .where(VerdictRow.campaign_id == campaign_id)
                .group_by(VerdictRow.class_id, VerdictRow.run_index, VerdictRow.state)
            )
            if step is not None:
                query = query.where(VerdictRow.step == step)
            for class_id, run_index, state, count in scope.execute(query):
                verdicts[class_id].setdefault(run_index, {})[state] = count
            return [
                ClassCoverage(
                    class_id=row.class_id,
                    state=row.state,
                    quota=row.quota,
                    failure_budget=row.failure_budget,
                    complete=row.complete_count,
                    dropped=row.dropped_count,
                    in_flight=row.in_flight_count,
                    verdicts={run_index: dict(states) for run_index, states in sorted(verdicts[row.class_id].items())},
                )
                for row in classes
            ]

    # Findings

    def findings(self, campaign_id: str, step: StepKind, monitored: Optional[bool] = None, *, session: Optional[Session] = None) -> StepFindings:
        """The summary of one step: its cases by state, outputs, verdicts, failed rules, classes and job durations.

        The cases are those that reached the step (as in CaseStore.list_outputs). monitored
        comes from the campaign's config; when None, a step counts as monitored once it has a
        verdict of a monitor other than empty. An unmonitored step gets no verdicts and no
        failed rules (statistics only).
        """
        with session_scope(self._sessions, session) as scope:
            if monitored is None:
                query = select(func.count()).select_from(VerdictRow).where(VerdictRow.campaign_id == campaign_id, VerdictRow.step == step, VerdictRow.monitor != MonitorImplementation.EMPTY)
                monitored = scope.execute(query).scalar_one() > 0
            cases = {
                state: count for state, count in scope.execute(step_outputs_query([ScenarioCaseRow.state, func.count(distinct(ScenarioCaseRow.id))], campaign_id, step).group_by(ScenarioCaseRow.state))
            }
            count, valid, complete = scope.execute(step_outputs_query(self._output_counts(step), campaign_id, step)).one()
            verdicts: Dict[VerdictState, int] = {}
            failed_rules: Tuple[RuleFindings, ...] = ()
            encounter_types: Dict[str, int] = {}
            if monitored:
                query = select(VerdictRow.state, func.count()).where(VerdictRow.campaign_id == campaign_id, VerdictRow.step == step).group_by(VerdictRow.state)
                verdicts = {state: number for state, number in scope.execute(query)}
                query = select(VerdictRow.failed_rules, VerdictRow.rule_outcomes).where(VerdictRow.campaign_id == campaign_id, VerdictRow.step == step, VerdictRow.state == VerdictState.FAILED)
                failed_rules = rule_findings([(rules, outcomes) for rules, outcomes in scope.execute(query)])
                encounter_types = self._encounter_types(scope, campaign_id, step)
            median, p90 = self._durations(scope, campaign_id, step)
            return StepFindings(
                step=step,
                monitored=monitored,
                cases=cases,
                outputs_count=count or 0,
                outputs_valid=valid or 0,
                outputs_complete=complete or 0,
                verdicts=verdicts,
                failed_rules=failed_rules,
                encounter_types=encounter_types,
                classes=self._class_findings(scope, campaign_id, step, monitored),
                duration_median_s=median,
                duration_p90_s=p90,
            )

    @staticmethod
    def _encounter_types(session: Session, campaign_id: str, step: StepKind) -> Dict[str, int]:
        """The step's vessel pairs by the first encounter type of each (OTHER included), most first; verdicts stored without encounters add none."""
        pair = func.jsonb_each(VerdictRow.encounters).table_valued(column("key"), column("value", JSONB))
        first_type = pair.c.value[0].astext
        query = (
            select(first_type, func.count())
            .select_from(VerdictRow)
            .join(pair, true())
            .where(VerdictRow.campaign_id == campaign_id, VerdictRow.step == step, VerdictRow.encounters.is_not(None))
            .group_by(first_type)
        )
        counts = {name: count for name, count in session.execute(query) if name is not None}
        return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))

    @staticmethod
    def _output_counts(step: StepKind) -> list:
        """count, valid and complete over a step's output rows; a valid scene counts as complete."""
        output_hash = output_hash_of(step)
        if step == StepKind.SIMULATION:
            valid = output_hash.is_not(None)
            complete = and_(valid, RunRecordRow.trajectories_complete.is_(True))
        else:
            valid = and_(output_hash.is_not(None), ~dropped_at_step(step))
            complete = valid if step == StepKind.SCENE else and_(valid, ScenarioCaseRow.trajectories_complete.is_(True))
        return [func.count(output_hash), func.sum(case((valid, 1), else_=0)), func.sum(case((complete, 1), else_=0))]

    @staticmethod
    def _class_findings(session: Session, campaign_id: str, step: StepKind, monitored: bool) -> Tuple[ClassFindings, ...]:
        class_ids = session.execute(select(CampaignClassRow.class_id).where(CampaignClassRow.campaign_id == campaign_id).order_by(CampaignClassRow.class_id)).scalars().all()
        query = step_outputs_query([ScenarioCaseRow.class_id, func.count(distinct(ScenarioCaseRow.id))], campaign_id, step).group_by(ScenarioCaseRow.class_id)
        cases = {class_id: count for class_id, count in session.execute(query)}
        verdicts: Dict[str, Dict[VerdictState, int]] = {}
        if monitored:
            query = select(VerdictRow.class_id, VerdictRow.state, func.count()).where(VerdictRow.campaign_id == campaign_id, VerdictRow.step == step).group_by(VerdictRow.class_id, VerdictRow.state)
            for class_id, state, count in session.execute(query):
                verdicts.setdefault(class_id, {})[state] = count
        return tuple(
            ClassFindings(
                class_id=class_id,
                cases=cases.get(class_id, 0),
                passed=verdicts.get(class_id, {}).get(VerdictState.PASSED, 0),
                failed=verdicts.get(class_id, {}).get(VerdictState.FAILED, 0),
            )
            for class_id in class_ids
        )

    @staticmethod
    def _durations(session: Session, campaign_id: str, step: StepKind) -> Tuple[Optional[float], Optional[float]]:
        """Median and 90th percentile of the running time (first accept to end) of the step's finished jobs."""
        running_s = extract("epoch", JobRow.finished_at - JobRow.started_at)
        query = (
            select(func.percentile_cont(0.5).within_group(running_s), func.percentile_cont(0.9).within_group(running_s))
            .select_from(PipelineJobRow)
            .join(JobRow, JobRow.id == PipelineJobRow.job_id)
            .where(PipelineJobRow.campaign_id == campaign_id, PipelineJobRow.stage == FIRST_STAGE_OF_STEP[step], JobRow.started_at.is_not(None), JobRow.finished_at.is_not(None))
        )
        median, p90 = session.execute(query).one()
        return (None if median is None else float(median)), (None if p90 is None else float(p90))

    # Helpers

    @staticmethod
    def _case_of(session: Session, case_id: int) -> Tuple[str, str]:
        found = session.execute(select(ScenarioCaseRow.campaign_id, ScenarioCaseRow.class_id).where(ScenarioCaseRow.id == case_id)).first()
        if found is None:
            raise UnknownCase(case_id)
        return found[0], found[1]

    @staticmethod
    def _case_index(session: Session, case_id: int) -> Optional[int]:
        return session.execute(select(ScenarioCaseRow.case_index).where(ScenarioCaseRow.id == case_id)).scalar_one_or_none()

    @classmethod
    def _verdict_filtered(
        cls,
        query,
        campaign_id: str,
        class_id: Optional[str],
        case_id: Optional[int],
        state: Optional[VerdictState],
        run_index: Optional[int],
        sensitive: Optional[bool],
        step: Optional[StepKind] = None,
    ):
        query = cls._filtered(query, VerdictRow, campaign_id, class_id, case_id, run_index)
        if step is not None:
            query = query.where(VerdictRow.step == step)
        if state is not None:
            query = query.where(VerdictRow.state == state)
        if sensitive is not None:
            query = query.where(VerdictRow.sensitive.is_(sensitive))
        return query

    @staticmethod
    def _insert_once(session: Session, table: Type[Any], key: List[str], values: dict) -> Optional[int]:
        statement = insert(table).values(**values).on_conflict_do_nothing(index_elements=[getattr(table, column) for column in key]).returning(table.id)
        return session.execute(statement).scalar_one_or_none()

    @staticmethod
    def _run_record_row(session: Session, case_id: int, run_index: int, repeat_index: int) -> RunRecordRow:
        query = select(RunRecordRow).where(RunRecordRow.case_id == case_id, RunRecordRow.run_index == run_index, RunRecordRow.repeat_index == repeat_index)
        return session.execute(query).scalar_one()

    @staticmethod
    def _filtered(query, table, campaign_id: str, class_id: Optional[str], case_id: Optional[int], run_index: Optional[int]):
        query = query.where(table.campaign_id == campaign_id)
        if class_id is not None:
            query = query.where(table.class_id == class_id)
        if case_id is not None:
            query = query.where(table.case_id == case_id)
        if run_index is not None:
            query = query.where(table.run_index == run_index)
        return query
