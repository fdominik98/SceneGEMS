"""How a case moves: one job event at a time, in the engine's transaction, with optimistic versions.

A case starts active at the stage of the campaign's first configured step, from its input:
a catalog class's content or a functional scenario given as content (generate_scene), an
item's scene (generate_trajectories) or an item's trajectories (simulate). An item case
records the item's hash and source (input_artifact, input_source); a scenario case the
scenario's hash. The case moves through the stage graph as its jobs succeed: each success
records what it produced (artifact references, run records, pending verdicts) in the case's
progress and writes the intents of the jobs that became due. A monitored scene or trajectory
set gets its monitor job beside the next step's job; the monitor's result is the step's
pending verdict. Every move goes through CaseStore.move_case with the version the case was
read at.

A run recorded outside the cluster (a live session, record_external_run) creates the one case
of its item class at simulate, with the run record (source live_session, no job) and the
intent of its post-hoc monitor, as if its simulate job had succeeded.

It leaves the pipeline early as

    dropped    the scene is invalid, or the trajectory generator found no trajectory, or no
               complete one while a simulation follows (the reason is recorded;
               trajectories_complete says which); when trajectory generation is the last
               step, a valid but incomplete trajectory set (the best partial path) completes
               the case with trajectories_complete false
    failed     a job ended failed (out of attempts, or a failure that is not retryable), was
               cancelled by someone else, or returned a result its stage cannot use; the case
               is quarantined with the error
    cancelled  the campaign stopped, or the coverage controller cut it (above the quota, or
               its class was abandoned)

Dropped and failed cases count against their class's failure budget (the class's dropped
count). A final case keeps its state; later events of its jobs change nothing, and the jobs
it still has are cancelled.

Events are processed once: the step of an event already in the case's progress is skipped,
so a job with several terminal-looking events (an expired lease, then a failure) is handled
once.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from sqlalchemy.orm import Session

from scenegems_tool.assurance.campaign.campaign_config import CampaignStep, InputItem, RetentionPolicy
from scenegems_tool.assurance.pipeline import retention
from scenegems_tool.assurance.pipeline.campaign_context import CampaignContext, CampaignContexts
from scenegems_tool.assurance.pipeline.payload_builder import PayloadError
from scenegems_tool.assurance.pipeline.pipeline_queries import job_facts, unfinished_jobs_of_cases
from scenegems_tool.assurance.pipeline.stage_graph import GENERATION_MONITORS, SCENE_MONITOR_STEP, SCENE_STEP, TRAJECTORIES_MONITOR_STEP, TRAJECTORIES_STEP, CaseProgress, Step
from scenegems_tool.assurance.pipeline.verdicts import (
    ResultError,
    is_sensitive,
    new_calibration_result,
    new_run_record,
    new_verdict,
    pending_from_live,
    pending_from_post_hoc,
    pending_unmonitored,
    record_references,
    release_job_references,
    step_roles,
)
from scenegems_tool.cluster.protocol.artifacts import is_reference
from scenegems_tool.cluster.protocol.jobs import JobState
from scenegems_tool.persistence.schema import ArtifactHolderKind, CampaignClassState, CaseState, JobEventKind, MonitorImplementation, PipelineStage, RunSource, StepKind, VerdictState
from scenegems_tool.persistence.stores import UNSET, AssuranceStores, CaseConflict, CaseRecord, NewCase, PipelineJobEvent

logger = logging.getLogger(__name__)

SUCCEEDED, FAILED, CANCELLED = "succeeded", "failed", "cancelled"
RECORDED = "recorded"  # the outcome of a simulate step that ran outside the cluster


@dataclass(frozen=True)
class ExternalRun:
    """A simulation that ran outside the cluster (a live session), as record_external_run stores it.

    state_log is the reference (wire form or ArtifactRef) of the stored state log, a
    Trajectories document in the master's artifact store; stack is the run's stack as the
    session configured it (per vessel), environment its environment.
    """

    state_log: Any
    stack: Mapping[str, Any]
    environment: Mapping[str, Any] = field(default_factory=dict)
    dt: Optional[float] = None
    steps: Optional[int] = None
    repeatability_tier: Optional[str] = None  # the resolver's tier of the session's stack
    state_digest: Optional[str] = None
    seed: Optional[int] = None  # the run seed of the case seed when None
    trajectories_complete: bool = True
    node_id: Optional[str] = None
    fingerprints: Mapping[str, str] = field(default_factory=dict)
    durations_s: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RecordedRun:
    """What record_external_run wrote: the case, its run record, and the key of its post-hoc monitor job (None when unmonitored)."""

    campaign_id: str
    case_id: int
    run_record_id: int
    monitor_key: Optional[str]


@dataclass
class StepOutbox:
    """What a step of the engine leaves to do after its transaction, and what it touched."""

    jobs_to_cancel: Dict[str, str] = field(default_factory=dict)  # job id to the reason
    touched_classes: Set[Tuple[str, str]] = field(default_factory=set)  # (campaign id, class id) whose cases changed
    events_applied: int = 0
    cases_started: int = 0

    def cancel(self, job_ids, reason: str) -> None:
        for job_id in job_ids:
            self.jobs_to_cancel.setdefault(job_id, reason)

    def snapshot(self) -> tuple:
        return dict(self.jobs_to_cancel), set(self.touched_classes), self.events_applied, self.cases_started

    def restore(self, saved: tuple) -> None:
        jobs, touched, self.events_applied, self.cases_started = saved
        self.jobs_to_cancel, self.touched_classes = dict(jobs), set(touched)


def _outcome_of(event: PipelineJobEvent) -> Optional[str]:
    """succeeded, failed or cancelled when the event ends its job; None for an expired lease that requeued it."""
    if event.kind == JobEventKind.SUCCEEDED:
        return SUCCEEDED
    if event.kind == JobEventKind.FAILED or (event.kind == JobEventKind.EXPIRED and event.job_state == JobState.FAILED):
        return FAILED
    if event.kind == JobEventKind.CANCELLED:
        return CANCELLED
    return None


class CaseMachine:
    def __init__(self, stores: AssuranceStores, session: Session, contexts: CampaignContexts, outbox: StepOutbox):
        self.stores = stores
        self.session = session
        self.contexts = contexts
        self.outbox = outbox

    # Starting cases

    def start_cases(self, context: CampaignContext, planned: List[Tuple[str, int]]) -> List[CaseRecord]:
        """Creates the planned cases (class id, index) with their seeds and inputs, and the intents of their first step's jobs."""
        if not planned:
            return []
        created = self.stores.cases.create_cases(context.campaign_id, [self._new_case(context, class_id, index) for class_id, index in planned], session=self.session)
        first = context.graph.first_step.value.replace("_", " ")
        for case in created:
            self.outbox.touched_classes.add((context.campaign_id, case.class_id))
            try:
                self._intents(context, case, self._first_steps(context, case))
            except PayloadError as error:
                self.end(context, case, CaseState.FAILED, f"the {first} payload could not be built: {error}")
        self.outbox.cases_started += len(created)
        return created

    @staticmethod
    def _new_case(context: CampaignContext, class_id: str, index: int) -> NewCase:
        input_artifact, input_source = context.case_input(class_id)
        return NewCase(
            class_id=class_id,
            case_index=index,
            seed=context.config.case_seed(class_id, index),
            config_version=context.campaign.config_version,
            stage=context.graph.first_stage(),
            input_artifact=input_artifact,
            input_source=input_source,
        )

    def _first_steps(self, context: CampaignContext, case: CaseRecord) -> List[Tuple[Step, Dict[str, Any]]]:
        """The jobs a new case starts with: its first configured step's, from its input."""
        builder, graph = context.builder, context.graph
        if graph.first_step == CampaignStep.SCENE_GENERATION:
            return [(SCENE_STEP, builder.scene_generation(case.class_id, context.content_hashes[case.class_id], case.seed))]
        item = context.input_of(case.class_id)
        if not isinstance(item, InputItem):
            raise PayloadError(f"FEC {case.class_id} has no input item")
        if graph.first_step == CampaignStep.TRAJECTORY_GENERATION:
            return [(TRAJECTORIES_STEP, builder.trajectory_generation_of_item(case.seed, item))]
        return [(simulate, builder.simulation_of_item(case.seed, simulate.run_index, item)) for simulate in graph.simulate_steps()]

    # Events

    def apply(self, event: PipelineJobEvent) -> None:
        pipeline_job = event.pipeline_job
        outcome = _outcome_of(event)
        if outcome is None:
            return
        case = self.stores.cases.get_case(pipeline_job.case_id, session=self.session)
        if case is None:
            return
        context = self.contexts.get(pipeline_job.campaign_id, self.session, case.config_version)
        if context is None:
            return
        if case.state.is_final:
            # A job of an ended case: its results are not needed, unless the campaign keeps everything
            if outcome == SUCCEEDED and context.config.policy.retention != RetentionPolicy.ALL:
                release_job_references(self.stores, self.session, event.job_id)
            return
        step = Step.of(pipeline_job.stage, pipeline_job.run_index, pipeline_job.repeat_index)
        progress = CaseProgress(case.progress)
        if progress.handled(step):
            return
        self.outbox.events_applied += 1
        progress.mark(step, outcome)
        if outcome != SUCCEEDED:
            error = event.job_error or event.detail.get("reason") or "no error given"
            verb = "was cancelled" if outcome == CANCELLED else "failed"
            self.end(context, case, CaseState.FAILED, f"{step.name} job {event.job_id} {verb}: {error}", progress)
            return
        result = event.job_result or {}
        try:
            handler = {
                PipelineStage.GENERATE_SCENE: self._scene_generated,
                PipelineStage.MONITOR_SCENE: self._generation_monitored,
                PipelineStage.GENERATE_TRAJECTORIES: self._trajectories_generated,
                PipelineStage.MONITOR_TRAJECTORIES: self._generation_monitored,
                PipelineStage.SIMULATE: self._simulated,
                PipelineStage.MONITOR: self._monitored,
                PipelineStage.CALIBRATE: self._calibrated,
            }[step.stage]
            handler(context, case, progress, step, event, result)
        except (ResultError, PayloadError) as error:
            self.end(context, case, CaseState.FAILED, f"{step.name} job {event.job_id}: {error}", progress)

    def _scene_generated(self, context: CampaignContext, case: CaseRecord, progress: CaseProgress, step: Step, event: PipelineJobEvent, result: Mapping[str, Any]) -> None:
        roles = record_references(self.stores, self.session, result, ArtifactHolderKind.CASE, case.case_id, context.campaign_id, event.job_id)
        scene = roles.get("scene", UNSET)
        if not result.get("valid") or result.get("evaluation_data") is None:
            self.end(context, case, CaseState.DROPPED, "the scene generation found no valid scene", progress, scene_artifact=scene)
            return
        due = []
        if context.graph.scene_monitored:
            due.append((SCENE_MONITOR_STEP, context.builder.scene_monitoring(f"{context.scenario_name(case)}#scene", result)))
        if context.graph.runs_step(CampaignStep.TRAJECTORY_GENERATION):
            due.append((TRAJECTORIES_STEP, context.builder.trajectory_generation(case.seed, result)))
        case = self._save(context, case, progress, scene_artifact=scene)
        self._intents(context, case, due)

    def _trajectories_generated(self, context: CampaignContext, case: CaseRecord, progress: CaseProgress, step: Step, event: PipelineJobEvent, result: Mapping[str, Any]) -> None:
        roles = record_references(self.stores, self.session, result, ArtifactHolderKind.CASE, case.case_id, context.campaign_id, event.job_id)
        trajectories = roles.get("trajectory_data", UNSET)
        valid, complete = bool(result.get("valid")), bool(result.get("complete"))
        if not valid or result.get("trajectory_data") is None:
            reason = "the trajectory generator found no trajectories" + (f": {result['error_message']}" if result.get("error_message") else "")
            self.end(context, case, CaseState.DROPPED, reason, progress, trajectories_artifact=trajectories, trajectories_complete=False)
            return
        simulates = context.graph.runs_step(CampaignStep.SIMULATION)
        if not complete and simulates:
            self.end(
                context,
                case,
                CaseState.DROPPED,
                "the trajectory generator found no complete trajectories (only the best partial path)",
                progress,
                trajectories_artifact=trajectories,
                trajectories_complete=False,
            )
            return
        due = []
        if context.graph.trajectories_monitored:
            due.append((TRAJECTORIES_MONITOR_STEP, context.builder.trajectory_monitoring(f"{context.scenario_name(case)}#trajectories", result)))
        if simulates:
            due += [(simulate, context.builder.simulation(case.seed, simulate.run_index, result)) for simulate in context.graph.simulate_steps()]
        # The last step keeps a trajectory set that is not complete (the best partial path), flagged
        case = self._save(context, case, progress, trajectories_artifact=trajectories, trajectories_complete=complete)
        self._intents(context, case, due)

    def _generation_monitored(self, context: CampaignContext, case: CaseRecord, progress: CaseProgress, step: Step, event: PipelineJobEvent, result: Mapping[str, Any]) -> None:
        """A scene or trajectory monitor's result: the step's pending verdict, and its frames held by the case."""
        step_kind = GENERATION_MONITORS[step.stage]
        pending = pending_from_post_hoc(result)
        record_references(self.stores, self.session, result, ArtifactHolderKind.CASE, case.case_id, context.campaign_id, event.job_id, step_roles(step_kind))
        progress.set_step_verdict(step_kind, pending)
        self._save(context, case, progress)

    def _simulated(self, context: CampaignContext, case: CaseRecord, progress: CaseProgress, step: Step, event: PipelineJobEvent, result: Mapping[str, Any]) -> None:
        run_index, repeat_index = step.run_index, step.repeat_index
        run = context.graph.run(run_index)
        if result.get("trajectories") is None and (run.monitor == MonitorImplementation.POST_HOC or context.graph.needs_calibration(run_index)):
            raise ResultError("the simulation returned no trajectories")
        facts = job_facts(self.session, [event.job_id]).get(event.job_id)
        tier = (result.get("run_record") or {}).get("repeatability_tier") or context.graph.run_tier(run_index)
        record = self.stores.results.add_run_record(
            new_run_record(
                case_id=case.case_id,
                run_index=run_index,
                repeat_index=repeat_index,
                generator=self._generator(context),
                trajectories_complete=self._trajectories_complete(context, case),
                stack=context.stack(run_index),
                environment=context.environment(run_index),
                seed=run.seed_for(case.seed),
                simulation_result=result,
                input_trajectories_hash=self._input_trajectories(context, case),
                job_id=event.job_id,
                node_id=facts.lease_owner if facts is not None else event.node_id,
                fingerprints=facts.required_fingerprints if facts is not None else {},
                durations_s=facts.durations_s() if facts is not None else {},
                tier=tier,
            ),
            session=self.session,
        )
        record_references(self.stores, self.session, result, ArtifactHolderKind.RUN, record.run_record_id, context.campaign_id, event.job_id)
        progress.set_run_record(run_index, repeat_index, record.run_record_id)
        if repeat_index == 0:
            state = progress.run(run_index)
            state["tier"] = record.repeatability_tier
            if run.monitor == MonitorImplementation.LIVE:
                state["verdict"] = pending_from_live(result)
            elif run.monitor == MonitorImplementation.EMPTY:
                state["verdict"] = pending_unmonitored()
        due = []
        for next_step in context.graph.steps_after_simulation(progress, run_index, repeat_index):
            if next_step.stage == PipelineStage.MONITOR:
                due.append((next_step, context.builder.post_hoc_monitoring(f"{context.scenario_name(case)}#run{run_index}", result)))
            else:
                due.append((next_step, context.builder.calibration(context.scenario_name(case), context.stack(run_index), self._repeat_results(case, run_index, event.job_id, result))))
        case = self._save(context, case, progress)
        self._intents(context, case, due)

    def _monitored(self, context: CampaignContext, case: CaseRecord, progress: CaseProgress, step: Step, event: PipelineJobEvent, result: Mapping[str, Any]) -> None:
        pending = pending_from_post_hoc(result)
        run_record_id = progress.run_record_id(step.run_index, 0)
        if run_record_id is not None:
            record_references(self.stores, self.session, result, ArtifactHolderKind.RUN, run_record_id, context.campaign_id, event.job_id)
        progress.run(step.run_index)["verdict"] = pending
        self._save(context, case, progress)

    def _calibrated(self, context: CampaignContext, case: CaseRecord, progress: CaseProgress, step: Step, event: PipelineJobEvent, result: Mapping[str, Any]) -> None:
        calibration = new_calibration_result(result, context.stack(step.run_index), context.run_fingerprints(step.run_index), context.environment(step.run_index), context.campaign_id)
        stored = self.stores.calibrations.upsert(calibration, session=self.session)
        state = progress.run(step.run_index)
        state["calibrated"] = True
        state["calibration"] = {"calibration_id": stored.calibration_id, "exact": stored.exact, "deviation_bound_m": stored.deviation_bound_m}
        self._save(context, case, progress)

    def _repeat_results(self, case: CaseRecord, run_index: int, current_job_id: str, current: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        """The simulation results of every repeat of the run, in repeat order."""
        jobs = [job for job in self.stores.pipeline.pipeline_jobs_of_case(case.case_id, session=self.session) if job.stage == PipelineStage.SIMULATE and job.run_index == run_index]
        facts = job_facts(self.session, [job.job_id for job in jobs if job.job_id is not None and job.job_id != current_job_id])
        results = []
        for job in sorted(jobs, key=lambda job: job.repeat_index):
            result = current if job.job_id == current_job_id else (facts.get(job.job_id).result if job.job_id in facts else None)
            if result is None or result.get("trajectories") is None:
                raise ResultError(f"repeat {job.repeat_index} of run {run_index} has no trajectories to calibrate with")
            results.append(result)
        return results

    # Ends

    def complete(self, context: CampaignContext, case: CaseRecord) -> CaseRecord:
        """Writes the ready case's verdicts (of its monitored scene and trajectory steps, then of its runs), applies retention and completes it."""
        progress = CaseProgress(case.progress)
        step_states: Dict[StepKind, VerdictState] = {}
        for step_kind in context.graph.monitored_steps():
            pending = progress.step_verdict(step_kind)
            if pending is None:
                raise ValueError(f"case {case.case_id} has no {step_kind.value} verdict")
            verdict = self.stores.results.add_verdict(new_verdict(case.case_id, 0, pending, None, False, step=step_kind), session=self.session)
            step_states[step_kind] = verdict.state
        states: Dict[int, VerdictState] = {}
        run_records: Dict[int, List[int]] = {}
        for run_index in range(len(context.graph.runs)):
            pending = progress.pending_verdict(run_index)
            if pending is None:
                raise ValueError(f"case {case.case_id} has no verdict for run {run_index}")
            tier = progress.run(run_index).get("tier")
            sensitive = is_sensitive(self.stores, self.session, tier, context.stack(run_index), context.run_fingerprints(run_index))
            verdict = self.stores.results.add_verdict(new_verdict(case.case_id, run_index, pending, progress.run_record_id(run_index, 0), sensitive), session=self.session)
            states[run_index] = verdict.state
            run_records[run_index] = sorted(progress.run(run_index).get("run_records", {}).values())
        keep_trajectories = context.graph.is_last(CampaignStep.TRAJECTORY_GENERATION)  # the campaign's output, like the scene
        retention.apply_on_verdicts(self.stores, self.session, context.config.policy.retention, case.case_id, states, run_records, step_states, keep_trajectories)
        moved = self._move(case, state=CaseState.COMPLETE, stage=PipelineStage.VERDICT, reason=None)
        self.outbox.touched_classes.add((context.campaign_id, case.class_id))
        return moved

    def cancel(self, context: CampaignContext, case: CaseRecord, reason: str) -> CaseRecord:
        moved = self.end(context, case, CaseState.CANCELLED, reason)
        policy: RetentionPolicy = context.config.policy.retention
        retention.apply_on_cancel(self.stores, self.session, policy, case.case_id, CaseProgress(case.progress).run_record_ids())
        return moved

    def end(self, context: CampaignContext, case: CaseRecord, state: CaseState, reason: str, progress: Optional[CaseProgress] = None, **fields: Any) -> CaseRecord:
        """Moves the case to a final state with its reason; its unfinished jobs are cancelled after the transaction."""
        if progress is not None:
            fields["progress"] = progress.to_json()
        moved = self._move(case, state=state, reason=reason, **fields)
        self.outbox.touched_classes.add((context.campaign_id, case.class_id))
        self.outbox.cancel(unfinished_jobs_of_cases(self.session, [case.case_id]), f"case {case.case_id} is {state.value}: {reason}")
        if state != CaseState.CANCELLED:
            logger.info("Case %s (%s) is %s: %s", case.case_id, context.scenario_name(case), state.value, reason)
        return moved

    # Runs from outside the cluster

    def record_external_run(self, context: CampaignContext, class_id: str, run: ExternalRun) -> RecordedRun:
        """Creates the class's one case with a recorded run 0 (repeat 0): its run record, and its post-hoc monitor's intent or its unmonitored verdict.

        The campaign must simulate only, with one run of one repeat judged post_hoc or not at
        all, and the class must be open without a case. Raises ValueError otherwise.
        """
        graph, campaign_id = context.graph, context.campaign_id
        if graph.steps != (CampaignStep.SIMULATION,) or len(graph.runs) != 1 or graph.run(0).repeats != 1:
            raise ValueError(f"campaign {campaign_id} does not take a recorded run: it needs the simulation step only, with one run of one repeat")
        run_config = graph.run(0)
        if run_config.monitor == MonitorImplementation.LIVE:
            raise ValueError(f"campaign {campaign_id} judges its run live; a recorded run is judged post_hoc or not at all")
        if not is_reference(run.state_log):
            raise ValueError("a recorded run's state log must be stored as an artifact first")
        record = self.stores.cases.get_class(campaign_id, class_id, session=self.session)
        if record is None or record.state != CampaignClassState.OPEN:
            raise ValueError(f"campaign {campaign_id} has no open FEC {class_id}")
        if self.stores.cases.list_cases(campaign_id, class_id, session=self.session):
            raise ValueError(f"FEC {class_id} of campaign {campaign_id} has its case already")
        (case,) = self.stores.cases.create_cases(campaign_id, [self._new_case(context, class_id, 0)], session=self.session)
        self.outbox.touched_classes.add((campaign_id, class_id))
        simulate = Step(PipelineStage.SIMULATE, 0, 0)
        progress = CaseProgress()
        progress.mark(simulate, RECORDED)
        state_log = run.state_log.model_dump(mode="json") if hasattr(run.state_log, "model_dump") else dict(run.state_log)
        result = {
            "trajectories": state_log,
            "steps": run.steps,
            "state_digest": run.state_digest,
            "run_record": {"dt": run.dt, "repeatability_tier": run.repeatability_tier, "environment": dict(run.environment)},
        }
        run_record = self.stores.results.add_run_record(
            new_run_record(
                case_id=case.case_id,
                run_index=0,
                repeat_index=0,
                generator=None,
                trajectories_complete=run.trajectories_complete,
                stack=run.stack,
                environment=run.environment,
                seed=run.seed if run.seed is not None else run_config.seed_for(case.seed),
                simulation_result=result,
                input_trajectories_hash=case.input_artifact,
                job_id=None,
                node_id=run.node_id,
                fingerprints=run.fingerprints,
                durations_s=run.durations_s,
                tier=run.repeatability_tier,
                source=RunSource.LIVE_SESSION,
            ),
            session=self.session,
        )
        record_references(self.stores, self.session, result, ArtifactHolderKind.RUN, run_record.run_record_id, campaign_id)
        progress.set_run_record(0, 0, run_record.run_record_id)
        progress.run(0)["tier"] = run_record.repeatability_tier
        due = []
        if graph.needs_monitor_job(0):
            due.append((Step(PipelineStage.MONITOR, 0), context.builder.post_hoc_monitoring(f"{context.scenario_name(case)}#run0", result)))
        else:
            progress.run(0)["verdict"] = pending_unmonitored()
        case = self._save(context, case, progress)
        written = self._intents(context, case, due)
        key = due[0][0].idempotency_key(campaign_id, case.case_id) if due and written else None
        return RecordedRun(campaign_id, case.case_id, run_record.run_record_id, key)

    # Helpers

    @staticmethod
    def _generator(context: CampaignContext):
        """The trajectory generator of the campaign's runs; None when their trajectories come from an input item."""
        return context.config.trajectories.generator if context.graph.runs_step(CampaignStep.TRAJECTORY_GENERATION) else None

    @staticmethod
    def _trajectories_complete(context: CampaignContext, case: CaseRecord) -> bool:
        """Whether the simulated trajectories were complete; an input item's count as complete (taken as given)."""
        return True if context.graph.first_step == CampaignStep.SIMULATION else bool(case.trajectories_complete)

    @staticmethod
    def _input_trajectories(context: CampaignContext, case: CaseRecord) -> Optional[str]:
        """The hash of the trajectories the runs simulate: the generated ones (None when inline), or the input item's."""
        return case.input_artifact if context.graph.first_step == CampaignStep.SIMULATION else case.trajectories_artifact

    def _save(self, context: CampaignContext, case: CaseRecord, progress: CaseProgress, **fields: Any) -> CaseRecord:
        moved = self._move(case, stage=context.graph.stage_of(progress), progress=progress.to_json(), **fields)
        self.outbox.touched_classes.add((context.campaign_id, case.class_id))
        return moved

    def _move(self, case: CaseRecord, **changes: Any) -> CaseRecord:
        try:
            return self.stores.cases.move_case(case.case_id, case.version, session=self.session, **changes)
        except CaseConflict as conflict:
            # Only the engine moves cases, so the case changed earlier in this transaction; retry on its current version
            current = conflict.current
            if current is None or current.state.is_final:
                raise
            return self.stores.cases.move_case(case.case_id, current.version, session=self.session, **changes)

    def _intents(self, context: CampaignContext, case: CaseRecord, due: List[Tuple[Step, Dict[str, Any]]]) -> bool:
        """Writes the intents of the due jobs, each checked first; an invalid payload fails the case and writes none (False)."""
        submissions = []
        for step, payload in due:
            key = step.idempotency_key(context.campaign_id, case.case_id)
            try:
                submissions.append((step, key, context.builder.submission(step, payload, key, context.pinned)))
            except PayloadError as error:
                self.end(context, case, CaseState.FAILED, f"the {step.name} payload is invalid: {error}")
                return False
        for step, key, submission in submissions:
            self.stores.pipeline.add_intent(
                context.campaign_id, case.case_id, step.stage, key, run_index=step.run_index, repeat_index=step.repeat_index, submission=submission.model_dump(mode="json"), session=self.session
            )
        return True
