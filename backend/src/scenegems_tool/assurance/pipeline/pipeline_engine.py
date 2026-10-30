"""The pipeline engine: runs every unfinished campaign, one tick at a time, as a control plane timer.

Only the engine that holds the engine lock ticks (engine_leadership.py); another engine on the
same database stands by and takes over when the leader's lock connection ends. A tick has two
parts.

1. One transaction (in a worker thread, so the event loop stays free), holding the cursor row:
   - the lock must still be held by this engine's connection, otherwise the tick writes
     nothing and the engine stands by (LeadershipLost);
   - the cursor is read where the database has it, so a tick that failed, whether or not its
     commit went through, is simply followed by the next one;
   - the job events after the cursor are applied to their cases (case_machine), each in a
     savepoint: a case whose event cannot be processed is quarantined instead of blocking the
     cursor;
   - each campaign's actual state converges on its desired state (below), the coverage
     controller completes, cuts and closes classes, and running campaigns start new cases
     under backpressure;
   - intents not linked to a job are collected for submission (an intent of a case that ended
     before its submission is retired);
   - the cursor advances to the batch's position.
2. After the commit, on the event loop: the jobs of ended cases are cancelled through the
   control plane (which tells their nodes), the intents are submitted through
   ControlPlane.submit with their idempotency keys and linked to their jobs, and the jobs of
   a paused campaign are held.

A crash between the two parts loses nothing: intents are resubmitted on the next tick (the
keys make that idempotent), and jobs of ended cases are cancelled at the next start.

After each committed transaction the engine tells on_change, on the event loop, which
campaigns it wrote to (events, states, cases of their classes). The live channel listens and
reads what changed for the campaigns somebody watches; the engine itself queries nothing for it.

Desired and actual states:

    start    actual created, desired running or draining: pin the master's current expected
             fingerprints when the campaign has none, actual running, event started
    pause    hold the campaign's unfinished jobs, start nothing, actual paused; jobs submitted
             while paused are held at once
    resume   release the held jobs, actual running (or draining)
    drain    finish started cases, start none; with nothing in flight, actual paused with the
             reason "drained", so a later resume continues the campaign
    stop     cancel the active cases and every unfinished job, actual stopped once no job of the
             campaign is unfinished; open classes are abandoned
    stalled  a job type the campaign needs, with the components of its stage, has no connected node
             that runs it with the pinned fingerprints (and the campaign's labels) for
             stall_after_s: actual stalled with the
             reason, back to running (or draining) once one appears; a stalled campaign starts
             no new cases
    complete every class complete or abandoned: actual completed

Stop conditions of the config (max cases, max failed verdicts, max duration) set the desired
state to draining, with a note event giving the reason. max_failed_verdicts counts the failed
verdicts of every monitored step (scenes and trajectory sets too, not only runs): the operator
chose to monitor those steps, so their failures are findings like a run's.

At start, and whenever it takes the lock again, the engine appends engine_started to every
unfinished campaign, repairs the class counts from the cases, cancels jobs whose cases ended,
and checks every class on its first tick; intents without a job are resubmitted by that tick.

wake() runs a tick at once instead of after the interval (the create route calls it through
ControlPlane.wake_pipeline, so a new campaign or workbench entry starts without waiting).

Runs from outside the cluster: a live session entry (origin live_session) gets no case from
the engine. record_external_run writes its one case with the recorded run (run record with
source live_session and no job) and the intent of its post-hoc monitor in a transaction that
holds the cursor row like a tick's, and submits the monitor job after the commit; from then
on the case moves like any other. Ticks and recorded runs take turns on the event loop, so
they never share the engine's state at once.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Collection, Dict, FrozenSet, List, Mapping, Optional, Sequence, Set, Tuple

import anyio
from sqlalchemy.orm import Session

from scenegems_tool.assurance.campaign.campaign_inputs import item_class_id
from scenegems_tool.assurance.campaign.class_catalog import ClassCatalog
from scenegems_tool.assurance.pipeline.campaign_context import CampaignContext, CampaignContexts
from scenegems_tool.assurance.pipeline.case_machine import CaseMachine, ExternalRun, RecordedRun, StepOutbox
from scenegems_tool.assurance.pipeline.coverage_controller import Backpressure, decide_class, plan_new_cases
from scenegems_tool.assurance.pipeline.engine_leadership import EngineLeadership, LeadershipLost
from scenegems_tool.assurance.pipeline.payload_builder import required_fingerprints
from scenegems_tool.assurance.pipeline.pipeline_queries import UNFINISHED_JOB_STATES, case_states, delete_intent, job_id_by_key, next_case_indexes, pin_fingerprints, unfinished_jobs_of_final_cases
from scenegems_tool.assurance.pipeline.stage_graph import JobNeed
from scenegems_tool.cluster.fingerprints.comparison import find_mismatches
from scenegems_tool.cluster.protocol.jobs import JobSubmission, JobType
from scenegems_tool.persistence.clock import Clock, utc_now
from scenegems_tool.persistence.schema import (
    CampaignActualState,
    CampaignClassState,
    CampaignDesiredState,
    CampaignEventKind,
    CampaignOrigin,
    CaseState,
    JobEventKind,
    NodeStatus,
    VerdictState,
)
from scenegems_tool.persistence.stores import ENGINE_CURSOR, AssuranceStores, CampaignRecord, JobStore, NodeRecord, PipelineJobEvent, SubmitOutcome

logger = logging.getLogger(__name__)

# Events that may end a job: an expired lease ends it when it was the last attempt
EVENT_KINDS = (JobEventKind.SUCCEEDED, JobEventKind.FAILED, JobEventKind.CANCELLED, JobEventKind.EXPIRED)
DRAINED = "drained"
STOPPED_REASON = "the campaign was stopped"


@dataclass(frozen=True)
class NodeAvailability:
    """A connected node as the stall check sees it."""

    record: NodeRecord
    stale_components: FrozenSet[str] = frozenset()  # its components whose images differ from the release

    def runs(self, job_type: JobType, components: Collection[str], fingerprints: Mapping[str, str], labels: Mapping[str, str], nodes: Collection[str] = ()) -> bool:
        """Whether the node may run a job of the type with these components now; nodes, when not empty, are the node ids the campaign allows."""
        record = self.record
        if record.status != NodeStatus.ONLINE or job_type not in record.slots:
            return False
        if not set(components) <= set(record.components) - self.stale_components:
            return False
        if nodes and record.node_id not in nodes:
            return False
        if any(record.labels.get(key) != value for key, value in labels.items()):
            return False
        return not find_mismatches(record.fingerprints, fingerprints)


@dataclass(frozen=True)
class EngineSettings:
    batch_size: int = 500  # job events per transaction
    stall_after_s: float = 60.0  # how long a needed job type may have no node before the campaign is stalled
    max_new_cases_per_tick: int = 256
    submit_concurrency: int = 8


@dataclass(frozen=True)
class PlannedSubmission:
    campaign_id: str
    case_id: int
    idempotency_key: str
    submission: JobSubmission
    hold: bool  # the campaign is paused: hold the job once it is submitted


@dataclass
class StepPlan:
    outbox: StepOutbox
    submissions: List[PlannedSubmission] = field(default_factory=list)
    wake: bool = False
    events_read: int = 0
    caught_up: bool = True  # the batch was not full
    changed: Set[str] = field(default_factory=set)  # campaigns the transaction wrote to


@dataclass(frozen=True)
class TickReport:
    events_read: int = 0
    events_applied: int = 0
    cases_started: int = 0
    submitted: int = 0
    cancelled: int = 0
    caught_up: bool = True
    stopped: bool = False
    standby: bool = False  # another engine holds the engine lock


class PipelineEngine:
    def __init__(
        self,
        stores: AssuranceStores,
        job_store: JobStore,
        submit: Callable[[JobSubmission], Awaitable[SubmitOutcome]],
        cancel: Callable[[str, str], Awaitable[object]],
        expected: Callable[[], Optional[Dict[str, str]]],
        nodes: Callable[[], Sequence[NodeAvailability]],
        wake: Callable[[], None] = lambda: None,
        clock: Clock = utc_now,
        settings: EngineSettings = EngineSettings(),
        catalog: Optional[ClassCatalog] = None,
        leadership: Optional[EngineLeadership] = None,
        on_change: Optional[Callable[[Set[str]], None]] = None,
    ):
        self.stores = stores
        self.jobs = job_store
        self.settings = settings
        self.contexts = CampaignContexts(stores, catalog)
        self.leadership = leadership or EngineLeadership(stores.session_factory)
        self._submit = submit
        self._cancel = cancel
        self._expected = expected
        self._nodes = nodes
        self._wake = wake
        self._clock = clock
        self._started = False
        self._started_term: Optional[int] = None  # the leadership term this engine last reconciled in
        self._standing_by = False
        self._stopped = False
        self._check_every_class = True
        self._unrunnable_since: Dict[str, datetime] = {}
        self.on_change = on_change  # hears the campaigns each committed transaction wrote to
        self._changed: Set[str] = set()
        self._wakeup = asyncio.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # the loop run() ticks on, for wakes from other threads
        self._turn = asyncio.Lock()  # a tick or a recorded run at a time
        self._recorded_classes: Set[Tuple[str, str]] = set()  # classes of recorded runs for the next tick's coverage controller

    @property
    def started(self) -> bool:
        return self._started

    @property
    def stopped(self) -> bool:
        return self._stopped

    def stop(self) -> None:
        """Stops ticking and gives the engine lock up, so another engine can take over."""
        self._stopped = True
        self.leadership.release()

    # Lifetime

    async def run(self, interval_s: float) -> None:
        """Ticks until stopped or cancelled; a tick that read a full batch, or a wake, is followed at once by the next."""
        self._loop = asyncio.get_running_loop()
        try:
            while not self._stopped:
                report = TickReport()
                try:
                    report = await self.tick()
                except Exception:
                    logger.exception("A pipeline engine tick failed; retrying in %.0f s", interval_s)
                if report.caught_up:
                    await self._sleep(interval_s)
        finally:
            self.leadership.release()

    async def _sleep(self, interval_s: float) -> None:
        try:
            await asyncio.wait_for(self._wakeup.wait(), interval_s)
        except asyncio.TimeoutError:
            pass
        self._wakeup.clear()

    def wake(self) -> None:
        """Runs a tick at once instead of after the interval (a wake during a tick runs another one after it); safe from any thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            self._wakeup.set()
            return
        try:
            on_loop = asyncio.get_running_loop() is loop
        except RuntimeError:
            on_loop = False
        if on_loop:
            self._wakeup.set()
        else:
            loop.call_soon_threadsafe(self._wakeup.set)

    async def start(self) -> bool:
        """Takes the engine lock and reconciles: engine_started per campaign, recounted classes, jobs of ended cases cancelled.

        False, with nothing done, while another engine holds the lock.
        """
        if not await anyio.to_thread.run_sync(self.leadership.acquire):
            return False
        try:
            outbox = await anyio.to_thread.run_sync(self._reconcile)
        except LeadershipLost:
            self._lose_leadership()
            return False
        self._notify(self._take_changes(outbox))
        self._started, self._started_term = True, self.leadership.term
        await self._cancel_jobs(outbox)
        return True

    async def tick(self) -> TickReport:
        async with self._turn:
            return await self._tick()

    async def _tick(self) -> TickReport:
        if self._stopped:
            return TickReport(stopped=True)
        if not await anyio.to_thread.run_sync(self.leadership.acquire):
            return self._stand_by()
        if self._standing_by:
            logger.info("This pipeline engine took the engine lock and leads")
            self._standing_by = False
        if not self._started or self._started_term != self.leadership.term:
            if not await self.start():
                return self._stand_by()
        nodes = list(self._nodes())
        recorded, self._recorded_classes = self._recorded_classes, set()
        try:
            plan = await anyio.to_thread.run_sync(self._step, nodes, recorded)
        except LeadershipLost:
            self._recorded_classes |= recorded
            self._lose_leadership()
            return self._stand_by()
        except BaseException:
            self._recorded_classes |= recorded
            raise
        self._notify(plan.changed)
        cancelled = await self._cancel_jobs(plan.outbox)
        submitted = await self._submit_all(plan.submissions)
        if plan.wake or submitted:
            self._wake()
        return TickReport(
            events_read=plan.events_read,
            events_applied=plan.outbox.events_applied,
            cases_started=plan.outbox.cases_started,
            submitted=submitted,
            cancelled=cancelled,
            caught_up=plan.caught_up,
        )

    def _stand_by(self) -> TickReport:
        if not self._standing_by:
            logger.warning("Another pipeline engine holds the engine lock on this database; this one stands by")
            self._standing_by = True
        return TickReport(standby=True)

    def _lose_leadership(self) -> None:
        logger.warning("The pipeline engine lost the engine lock; it stands by and reconciles when it leads again")
        self.leadership.release()
        self._started = False

    # The transaction of a tick

    def _reconcile(self) -> StepOutbox:
        outbox = StepOutbox()
        self._changed = set()
        with self.stores.transaction() as session:
            position = self.stores.pipeline.read_cursor(lock=True, session=session)
            self.leadership.check(session)
            for campaign in self.stores.campaigns.unfinished_campaigns(session=session):
                corrected = self.stores.cases.recount_classes(campaign.campaign_id, session=session)
                orphaned = unfinished_jobs_of_final_cases(session, campaign.campaign_id)
                intents = self.stores.pipeline.intents_without_job(campaign.campaign_id, session=session)
                outbox.cancel(orphaned, "its case ended before the engine restarted")
                detail = {"cursor": [position.tx_id, position.event_id], "intents": len(intents), "recounted_classes": [record.class_id for record in corrected], "orphaned_jobs": len(orphaned)}
                self._event(session, campaign.campaign_id, CampaignEventKind.ENGINE_STARTED, detail)
                if corrected:
                    logger.warning("Campaign %s: class counts repaired from the cases for %s", campaign.campaign_id, ", ".join(record.class_id for record in corrected))
        self._check_every_class = True
        return outbox

    def _step(self, nodes: Sequence[NodeAvailability], recorded: Collection[Tuple[str, str]] = ()) -> StepPlan:
        now = self._clock()
        plan = StepPlan(StepOutbox())
        plan.outbox.touched_classes.update(recorded)  # the coverage controller decides the classes of runs recorded since the last tick
        self._changed = set()
        with self.stores.transaction() as session:
            # The cursor row is locked and this engine holds the engine lock, so the cursor is where the
            # last committed tick left it, also after a tick whose commit failed (committed or not)
            position = self.stores.pipeline.read_cursor(lock=True, session=session)
            self.leadership.check(session)
            campaigns = self.stores.campaigns.unfinished_campaigns(session=session)
            self.contexts.refresh(campaigns)
            machine = CaseMachine(self.stores, session, self.contexts, plan.outbox)
            batch = self.stores.pipeline.events_after(position, self.settings.batch_size, EVENT_KINDS, session=session)
            for event in batch.events:
                self._apply_event(machine, session, event)
            for campaign in campaigns:
                self._converge(machine, session, campaign, nodes, plan, now)
            self.stores.pipeline.advance_cursor(ENGINE_CURSOR, position, batch.position, session=session)
            plan.submissions = self._pending_submissions(session, plan.outbox)
        self._check_every_class = False
        plan.changed = self._take_changes(plan.outbox)
        plan.events_read = len(batch.events)
        plan.caught_up = len(batch.events) < self.settings.batch_size
        return plan

    def _apply_event(self, machine: CaseMachine, session: Session, event: PipelineJobEvent) -> None:
        saved = machine.outbox.snapshot()
        try:
            with session.begin_nested():
                machine.apply(event)
        except Exception as error:
            logger.exception("Job event %s of case %s could not be processed; the case is quarantined", event.event_id, event.pipeline_job.case_id)
            machine.outbox.restore(saved)
            with session.begin_nested():
                case = self.stores.cases.get_case(event.pipeline_job.case_id, session=session)
                context = self.contexts.get(event.pipeline_job.campaign_id, session, None if case is None else case.config_version)
                if case is not None and context is not None and not case.state.is_final:
                    machine.end(context, case, CaseState.FAILED, f"the engine could not process event {event.event_id} of job {event.job_id}: {type(error).__name__}: {error}")

    # Converging a campaign

    def _converge(self, machine: CaseMachine, session: Session, campaign: CampaignRecord, nodes: Sequence[NodeAvailability], plan: StepPlan, now: datetime) -> None:
        campaign_id = campaign.campaign_id
        if campaign.desired_state == CampaignDesiredState.STOPPED:
            self._stop(machine, session, campaign)
            return
        if campaign.actual_state == CampaignActualState.CREATED:
            if campaign.desired_state == CampaignDesiredState.PAUSED:
                return
            campaign = self._start_campaign(session, campaign, now)
            if campaign is None:
                return
        context = self.contexts.get(campaign_id, session)
        self._select(machine, session, context)
        if not self.stores.cases.list_classes(campaign_id, [CampaignClassState.OPEN], session=session):
            classes = self.stores.cases.list_classes(campaign_id, session=session)
            self._set_actual(
                session,
                campaign,
                CampaignActualState.COMPLETED,
                None,
                CampaignEventKind.COMPLETED,
                {"classes": {state.value: sum(1 for record in classes if record.state == state) for state in CampaignClassState}},
            )
            self._unrunnable_since.pop(campaign_id, None)
            return
        campaign = self._follow_desired(session, campaign, plan)
        if campaign is not None:
            self._advance(machine, session, self.contexts.get(campaign_id, session), nodes, now)

    def _follow_desired(self, session: Session, campaign: CampaignRecord, plan: StepPlan) -> Optional[CampaignRecord]:
        """Pause, resume and drain transitions; None when the campaign stays paused."""
        desired, actual = campaign.desired_state, campaign.actual_state
        if desired == CampaignDesiredState.PAUSED:
            if actual != CampaignActualState.PAUSED:
                held = self.jobs.hold_jobs(self._unfinished_jobs(session, campaign.campaign_id), session=session)
                self._set_actual(session, campaign, CampaignActualState.PAUSED, None, CampaignEventKind.PAUSED, {"held_jobs": len(held)})
            return None
        target = _target_of(desired)
        kind = CampaignEventKind.RESUMED if target == CampaignActualState.RUNNING else CampaignEventKind.DRAINING
        if actual == CampaignActualState.PAUSED:
            if desired == CampaignDesiredState.DRAINING and campaign.state_reason == DRAINED:
                return None
            released = self.jobs.release_held_jobs(self._unfinished_jobs(session, campaign.campaign_id), session=session)
            plan.wake = plan.wake or bool(released)
            return self._set_actual(session, campaign, target, None, kind, {"released_jobs": len(released)})
        if actual in (CampaignActualState.RUNNING, CampaignActualState.DRAINING) and actual != target:
            return self._set_actual(session, campaign, target, None, kind)
        return campaign

    def _advance(self, machine: CaseMachine, session: Session, context: CampaignContext, nodes: Sequence[NodeAvailability], now: datetime) -> None:
        """A running or draining campaign: the stall check, the end of a drain, the stop conditions, new cases."""
        campaign_id = context.campaign_id
        queued = self.stores.pipeline.queued_jobs_by_stage(campaign_id, session=session)
        campaign = self._check_stall(session, context, context.campaign, queued, nodes, now)
        if campaign.actual_state == CampaignActualState.STALLED:
            return
        if campaign.desired_state == CampaignDesiredState.DRAINING:
            if self.stores.cases.count_cases(campaign_id, [CaseState.ACTIVE], session=session) == 0:
                self._set_actual(session, campaign, CampaignActualState.PAUSED, DRAINED, CampaignEventKind.PAUSED, {"reason": DRAINED})
            return
        reason = self._stop_condition(session, context, now)
        if reason is not None:
            self._event(session, campaign_id, CampaignEventKind.NOTE, {"stop_condition": reason})
            self.contexts.update(self.stores.campaigns.set_desired_state(campaign_id, CampaignDesiredState.DRAINING, session=session))
            logger.info("Campaign %s drains: %s", campaign_id, reason)
            return
        if campaign.origin == CampaignOrigin.LIVE_SESSION:
            return  # its case comes from record_external_run
        self._start_cases(machine, session, context, queued)

    def _start_campaign(self, session: Session, campaign: CampaignRecord, now: datetime) -> Optional[CampaignRecord]:
        pinned = dict(campaign.pinned_fingerprints)
        if not pinned:
            expected = self._expected()
            if not expected:
                return None  # the master's expected fingerprints are not loaded yet
            pin_fingerprints(session, campaign.campaign_id, expected, now)
            pinned = dict(expected)
        target = _target_of(campaign.desired_state)
        return self._set_actual(session, campaign, target, None, CampaignEventKind.STARTED, {"pinned_fingerprints": len(pinned), "desired_state": campaign.desired_state.value})

    def _stop(self, machine: CaseMachine, session: Session, campaign: CampaignRecord) -> None:
        campaign_id = campaign.campaign_id
        context = self.contexts.get(campaign_id, session)
        active = self.stores.cases.list_cases(campaign_id, states=[CaseState.ACTIVE], session=session)
        for case in active:
            machine.cancel(context, case, STOPPED_REASON)
        for record in self.stores.cases.list_classes(campaign_id, [CampaignClassState.OPEN], session=session):
            self.stores.cases.set_class_state(campaign_id, record.class_id, CampaignClassState.ABANDONED, STOPPED_REASON, session=session)
            self._event(session, campaign_id, CampaignEventKind.CLASS_ABANDONED, {"reason": STOPPED_REASON}, record.class_id)
        unfinished = self._unfinished_jobs(session, campaign_id)
        machine.outbox.cancel(unfinished, STOPPED_REASON)
        if unfinished:
            return  # stopped once the cancels are through, on a later tick
        self._set_actual(session, campaign, CampaignActualState.STOPPED, None, CampaignEventKind.STOPPED, {"cancelled_cases": len(active)})
        self._unrunnable_since.pop(campaign_id, None)

    def _select(self, machine: CaseMachine, session: Session, context: CampaignContext) -> None:
        """The coverage controller over the classes whose cases changed (every class on the first tick)."""
        campaign_id = context.campaign_id
        if self._check_every_class:
            class_ids = [record.class_id for record in self.stores.cases.list_classes(campaign_id, [CampaignClassState.OPEN], session=session)]
        else:
            class_ids = sorted(class_id for touched_campaign, class_id in machine.outbox.touched_classes if touched_campaign == campaign_id)
        for class_id in class_ids:
            # a case quarantined while it was being completed changes the decision, so the class is decided again
            while not self._decide_class(machine, session, context, class_id):
                pass

    def _decide_class(self, machine: CaseMachine, session: Session, context: CampaignContext, class_id: str) -> bool:
        """Applies the coverage controller's decision to one class; False when a case could not be completed."""
        campaign_id = context.campaign_id
        record = self.stores.cases.get_class(campaign_id, class_id, session=session)
        if record is None or record.state != CampaignClassState.OPEN:
            return True
        cases = self.stores.cases.list_cases(campaign_id, class_id, session=session)
        decision = decide_class(cases, record.quota, record.failure_budget, record.dropped_count)
        by_id = {case.case_id: case for case in cases}
        if not all(self._complete(machine, session, context, by_id[case_id]) for case_id in decision.complete):
            return False
        cut_reason = "above the FEC's quota" if decision.close == CampaignClassState.COMPLETE else "its FEC was abandoned"
        for case_id in decision.cancel:
            machine.cancel(context, self.stores.cases.get_case(case_id, session=session), cut_reason)
        if decision.close is not None:
            self.stores.cases.set_class_state(campaign_id, class_id, decision.close, decision.reason, session=session)
            kind = CampaignEventKind.CLASS_COMPLETE if decision.close == CampaignClassState.COMPLETE else CampaignEventKind.CLASS_ABANDONED
            self._event(session, campaign_id, kind, {"reason": decision.reason, "cancelled_cases": len(decision.cancel)}, class_id)
        return True

    def _complete(self, machine: CaseMachine, session: Session, context: CampaignContext, case) -> bool:
        """Completes a ready case in a savepoint; one whose verdicts cannot be written is quarantined instead."""
        saved = machine.outbox.snapshot()
        try:
            with session.begin_nested():
                machine.complete(context, case)
            return True
        except Exception as error:
            logger.exception("Case %s could not be completed; it is quarantined", case.case_id)
            machine.outbox.restore(saved)
            with session.begin_nested():
                machine.end(context, self.stores.cases.get_case(case.case_id, session=session), CaseState.FAILED, f"its verdicts could not be written: {type(error).__name__}: {error}")
            return False

    def _check_stall(self, session: Session, context: CampaignContext, campaign: CampaignRecord, queued, nodes: Sequence[NodeAvailability], now: datetime) -> CampaignRecord:
        missing = self._missing_needs(context, queued, nodes)
        campaign_id = campaign.campaign_id
        target = _target_of(campaign.desired_state)
        if not missing:
            self._unrunnable_since.pop(campaign_id, None)
            if campaign.actual_state == CampaignActualState.STALLED:
                kind = CampaignEventKind.RESUMED if target == CampaignActualState.RUNNING else CampaignEventKind.DRAINING
                return self._set_actual(session, campaign, target, None, kind, {"reason": "a node runs every needed job type with its components again"})
            return campaign
        since = self._unrunnable_since.setdefault(campaign_id, now)
        reason = (
            "no connected node runs "
            + "; ".join(f"{job_type.value} with {', '.join(components)}" for job_type, components in missing)
            + " with the campaign's pinned fingerprints"
            + (" and labels" if context.config.resources.required_labels else "")
            + (" among its selected nodes" if context.config.resources.nodes else "")
        )
        if campaign.actual_state != CampaignActualState.STALLED and now - since >= timedelta(seconds=self.settings.stall_after_s):
            logger.warning("Campaign %s is stalled: %s", campaign_id, reason)
            detail = {"reason": reason, "job_types": sorted({job_type.value for job_type, _ in missing}), "components": sorted({component for _, components in missing for component in components})}
            return self._set_actual(session, campaign, CampaignActualState.STALLED, reason, CampaignEventKind.STALLED, detail)
        return campaign

    @staticmethod
    def _missing_needs(context: CampaignContext, queued, nodes: Sequence[NodeAvailability]) -> List[JobNeed]:
        """The job types with components that a stage with queued jobs needs and no connected node runs."""
        labels = context.config.resources.required_labels
        allowed = frozenset(context.config.resources.nodes)
        missing: List[JobNeed] = []
        for stage, count in sorted(queued.items(), key=lambda item: item[0].value):
            if count <= 0:
                continue
            # The simulate stage needs the components of each distinct stack of the runs (kinematic, ArduPilot SITL, Gazebo)
            for need in context.graph.stage_needs(stage):
                job_type, components = need
                fingerprints = required_fingerprints(components, context.pinned)
                if need not in missing and not any(node.runs(job_type, components, fingerprints, labels, allowed) for node in nodes):
                    missing.append(need)
        return missing

    def _stop_condition(self, session: Session, context: CampaignContext, now: datetime) -> Optional[str]:
        stop = context.config.policy.stop
        campaign_id = context.campaign_id
        if stop.max_cases is not None and self.stores.cases.count_cases(campaign_id, session=session) >= stop.max_cases:
            return f"{stop.max_cases} cases started (max_cases)"
        # failed verdicts of every monitored step count, scenes and trajectory sets too
        if stop.max_failed_verdicts is not None and self.stores.results.count_verdicts(campaign_id, VerdictState.FAILED, session=session) >= stop.max_failed_verdicts:
            return f"{stop.max_failed_verdicts} failed verdicts (max_failed_verdicts)"
        started = context.campaign.started_at
        if stop.max_duration_s is not None and started is not None and (now - started).total_seconds() >= stop.max_duration_s:
            return f"running for {stop.max_duration_s:.0f} s (max_duration_s)"
        return None

    def _start_cases(self, machine: CaseMachine, session: Session, context: CampaignContext, queued) -> None:
        backpressure = Backpressure(context.config.resources.queue_depth, dict(queued), context.graph.first_stage())
        room = min(backpressure.room_for_new_cases(), self.settings.max_new_cases_per_tick)
        max_cases = context.config.policy.stop.max_cases
        if max_cases is not None:
            room = min(room, max_cases - self.stores.cases.count_cases(context.campaign_id, session=session))
        if room <= 0:
            return
        classes = self.stores.cases.list_classes(context.campaign_id, [CampaignClassState.OPEN], session=session)
        planned = plan_new_cases(classes, next_case_indexes(session, context.campaign_id), room)
        machine.start_cases(context, planned)

    # Runs from outside the cluster

    async def record_external_run(self, campaign_id: str, run: ExternalRun, class_id: Optional[str] = None) -> RecordedRun:
        """Records a simulation that ran outside the cluster (a live session) as the one case of an item class (item/0 by default).

        Writes the case, its run record (source live_session, no job) and the intent of its
        post-hoc monitor in one transaction holding the cursor row, then submits the monitor
        job after the commit (a submission that fails is retried by the next tick) and wakes
        the engine. The campaign's fingerprints are pinned now when it has none yet. Raises
        ValueError when the campaign is finished or stopping, or does not take a recorded run
        (CaseMachine.record_external_run says when it does).
        """
        class_id = class_id or item_class_id(0)
        async with self._turn:
            recorded, outbox, submissions, changed = await anyio.to_thread.run_sync(self._record, campaign_id, class_id, run)
            self._recorded_classes.add((campaign_id, class_id))
            self._notify(changed)
            await self._cancel_jobs(outbox)
            await self._submit_all(submissions)
        self.wake()
        return recorded

    def _record(self, campaign_id: str, class_id: str, run: ExternalRun) -> Tuple[RecordedRun, StepOutbox, List[PlannedSubmission], Set[str]]:
        outbox = StepOutbox()
        self._changed = set()
        with self.stores.transaction() as session:
            self.stores.pipeline.read_cursor(lock=True, session=session)  # no tick writes meanwhile
            campaign = self.stores.campaigns.get_campaign(campaign_id, lock=True, session=session)
            if campaign is None or campaign.actual_state.is_final or campaign.desired_state == CampaignDesiredState.STOPPED:
                raise ValueError(f"campaign {campaign_id} is not running, so it takes no recorded run")
            expected = None if campaign.pinned_fingerprints else self._expected()
            if expected:
                pin_fingerprints(session, campaign_id, expected, self._clock())
            self.contexts.refresh(self.stores.campaigns.unfinished_campaigns(session=session))
            machine = CaseMachine(self.stores, session, self.contexts, outbox)
            recorded = machine.record_external_run(self.contexts.get(campaign_id, session), class_id, run)
            self._event(session, campaign_id, CampaignEventKind.NOTE, {"recorded_run": {"case_id": recorded.case_id, "run_record_id": recorded.run_record_id}}, class_id)
            submissions = [planned for planned in self._pending_submissions(session, outbox) if planned.case_id == recorded.case_id]
        return recorded, outbox, submissions, self._take_changes(outbox)

    # Submissions

    def _pending_submissions(self, session: Session, outbox: StepOutbox) -> List[PlannedSubmission]:
        """Intents to submit; an intent whose case or campaign ended first is retired (and its job cancelled, if one exists)."""
        intents = self.stores.pipeline.intents_without_job(session=session)
        states = case_states(session, [intent.case_id for intent in intents])
        planned = []
        for intent in intents:
            context = self.contexts.get(intent.campaign_id, session)
            state = states.get(intent.case_id)
            if context is None or state is None or state.is_final or intent.submission is None:
                job_id = job_id_by_key(session, intent.idempotency_key)
                if job_id is None:
                    delete_intent(session, intent.idempotency_key)
                else:
                    self.stores.pipeline.link_job(intent.idempotency_key, job_id, session=session)
                    outbox.cancel([job_id], f"case {intent.case_id} ended before its job was linked")
                continue
            hold = context.campaign.desired_state == CampaignDesiredState.PAUSED
            planned.append(PlannedSubmission(intent.campaign_id, intent.case_id, intent.idempotency_key, JobSubmission.model_validate(intent.submission), hold))
        return planned

    async def _submit_all(self, submissions: Sequence[PlannedSubmission]) -> int:
        if not submissions:
            return 0
        from scenegems_tool.cluster.master.control_plane import InvalidPayload

        limit = asyncio.Semaphore(self.settings.submit_concurrency)
        links: List[tuple] = []
        refused: List[tuple] = []

        async def submit_one(planned: PlannedSubmission) -> None:
            async with limit:
                try:
                    outcome = await self._submit(planned.submission)
                except InvalidPayload as error:
                    refused.append((planned, str(error)))
                    return
                except Exception as error:
                    logger.warning("Submitting %s failed; the next tick retries: %s", planned.idempotency_key, error)
                    return
                links.append((planned, outcome.job.job_id))

        await asyncio.gather(*(submit_one(planned) for planned in submissions))
        if links or refused:
            self._notify(await anyio.to_thread.run_sync(self._link, links, refused))
        return len(links)

    def _link(self, links: Sequence[tuple], refused: Sequence[tuple]) -> Set[str]:
        """Links submitted jobs to their intents and ends the cases of refused ones; returns the campaigns it changed."""
        outbox = StepOutbox()
        self._changed = set()
        with self.stores.transaction() as session:
            held = [job_id for planned, job_id in links if planned.hold]
            for planned, job_id in links:
                self.stores.pipeline.link_job(planned.idempotency_key, job_id, session=session)
            if held:
                self.jobs.hold_jobs(held, session=session)
            if not refused:
                return set()
            self.contexts.refresh(self.stores.campaigns.unfinished_campaigns(session=session))
            machine = CaseMachine(self.stores, session, self.contexts, outbox)
            for planned, error in refused:
                delete_intent(session, planned.idempotency_key)
                case = self.stores.cases.get_case(planned.case_id, session=session)
                context = self.contexts.get(planned.campaign_id, session, None if case is None else case.config_version)
                if case is not None and context is not None and not case.state.is_final:
                    machine.end(context, case, CaseState.FAILED, f"the master refused the {planned.submission.job_type.value} job: {error}")
        return self._take_changes(outbox)

    async def _cancel_jobs(self, outbox: StepOutbox) -> int:
        cancelled = 0
        for job_id, reason in sorted(outbox.jobs_to_cancel.items()):
            try:
                outcome = await self._cancel(job_id, reason)
            except Exception as error:
                logger.warning("Cancelling job %s failed: %s", job_id, error)
                continue
            cancelled += int(bool(getattr(outcome, "cancelled", False)))
        return cancelled

    # Helpers

    def _event(self, session: Session, campaign_id: str, kind: CampaignEventKind, detail: Optional[Dict[str, Any]] = None, class_id: Optional[str] = None) -> None:
        self.stores.campaigns.append_event(campaign_id, kind, detail, class_id=class_id, session=session)
        self._changed.add(campaign_id)

    def _take_changes(self, outbox: StepOutbox) -> Set[str]:
        """The campaigns the last transaction wrote to: events appended, cases of their classes moved."""
        changed = self._changed | {campaign_id for campaign_id, _ in outbox.touched_classes}
        self._changed = set()
        return changed

    def _notify(self, campaign_ids: Set[str]) -> None:
        if not campaign_ids or self.on_change is None:
            return
        try:
            self.on_change(set(campaign_ids))
        except Exception:
            logger.exception("The campaign change listener failed")

    def _unfinished_jobs(self, session: Session, campaign_id: str) -> List[str]:
        return self.stores.pipeline.job_ids_of_campaign(campaign_id, UNFINISHED_JOB_STATES, session=session)

    def _set_actual(self, session: Session, campaign: CampaignRecord, state: CampaignActualState, reason: Optional[str], kind: CampaignEventKind, detail: Optional[dict] = None) -> CampaignRecord:
        updated = self.stores.campaigns.set_actual_state(campaign.campaign_id, state, reason, session=session)
        self._event(session, campaign.campaign_id, kind, detail)
        self.contexts.update(updated)
        logger.info("Campaign %s (%s) is %s%s", campaign.campaign_id, campaign.name, state.value, f": {reason}" if reason else "")
        return updated


def _target_of(desired: CampaignDesiredState) -> CampaignActualState:
    """The actual state a running campaign converges on: running, or draining."""
    return CampaignActualState.DRAINING if desired == CampaignDesiredState.DRAINING else CampaignActualState.RUNNING
