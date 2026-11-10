"""The producers of the worker nodes, job and job instance topics on a control node with scripted worker nodes (memory and -m postgres)."""

from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from scenegems_tool.cluster.control_node.api.control_node_apps import create_worker_node_api_app
from scenegems_tool.cluster.control_node.api.live_routes import live_router
from scenegems_tool.cluster.control_node.api.operator_routes import WORKER_NODES_PATH, operator_router
from scenegems_tool.cluster.control_node.live.live_channel import LiveChannel
from scenegems_tool.cluster.control_node.live.topics import CampaignListTopic, CampaignTopics, create_live_channel
from scenegems_tool.cluster.protocol.live import TopicKind, campaign_topic, campaigns_topic, instance_topic, job_instance, job_topic
from scenegems_tool.cluster.protocol.messages import JobStatus, LeaseOffer, LogLine, LogLines, LogStream
from scenegems_tool.cluster.protocol.routes import JOBS_PATH
from scenegems_tool.persistence.schema import CampaignActualState, CampaignClassState, CampaignDesiredState, CampaignEventKind
from scenegems_tool.persistence.stores import AssuranceStores
from tests.scenegems_tool.assurance.pipeline.conftest import CLASS_A, CLASS_B, config_dict, create_campaign
from tests.scenegems_tool.cluster.control_node.conftest import SCENE
from tests.scenegems_tool.cluster.control_node.live.conftest import Browser, settle
from tests.scenegems_tool.cluster.control_node.live.live_browser import LiveBrowser
from tests.scenegems_tool.cluster.payloads import valid_payload
from tests.scenegems_tool.persistence.stores.builders import ManualClock


@pytest.fixture
def channel(plane):
    return create_live_channel(plane)


@pytest.fixture
def client(plane, channel):
    """The control node's worker node API with the operator routes and the live channel on one test client."""
    app = create_worker_node_api_app(plane, run_timers=False)
    app.include_router(operator_router(plane))
    app.include_router(live_router(channel))
    with TestClient(app) as client:
        yield client


@pytest.fixture
def browser(client):
    browser = LiveBrowser(client)
    yield browser
    browser.close()


@pytest.fixture
def idle(on_loop, channel):
    """Waits until the producers handled every change so far."""
    return lambda: on_loop(channel.producers.idle)


def _submit(client) -> dict:
    response = client.post(JOBS_PATH, json={"job_type": SCENE.value, "payload": valid_payload(SCENE)})
    assert response.status_code == 201
    return response.json()


def _line(text: str) -> LogLine:
    return LogLine(timestamp=datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc), stream=LogStream.STDOUT, source="runner", text=text)


def test_the_worker_nodes_topic_follows_connects_drains_and_disconnects(client, browser, make_worker_node, idle):
    first = make_worker_node("lab 1")
    first.connect()
    snapshot = browser.subscribe("worker_nodes")
    assert [worker_node["worker_node_id"] for worker_node in snapshot] == [first.worker_node_id] and snapshot[0]["connected"] is True

    second = make_worker_node("lab 2")
    second.connect()
    idle()
    joined = browser.expect_update("worker_nodes")["worker_node"]
    assert joined["worker_node_id"] == second.worker_node_id and joined["status"] == "online" and joined["connected"] is True

    second.heartbeat()
    idle()
    browser.drain()  # the first heartbeat may report other resources than the Hello
    second.heartbeat()
    idle()
    assert browser.drain() == []  # nothing changed but the time it was last seen

    client.post(f"{WORKER_NODES_PATH}/{second.worker_node_id}/drain", json={"reason": "maintenance"})
    idle()
    assert browser.expect_update("worker_nodes")["worker_node"]["status"] == "draining"

    second.close()
    idle()
    left = browser.expect_update("worker_nodes")["worker_node"]
    assert left["worker_node_id"] == second.worker_node_id and left["connected"] is False


def test_the_worker_nodes_topic_announces_a_removed_worker_node(client, browser, make_worker_node, idle, on_loop, plane, clock):
    gone = make_worker_node("lab 1")
    kept = make_worker_node("lab 2")
    gone.connect()
    kept.connect()
    browser.subscribe("worker_nodes")
    gone.close()
    idle()
    browser.drain()
    clock.advance(plane.registry._offline_after_s + 1)
    on_loop(plane.registry.sweep_silent)
    idle()
    browser.drain()
    assert client.post(f"{WORKER_NODES_PATH}/{gone.worker_node_id}/remove").status_code == 200
    idle()
    assert browser.expect_update("worker_nodes") == {"removed": gone.worker_node_id}


def test_the_job_topic_follows_a_job_through_its_life(client, browser, make_worker_node, schedule, idle):
    worker_node = make_worker_node("lab 1", slots={SCENE: 1})
    worker_node.connect()
    job = _submit(client)
    snapshot = browser.subscribe(job_topic(job["job_id"]))
    assert snapshot["job_id"] == job["job_id"] and snapshot["state"] == "queued" and snapshot["logs"] == [] and snapshot["progress"] is None

    schedule()
    offer = worker_node.expect(LeaseOffer)
    idle()
    assert browser.expect_update(job_topic(job["job_id"]))["job"]["state"] == "leased"

    worker_node.accept(offer)
    idle()
    running = browser.expect_update(job_topic(job["job_id"]))["job"]
    assert running["state"] == "running" and running["lease_owner"] == worker_node.worker_node_id

    worker_node.send(JobStatus(lease_id=offer.lease_id, job_id=job["job_id"], progress=0.4, message="sampling"))
    worker_node.send_and_sync(LogLines(lease_id=offer.lease_id, job_id=job["job_id"], lines=[_line("hello"), _line("world")]))
    status = browser.expect_update(job_topic(job["job_id"]))["status"]
    assert (status["progress"], status["message"]) == (0.4, "sampling")
    assert [line["text"] for line in browser.expect_update(job_topic(job["job_id"]))["logs"]] == ["hello", "world"]

    worker_node.succeed(offer, {"sample": 1})
    idle()
    finished = browser.expect_update(job_topic(job["job_id"]))["job"]
    assert finished["state"] == "succeeded" and finished["result"] == {"sample": 1}
    assert browser.drain() == []


def test_a_snapshot_has_the_log_lines_so_far(client, browser, make_worker_node, schedule):
    worker_node = make_worker_node("lab 1", slots={SCENE: 1})
    worker_node.connect()
    job = _submit(client)
    schedule()
    offer = worker_node.expect(LeaseOffer)
    worker_node.accept(offer)
    worker_node.send_and_sync(LogLines(lease_id=offer.lease_id, job_id=job["job_id"], lines=[_line("early")]))
    snapshot = browser.subscribe(job_topic(job["job_id"]))
    assert snapshot["state"] == "running" and [line["text"] for line in snapshot["logs"]] == ["early"]
    worker_node.send_and_sync(LogLines(lease_id=offer.lease_id, job_id=job["job_id"], lines=[_line("late")]))
    assert [line["text"] for line in browser.expect_update(job_topic(job["job_id"]))["logs"]] == ["late"]


def test_an_unknown_job_is_an_error(browser):
    browser.send({"type": "subscribe", "topic": "job:no-such-job"})
    error = browser.receive()
    assert error["type"] == "error" and error["topic"] == "job:no-such-job" and "no job" in error["message"]


def test_a_job_instance_shows_the_jobs_state_and_progress(client, browser, make_worker_node, schedule, idle, channel):
    worker_node = make_worker_node("lab 1", slots={SCENE: 1})
    worker_node.connect()
    job = _submit(client)
    schedule()
    offer = worker_node.expect(LeaseOffer)
    observed = []
    channel.producers.hub.on_job_observation = lambda *arguments: observed.append(arguments)
    topic = instance_topic(worker_node.worker_node_id, job_instance(job["job_id"], 1))
    snapshot = browser.subscribe(topic)
    assert snapshot == {
        "worker_node_id": worker_node.worker_node_id,
        "instance": f"job-{job['job_id']}-1",
        "kind": "scene_generation",
        "state": "leased",
        "job_id": job["job_id"],
        "attempt": 1,
        "observed_speed": 10.0,
    }
    assert observed == [(worker_node.worker_node_id, job["job_id"], 1, True)]

    worker_node.accept(offer)
    idle()
    assert browser.expect_update(topic) == {"kind": "status", "state": "running", "message": "", "progress": None, "observed_speed": 10.0}
    worker_node.send_and_sync(JobStatus(lease_id=offer.lease_id, job_id=job["job_id"], progress=0.5, message="half way"))
    assert browser.expect_update(topic) == {"kind": "status", "state": "running", "message": "half way", "progress": 0.5, "observed_speed": 10.0}

    browser.send({"type": "unsubscribe", "topic": topic})
    assert browser.receive()["type"] == "unsubscribed"
    assert observed[-1] == (worker_node.worker_node_id, job["job_id"], 1, False)


def test_a_later_attempt_than_the_jobs_is_refused(client, browser, make_worker_node):
    worker_node = make_worker_node("lab 1", slots={SCENE: 1})
    worker_node.connect()
    job = _submit(client)
    browser.send({"type": "subscribe", "topic": instance_topic(worker_node.worker_node_id, job_instance(job["job_id"], 1))})
    error = browser.receive()
    assert error["type"] == "error" and "has not started attempt 1" in error["message"]


def test_hooks_do_nothing_without_subscribers(client, make_worker_node, schedule, channel, on_loop):
    marked = []
    for worker in (channel.producers.worker_nodes.worker, channel.producers.jobs.worker):
        worker.mark = marked.append  # what a hook would hand on
    worker_node = make_worker_node("lab 1", slots={SCENE: 1})
    worker_node.connect()
    worker_node.heartbeat()
    job = _submit(client)
    schedule()
    offer = worker_node.expect(LeaseOffer)
    worker_node.accept(offer)
    worker_node.send_and_sync(JobStatus(lease_id=offer.lease_id, job_id=job["job_id"], progress=0.5, message="half way"))
    worker_node.send_and_sync(LogLines(lease_id=offer.lease_id, job_id=job["job_id"], lines=[_line("x")]))
    worker_node.succeed(offer)
    client.post(f"{WORKER_NODES_PATH}/{worker_node.worker_node_id}/drain", json={"reason": "x"})
    worker_node.close()
    assert marked == [] and channel.topics() == set()


# Campaigns (Postgres): the producer as the pipeline engine's notifications drive it


@pytest.fixture
def campaign_stores(session_factory):
    return AssuranceStores.create(session_factory, ManualClock())


@pytest.mark.anyio
@pytest.mark.postgres
async def test_the_campaign_topic_sends_new_events_summary_changes_and_changed_classes(campaign_stores):
    stores = campaign_stores
    campaign = create_campaign(stores, config_dict(classes=(CLASS_A, CLASS_B), quota=2), CampaignDesiredState.PAUSED)
    channel = LiveChannel()
    campaigns = CampaignTopics(channel, stores)
    channel.add_source(TopicKind.CAMPAIGN, campaigns)
    topic = campaign_topic(campaign.campaign_id)
    browser = Browser(channel)
    browser.socket.subscribe(topic)
    (subscribed,) = await browser.messages(1)
    snapshot = subscribed["snapshot"]
    assert snapshot["campaign_id"] == campaign.campaign_id and snapshot["actual_state"] == "created"
    assert [entry["fec_id"] for entry in snapshot["fecs"]] == [CLASS_A, CLASS_B] and snapshot["totals"]["quota"] == 4
    last_event_id = snapshot["last_event_id"]
    await campaigns.worker.idle()  # the priming read finds nothing newer
    await settle()
    assert browser.socket.take() == []

    # What a tick of the engine writes, then its notification
    stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.RUNNING)
    stores.campaigns.append_event(campaign.campaign_id, CampaignEventKind.STARTED, {"pinned_fingerprints": 0})
    stores.cases.set_class_state(campaign.campaign_id, CLASS_B, CampaignClassState.ABANDONED, "a test")
    stores.campaigns.append_event(campaign.campaign_id, CampaignEventKind.CLASS_ABANDONED, {"reason": "a test"}, class_id=CLASS_B)
    campaigns.campaigns_changed({campaign.campaign_id, "a-campaign-nobody-watches"})
    await campaigns.worker.idle()
    started, abandoned, summary, classes = await browser.messages(4)
    assert [started["data"]["event"]["kind"], abandoned["data"]["event"]["kind"]] == ["started", "fec_abandoned"]
    assert started["data"]["event"]["event_id"] > last_event_id
    assert summary["data"]["campaign"]["actual_state"] == "running" and "fecs" not in summary["data"]["campaign"]
    assert [(entry["fec_id"], entry["state"]) for entry in classes["data"]["fecs"]] == [(CLASS_B, "abandoned")]
    assert [message["seq"] for message in (started, abandoned, summary, classes)] == [1, 2, 3, 4]

    campaigns.campaigns_changed({campaign.campaign_id})  # nothing new
    await campaigns.worker.idle()
    await settle()
    assert browser.socket.take() == []

    await browser.leave()
    campaigns.campaigns_changed({campaign.campaign_id})
    assert not campaigns.worker.busy  # nobody watches: nothing is read


@pytest.mark.anyio
@pytest.mark.postgres
async def test_an_unknown_campaign_is_an_error(campaign_stores):
    channel = LiveChannel()
    channel.add_source(TopicKind.CAMPAIGN, CampaignTopics(channel, campaign_stores))
    browser = Browser(channel)
    browser.socket.subscribe("campaign:no-such-campaign")
    (error,) = await browser.messages(1)
    assert error["type"] == "error" and "no campaign no-such-campaign" in error["message"] and channel.topics() == set()
    await browser.leave()


def test_the_channel_hooks_into_the_pipeline_engine(plane, channel):
    assert channel.source(TopicKind.CAMPAIGN) is None  # the plane of these tests has no campaign stores

    class Engine:
        on_change = None

    plane.pipeline = Engine()
    with_campaigns = create_live_channel(plane, assurance=object())
    assert plane.pipeline.on_change == with_campaigns.producers.campaigns.campaigns_changed


@pytest.mark.anyio
@pytest.mark.postgres
async def test_the_campaigns_topic_sends_a_row_for_every_change_and_the_id_of_a_deleted_campaign(campaign_stores):
    stores = campaign_stores
    listing = CampaignListTopic(LiveChannel(), stores)
    channel = listing._channel
    channel.add_source(TopicKind.CAMPAIGNS, listing)
    campaign = create_campaign(stores, config_dict(classes=(CLASS_A, CLASS_B), quota=2), CampaignDesiredState.PAUSED)
    browser = Browser(channel)
    browser.socket.subscribe(campaigns_topic())
    (subscribed,) = await browser.messages(1)
    assert subscribed["topic"] == "campaigns" and subscribed["snapshot"] == {}

    listing.campaigns_changed({campaign.campaign_id, "a-campaign-that-does-not-exist"})
    await listing.worker.idle()
    (created,) = await browser.messages(1)
    row = created["data"]["campaign"]
    assert created["seq"] == 1 and set(created["data"]) == {"campaign"}
    assert (row["campaign_id"], row["kind"], row["origin"], row["actual_state"]) == (campaign.campaign_id, "campaign", None, "created")
    assert row["steps"] == ["scene_generation", "trajectory_generation", "simulation"] and row["input"] == {"first_step": "scene_generation", "item_count": 0} and row["made_from"] == []
    assert row["totals"] == {"cases": {}, "verdicts": {}}

    listing.campaigns_changed({campaign.campaign_id})  # nothing changed in the row
    await listing.worker.idle()
    await settle()
    assert browser.socket.take() == []

    stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.RUNNING)
    listing.campaigns_changed({campaign.campaign_id})
    await listing.worker.idle()
    (running,) = await browser.messages(1)
    assert running["data"]["campaign"]["actual_state"] == "running" and running["seq"] == 2

    stores.campaigns.set_actual_state(campaign.campaign_id, CampaignActualState.COMPLETED)
    stores.campaigns.delete_campaign(campaign.campaign_id)
    listing.campaign_deleted(campaign.campaign_id)
    listing.campaigns_changed({campaign.campaign_id})  # a change that was marked before the delete is not sent as a row
    await listing.worker.idle()
    await settle()
    (deleted,) = browser.socket.take()
    assert deleted["data"] == {"deleted": campaign.campaign_id} and deleted["seq"] == 3

    await browser.leave()
    listing.campaigns_changed({"someone"})
    assert not listing.worker.busy  # nobody watches: nothing is read
    listing.campaign_deleted("someone")  # and nothing is sent


@pytest.mark.anyio
@pytest.mark.postgres
async def test_the_engines_notification_reaches_the_campaigns_topic(campaign_stores):
    channel = LiveChannel()
    listing = CampaignListTopic(channel, campaign_stores)
    campaigns = CampaignTopics(channel, campaign_stores, listing)
    channel.add_source(TopicKind.CAMPAIGNS, listing)
    campaign = create_campaign(campaign_stores, config_dict(), CampaignDesiredState.PAUSED)
    browser = Browser(channel)
    browser.socket.subscribe(campaigns_topic())
    await browser.messages(1)
    campaigns.campaigns_changed({campaign.campaign_id})  # what PipelineEngine.on_change calls
    await listing.worker.idle()
    (row,) = await browser.messages(1)
    assert row["data"]["campaign"]["campaign_id"] == campaign.campaign_id
    await browser.leave()


def test_the_channel_serves_the_campaigns_topic_beside_the_campaign_topics(plane):
    class Engine:
        on_change = None

    plane.pipeline = Engine()
    with_campaigns = create_live_channel(plane, assurance=object())
    listing = with_campaigns.producers.campaign_list
    assert isinstance(listing, CampaignListTopic) and with_campaigns.source(TopicKind.CAMPAIGNS) is listing
    assert listing.worker in with_campaigns.producers._workers()
    assert create_live_channel(plane).source(TopicKind.CAMPAIGNS) is None and create_live_channel(plane).producers.campaign_list is None
