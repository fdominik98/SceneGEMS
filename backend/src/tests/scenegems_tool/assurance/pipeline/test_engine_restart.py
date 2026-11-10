"""Restarts: an engine replaced mid-campaign, crashes between the steps of a tick, failed commits,
two engines on one database (one leads with the engine lock, the other stands by).

Every test ends with the same books: no case lost or duplicated, the counts agree with the
cases, one job per pipeline job, and the campaign complete with its exact quota.
"""

import asyncio
from contextlib import contextmanager

import pytest
from sqlalchemy import func, select, text

from scenegems_tool.cluster.protocol.jobs import JobState
from scenegems_tool.persistence.database import transaction
from scenegems_tool.persistence.schema import CampaignActualState, CampaignDesiredState, CampaignEventKind, JobRow, PipelineJobRow
from scenegems_tool.persistence.stores import AssuranceStores
from tests.scenegems_tool.assurance.pipeline.checks import assert_consistent
from tests.scenegems_tool.assurance.pipeline.conftest import CLASS_A, CLASS_B, config_dict, create_campaign
from tests.scenegems_tool.assurance.pipeline.fake_executor import LEASE_S

pytestmark = pytest.mark.postgres


def _assert_one_job_per_pipeline_job(harness, campaign_id: str) -> None:
    with transaction(harness.stores.session_factory) as session:
        pipeline_jobs = session.execute(select(func.count()).select_from(PipelineJobRow).where(PipelineJobRow.campaign_id == campaign_id)).scalar_one()
        linked = session.execute(select(func.count(func.distinct(PipelineJobRow.job_id))).where(PipelineJobRow.campaign_id == campaign_id)).scalar_one()
        jobs = session.execute(select(func.count()).select_from(JobRow).where(JobRow.idempotency_key.like(f"campaign:{campaign_id}:%"))).scalar_one()
    assert pipeline_jobs == linked == jobs


def _assert_finished_with_quota(harness, campaign, quota_cases: int) -> None:
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.COMPLETED
    states = assert_consistent(harness.stores, campaign.campaign_id)
    assert states.get("complete") == quota_cases
    _assert_one_job_per_pipeline_job(harness, campaign.campaign_id)


def test_a_new_engine_continues_where_the_old_one_stopped(harness):
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=3, failure_budget=1))
    for _ in range(3):
        harness.settle()
        harness.executor.run(limit=3)
    harness.settle()
    harness.executor.claim_all(limit=2)  # two jobs are leased when the control node goes down
    # The control node is down for longer than a lease: the leases expire and the jobs return to the queue
    harness.clock.advance(LEASE_S + 1)
    assert len(harness.job_store.expire_leases()) == 2
    harness.replace_engine()
    harness.drive(campaign.campaign_id)
    _assert_finished_with_quota(harness, campaign, 6)
    assert [event.kind for event in harness.stores.campaigns.list_events(campaign.campaign_id, limit=None)].count(CampaignEventKind.ENGINE_STARTED) == 2


def test_a_crash_inside_a_tick_loses_nothing(harness, monkeypatch):
    campaign = create_campaign(harness.stores, config_dict(quota=2, failure_budget=0))
    harness.settle()
    harness.executor.run()
    position = harness.stores.pipeline.read_cursor()

    def crash(*arguments, **options):
        raise RuntimeError("the control node died before the commit")

    monkeypatch.setattr(harness.stores.pipeline, "advance_cursor", crash)
    with pytest.raises(RuntimeError):
        harness.tick()
    monkeypatch.undo()
    assert harness.stores.pipeline.read_cursor() == position  # the events of the crashed tick are still ahead
    harness.replace_engine()
    harness.drive(campaign.campaign_id)
    _assert_finished_with_quota(harness, campaign, 2)


def test_a_commit_that_went_through_unacknowledged_is_not_taken_for_another_engine(harness, monkeypatch):
    campaign = create_campaign(harness.stores, config_dict(quota=1, failure_budget=0))
    harness.settle()
    harness.executor.run()
    original = AssuranceStores.transaction

    @contextmanager
    def lost_acknowledgment(stores):
        with original(stores) as session:
            yield session
        raise ConnectionError("the connection dropped after the commit")

    monkeypatch.setattr(AssuranceStores, "transaction", lost_acknowledgment)
    with pytest.raises(ConnectionError):
        harness.tick()
    monkeypatch.undo()
    assert not harness.tick().stopped
    harness.drive(campaign.campaign_id)
    assert not harness.engine.stopped
    _assert_finished_with_quota(harness, campaign, 1)


def test_intents_left_by_a_crash_before_their_submission_are_resubmitted(harness, monkeypatch):
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=2, failure_budget=0))

    async def crash_before_submitting(submissions):
        return 0

    monkeypatch.setattr(harness.engine, "_submit_all", crash_before_submitting)
    harness.tick()
    assert len(harness.stores.pipeline.intents_without_job(campaign.campaign_id)) == 4 and harness.job_store.list_jobs() == []
    harness.replace_engine()
    harness.tick()
    assert harness.stores.pipeline.intents_without_job(campaign.campaign_id) == [] and len(harness.job_store.list_jobs()) == 4
    harness.drive(campaign.campaign_id)
    _assert_finished_with_quota(harness, campaign, 4)


def test_a_crash_between_submission_and_link_resubmits_the_same_jobs(harness, monkeypatch):
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=2, failure_budget=0))
    harness.settle()
    harness.executor.run()  # the scene results arrive

    def crash_before_linking(*arguments):
        raise RuntimeError("the control node died before linking")

    monkeypatch.setattr(harness.engine, "_link", crash_before_linking)
    with pytest.raises(RuntimeError):
        harness.tick()
    unlinked = harness.stores.pipeline.intents_without_job(campaign.campaign_id)
    assert len(unlinked) == 4
    submitted = {job.idempotency_key: job.job_id for job in harness.job_store.list_jobs(state=JobState.QUEUED)}
    assert set(submitted) == {intent.idempotency_key for intent in unlinked}
    harness.replace_engine()
    harness.tick()
    assert harness.stores.pipeline.intents_without_job(campaign.campaign_id) == []
    assert {key: harness.stores.pipeline.get_by_key(key).job_id for key in submitted} == submitted  # the job store returned the jobs it had
    harness.drive(campaign.campaign_id)
    _assert_finished_with_quota(harness, campaign, 4)


def test_jobs_left_running_for_ended_cases_are_cancelled_at_start(harness, monkeypatch):
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=2, failure_budget=0))
    harness.settle()

    async def crash_before_cancelling(outbox):
        return 0

    monkeypatch.setattr(harness.engine, "_cancel_jobs", crash_before_cancelling)
    harness.stores.campaigns.set_desired_state(campaign.campaign_id, CampaignDesiredState.STOPPED)
    harness.tick()
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.RUNNING  # stopped once its jobs are cancelled
    assert len(harness.stores.pipeline.job_ids_of_campaign(campaign.campaign_id, [JobState.QUEUED])) == 4
    harness.replace_engine()
    harness.settle()
    assert harness.campaign(campaign.campaign_id).actual_state == CampaignActualState.STOPPED
    assert {harness.job_store.get(job_id).state for job_id in harness.stores.pipeline.job_ids_of_campaign(campaign.campaign_id)} == {JobState.CANCELLED}
    (started,) = [event for event in harness.stores.campaigns.list_events(campaign.campaign_id, limit=None) if event.kind == CampaignEventKind.ENGINE_STARTED][1:]
    assert started.detail["orphaned_jobs"] == 4
    assert_consistent(harness.stores, campaign.campaign_id)


def _engine_starts(harness, campaign_id: str) -> int:
    return [event.kind for event in harness.stores.campaigns.list_events(campaign_id, limit=None)].count(CampaignEventKind.ENGINE_STARTED)


def test_a_second_engine_on_the_same_database_stands_by_and_takes_over(harness):
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=2, failure_budget=1))
    harness.settle()
    harness.executor.run()
    second = harness.new_engine()
    assert not harness.run(second.start())  # the first engine holds the engine lock
    position = harness.stores.pipeline.read_cursor()
    report = harness.tick(second)
    assert report.standby and not second.stopped and harness.stores.pipeline.read_cursor() == position  # a standby writes nothing
    harness.settle()  # the first engine leads on and moves the cursor
    assert harness.tick(second).standby
    harness.crash()  # the first control node dies
    assert not harness.tick(second).standby
    harness.drive(campaign.campaign_id, engine=second)
    _assert_finished_with_quota(harness, campaign, 4)
    assert _engine_starts(harness, campaign.campaign_id) == 2


def test_a_stopped_engine_gives_the_lock_to_the_next(harness):
    campaign = create_campaign(harness.stores, config_dict(quota=2, failure_budget=0))
    harness.settle()
    second = harness.new_engine()
    assert harness.tick(second).standby
    harness.engine.stop()
    assert harness.tick(harness.engine).stopped
    harness.drive(campaign.campaign_id, engine=second)
    _assert_finished_with_quota(harness, campaign, 2)


def test_a_cancelled_engine_run_gives_the_lock_up(harness):
    # The control plane stops its timers by cancelling them; the next control node must be able to lead
    async def run_then_cancel():
        task = asyncio.create_task(harness.engine.run(0.01))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if harness.engine.leadership.held:
                break
        assert harness.engine.leadership.held
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    harness.run(run_then_cancel())
    assert not harness.engine.leadership.held
    assert harness.run(harness.new_engine().start())


def test_two_failed_commits_in_a_row_lose_nothing(harness, monkeypatch):
    # The first commit went through unacknowledged, the second did not: the engine must not take
    # the cursor of the first for another engine's, as an engine that remembers where it left it would
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=2, failure_budget=0))
    harness.settle()
    assert harness.executor.run(limit=3) == 3  # the first tick reads these results, the second the rest
    original = AssuranceStores.transaction
    failures = []

    @contextmanager
    def failing_commits(stores):
        failures.append(len(failures))
        if len(failures) == 1:
            with original(stores) as session:
                yield session
            raise ConnectionError("the connection dropped after the commit")
        with original(stores) as session:
            yield session
            raise ConnectionError("the connection dropped before the commit")

    monkeypatch.setattr(AssuranceStores, "transaction", failing_commits)
    with pytest.raises(ConnectionError):
        harness.tick()
    moved = harness.stores.pipeline.read_cursor()
    left = harness.executor.run()  # results that the second tick reads and loses with its rollback
    assert left > 0
    with pytest.raises(ConnectionError):
        harness.tick()
    monkeypatch.undo()
    assert harness.stores.pipeline.read_cursor() == moved
    report = harness.tick()
    assert not report.stopped and not report.standby and report.events_read == left
    harness.drive(campaign.campaign_id)
    _assert_finished_with_quota(harness, campaign, 4)


def test_an_engine_whose_lock_connection_ended_takes_the_lock_again_and_reconciles(harness):
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=2, failure_budget=0))
    harness.settle()
    harness.executor.run()
    term = harness.engine.leadership.term
    with transaction(harness.stores.session_factory) as session:
        assert session.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": harness.engine.leadership._pid}).scalar()
    report = harness.tick()
    assert not report.standby and harness.engine.leadership.term == term + 1
    harness.drive(campaign.campaign_id)
    _assert_finished_with_quota(harness, campaign, 4)
    assert _engine_starts(harness, campaign.campaign_id) == 2


def test_a_tick_writes_nothing_once_another_engine_holds_the_lock(harness, monkeypatch):
    campaign = create_campaign(harness.stores, config_dict(classes=(CLASS_A, CLASS_B), quota=2, failure_budget=0))
    harness.settle()
    harness.executor.run()
    first = harness.engine
    with transaction(harness.stores.session_factory) as session:
        session.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": first.leadership._pid})
    second = harness.new_engine()
    assert not harness.tick(second).standby  # the lock was free, so the second engine leads
    harness.executor.run()
    position = harness.stores.pipeline.read_cursor()
    monkeypatch.setattr(first.leadership, "acquire", lambda: True)  # the first engine has not noticed yet
    assert harness.tick(first).standby  # its tick finds the lock held by another connection and writes nothing
    assert harness.stores.pipeline.read_cursor() == position
    monkeypatch.undo()
    assert harness.tick(first).standby
    harness.drive(campaign.campaign_id, engine=second)
    _assert_finished_with_quota(harness, campaign, 4)
