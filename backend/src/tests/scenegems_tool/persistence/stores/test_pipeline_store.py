"""Pipeline jobs (intent, submission, link) and the cursor over the job events."""

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select

from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobState, JobType
from scenegems_tool.cluster.protocol.messages import JobResult
from scenegems_tool.persistence.database import transaction
from scenegems_tool.persistence.schema import CaseState, JobEventKind, JobRow, PipelineStage
from scenegems_tool.persistence.stores import ENGINE_CURSOR, START_OF_EVENTS, CursorConflict, CursorPosition, NewCase, PipelineJobConflict, UnknownPipelineJob
from scenegems_tool.persistence.stores.job_event_log import append_job_event
from tests.scenegems_tool.persistence.stores.builders import make_hello, make_submission
from tests.scenegems_tool.persistence.stores.conftest import CLASS_A

pytestmark = pytest.mark.postgres

SCENE = JobType.SCENE_GENERATION
LEASE_S = 30.0


@pytest.fixture
def case(stores, campaign):
    return stores.cases.create_case(campaign.campaign_id, NewCase(class_id=CLASS_A, case_index=0, seed=7))


def _submit_for(stores, job_store, campaign, case, key, stage=PipelineStage.GENERATE_SCENE, run_index=None):
    """The engine's two steps: the intent, then the job, then the link."""
    submission = make_submission(idempotency_key=key)
    stores.pipeline.add_intent(campaign.campaign_id, case.case_id, stage, key, run_index=run_index, submission=submission.model_dump(mode="json"))
    job = job_store.submit(submission).job
    stores.pipeline.link_job(key, job.job_id)
    return job


def _succeed(job_store, lease):
    return job_store.report_result(JobResult(lease_id=lease.lease_id, job_id=lease.job.job_id, idempotency_key=lease.job.idempotency_key, outcome=JobOutcome.SUCCEEDED, result={"valid": True}))


# Intents and links


def test_an_intent_waits_for_its_job(stores, campaign, case, job_store):
    outcome = stores.pipeline.add_intent(campaign.campaign_id, case.case_id, PipelineStage.GENERATE_SCENE, "c1/0/scene", submission={"job_type": "scene_generation"})
    assert outcome.created and outcome.pipeline_job.is_intent and outcome.pipeline_job.submission == {"job_type": "scene_generation"}
    assert [intent.idempotency_key for intent in stores.pipeline.intents_without_job(campaign.campaign_id)] == ["c1/0/scene"]
    again = stores.pipeline.add_intent(campaign.campaign_id, case.case_id, PipelineStage.GENERATE_SCENE, "c1/0/scene")
    assert not again.created and again.pipeline_job == outcome.pipeline_job
    job = job_store.submit(make_submission(idempotency_key="c1/0/scene")).job
    linked = stores.pipeline.link_job("c1/0/scene", job.job_id)
    assert (linked.job_id, linked.submission, linked.is_intent) == (job.job_id, None, False)
    assert stores.pipeline.link_job("c1/0/scene", job.job_id) == linked
    assert stores.pipeline.intents_without_job() == []
    assert stores.pipeline.get_by_job_id(job.job_id) == linked
    assert stores.pipeline.get_by_key("c1/0/scene") == linked
    assert stores.pipeline.pipeline_jobs_of_case(case.case_id) == [linked]


def test_a_crash_between_intent_and_submission_resubmits_the_same_job(stores, campaign, case, job_store):
    key = "c1/0/scene"
    submission = make_submission(idempotency_key=key)
    stores.pipeline.add_intent(campaign.campaign_id, case.case_id, PipelineStage.GENERATE_SCENE, key, submission=submission.model_dump(mode="json"))
    first = job_store.submit(submission).job  # the engine dies before link_job
    (intent,) = stores.pipeline.intents_without_job()
    again = job_store.submit(type(submission).model_validate(intent.submission))
    assert not again.created and again.job.job_id == first.job_id
    stores.pipeline.link_job(key, again.job.job_id)
    assert stores.pipeline.intents_without_job() == []


def test_a_key_names_one_case_stage_and_run(stores, campaign, case):
    stores.pipeline.add_intent(campaign.campaign_id, case.case_id, PipelineStage.SIMULATE, "c1/0/run0", run_index=0)
    with pytest.raises(PipelineJobConflict):
        stores.pipeline.add_intent(campaign.campaign_id, case.case_id, PipelineStage.SIMULATE, "c1/0/run0", run_index=1)
    with pytest.raises(ValueError):
        stores.pipeline.add_intent(campaign.campaign_id, case.case_id, PipelineStage.VERDICT, "c1/0/verdict")


def test_an_intent_links_one_job(stores, campaign, case, job_store):
    _submit_for(stores, job_store, campaign, case, "c1/0/scene")
    other = job_store.submit(make_submission(idempotency_key="other")).job
    with pytest.raises(PipelineJobConflict):
        stores.pipeline.link_job("c1/0/scene", other.job_id)
    with pytest.raises(UnknownPipelineJob):
        stores.pipeline.link_job("missing", other.job_id)


def test_job_ids_and_queue_depth_of_a_campaign(stores, campaign, case, job_store, worker_node_store):
    worker_node_store.register(make_hello("worker-node-a", slots={SCENE: 4}))
    scene = _submit_for(stores, job_store, campaign, case, "c1/0/scene")
    trajectories = _submit_for(stores, job_store, campaign, case, "c1/0/trajectories", stage=PipelineStage.GENERATE_TRAJECTORIES)
    stores.pipeline.add_intent(campaign.campaign_id, case.case_id, PipelineStage.SIMULATE, "c1/0/run0", run_index=0)
    job_store.submit(make_submission(idempotency_key="not-a-pipeline-job"))
    assert stores.pipeline.job_ids_of_campaign(campaign.campaign_id) == sorted([scene.job_id, trajectories.job_id])
    assert stores.pipeline.queued_jobs_by_stage(campaign.campaign_id) == {PipelineStage.GENERATE_SCENE: 1, PipelineStage.GENERATE_TRAJECTORIES: 1, PipelineStage.SIMULATE: 1}
    lease = job_store.claim_next("worker-node-a", LEASE_S)
    assert lease.job.job_id == scene.job_id
    assert stores.pipeline.job_ids_of_campaign(campaign.campaign_id, [JobState.QUEUED]) == [trajectories.job_id]
    assert stores.pipeline.queued_jobs_by_stage(campaign.campaign_id) == {PipelineStage.GENERATE_TRAJECTORIES: 1, PipelineStage.SIMULATE: 1}


# Cursor


def test_a_new_cursor_starts_at_the_beginning(stores):
    assert stores.pipeline.read_cursor() == START_OF_EVENTS
    assert stores.pipeline.read_cursor("other") == START_OF_EVENTS


def test_events_after_the_cursor_are_terminal_events_of_pipeline_jobs(stores, campaign, case, job_store, worker_node_store):
    worker_node_store.register(make_hello("worker-node-a", slots={SCENE: 4}))
    scene = _submit_for(stores, job_store, campaign, case, "c1/0/scene")
    plain = job_store.submit(make_submission(idempotency_key="not-a-pipeline-job")).job
    trajectories = _submit_for(stores, job_store, campaign, case, "c1/0/trajectories", stage=PipelineStage.GENERATE_TRAJECTORIES)
    leases = {lease.job.job_id: lease for lease in (job_store.claim_next("worker-node-a", LEASE_S) for _ in range(3))}
    _succeed(job_store, leases[scene.job_id])
    _succeed(job_store, leases[plain.job_id])
    job_store.cancel(trajectories.job_id, "campaign stopped")

    batch = stores.pipeline.events_after(START_OF_EVENTS)
    assert [(event.job_id, event.kind) for event in batch.events] == [(scene.job_id, JobEventKind.SUCCEEDED), (trajectories.job_id, JobEventKind.CANCELLED)]
    first = batch.events[0]
    assert (first.pipeline_job.idempotency_key, first.pipeline_job.case_id, first.job_state, first.job_result, first.worker_node_id) == (
        "c1/0/scene",
        case.case_id,
        JobState.SUCCEEDED,
        {"valid": True},
        "worker-node-a",
    )
    assert batch.events[1].detail == {"reason": "campaign stopped"}
    # the batch's position passes the last event, whichever job or kind it has
    assert batch.position >= batch.events[-1].position
    assert stores.pipeline.events_after(batch.position).events == ()
    every_kind = stores.pipeline.events_after(START_OF_EVENTS, kinds=None).events
    assert {event.kind for event in every_kind} == {JobEventKind.SUBMITTED, JobEventKind.LEASED, JobEventKind.SUCCEEDED, JobEventKind.CANCELLED}
    assert all(event.pipeline_job.campaign_id == campaign.campaign_id for event in every_kind)


def test_a_full_batch_ends_at_its_last_event(stores, campaign, case, job_store):
    jobs = [_submit_for(stores, job_store, campaign, case, f"c1/0/scene-{index}") for index in range(5)]
    for job in jobs:
        job_store.cancel(job.job_id, "test")
    seen, position = [], START_OF_EVENTS
    while True:
        batch = stores.pipeline.events_after(position, limit=2)
        seen.extend(event.job_id for event in batch.events)
        if not batch.events:
            break
        assert len(batch.events) < 2 or batch.position == batch.events[-1].position
        position = batch.position
    assert seen == [job.job_id for job in jobs]


def test_an_event_that_commits_late_is_not_skipped(stores, campaign, case, job_store, session_factory):
    """The trap of an id cursor: an event with a lower id becomes visible after one with a higher id."""
    early, late = (_submit_for(stores, job_store, campaign, case, key) for key in ("c1/0/early", "c1/0/late"))
    with transaction(session_factory) as slow:
        row = slow.execute(select(JobRow).where(JobRow.id == early.job_id).with_for_update()).scalar_one()
        row.state = JobState.CANCELLED
        row.finished_at = row.updated_at
        append_job_event(slow, row, JobEventKind.CANCELLED, JobState.QUEUED, row.updated_at, {"reason": "slow"})
        slow.flush()  # the early event has its id now, below the late one's
        job_store.cancel(late.job_id, "fast")  # commits at once
        batch = stores.pipeline.events_after(START_OF_EVENTS)
        assert batch.events == ()  # the late event waits until the slow transaction has ended
        position = batch.position  # past the submissions, which ended before
    batch = stores.pipeline.events_after(position)
    assert [event.job_id for event in batch.events] == [early.job_id, late.job_id]
    early_event, late_event = batch.events
    assert early_event.event_id < late_event.event_id


def test_advancing_the_cursor_commits_with_the_case_update(stores, campaign, case, job_store):
    job = _submit_for(stores, job_store, campaign, case, "c1/0/scene")
    job_store.cancel(job.job_id, "test")

    def engine_step(fail: bool):
        with stores.transaction() as session:
            position = stores.pipeline.read_cursor(lock=True, session=session)
            batch = stores.pipeline.events_after(position, session=session)
            for event in batch.events:
                current = stores.cases.get_case(event.pipeline_job.case_id, session=session)
                stores.cases.move_case(current.case_id, current.version, state=CaseState.CANCELLED, reason=event.detail["reason"], session=session)
            stores.pipeline.advance_cursor(ENGINE_CURSOR, position, batch.position, session=session)
            if fail:
                raise RuntimeError("the control node died mid-step")
            return batch

    with pytest.raises(RuntimeError):
        engine_step(fail=True)
    assert stores.pipeline.read_cursor() == START_OF_EVENTS and stores.cases.get_case(case.case_id).state == CaseState.ACTIVE
    batch = engine_step(fail=False)
    assert len(batch.events) == 1
    assert stores.pipeline.read_cursor() == batch.position and stores.cases.get_case(case.case_id).state == CaseState.CANCELLED
    assert engine_step(fail=False).events == ()


def test_the_cursor_moves_from_where_it_was_read(stores):
    stores.pipeline.read_cursor()
    stores.pipeline.advance_cursor(ENGINE_CURSOR, START_OF_EVENTS, CursorPosition(10, 4))
    with pytest.raises(CursorConflict):
        stores.pipeline.advance_cursor(ENGINE_CURSOR, START_OF_EVENTS, CursorPosition(12, 5))
    with pytest.raises(ValueError):
        stores.pipeline.advance_cursor(ENGINE_CURSOR, CursorPosition(10, 4), CursorPosition(9, 9))
    with pytest.raises(CursorConflict):
        stores.pipeline.advance_cursor("never-read", START_OF_EVENTS, CursorPosition(1, 1))
    assert stores.pipeline.read_cursor() == CursorPosition(10, 4)


def test_a_reader_sees_every_event_of_concurrent_writers_once(stores, campaign, case, job_store):
    writers, jobs_per_writer = 8, 25
    jobs = [_submit_for(stores, job_store, campaign, case, f"c1/0/job-{index}") for index in range(writers * jobs_per_writer)]
    barrier = threading.Barrier(writers + 1)
    done = threading.Event()
    seen = Counter()

    def write(index: int) -> None:
        barrier.wait()
        for job in jobs[index::writers]:
            job_store.cancel(job.job_id, "test")

    def read() -> None:
        barrier.wait()
        position = START_OF_EVENTS
        while True:
            finished = done.is_set()  # read once more after the writers finished
            batch = stores.pipeline.events_after(position, limit=7)
            seen.update(event.job_id for event in batch.events)
            position = batch.position
            if finished and not batch.events:
                return

    with ThreadPoolExecutor(max_workers=writers + 1) as pool:
        reader = pool.submit(read)
        for future in [pool.submit(write, index) for index in range(writers)]:
            future.result()
        done.set()
        reader.result()
    assert set(seen) == {job.job_id for job in jobs}
    assert max(seen.values()) == 1
