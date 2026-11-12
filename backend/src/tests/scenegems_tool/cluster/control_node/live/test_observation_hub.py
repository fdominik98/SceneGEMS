"""The observation hub against a fake broker client: pools observed only while someone watches, previews translated."""

import json

import pytest

from scenegems_tool.cluster.control_node.control_plane import ControlPlane
from scenegems_tool.cluster.control_node.live.live_channel import LiveSettings
from scenegems_tool.cluster.control_node.live.observation_hub import GENERATED_SCENE_TOPIC, TRAJECTORY_PREVIEW_TOPIC, TRAJECTORY_RESULT_TOPIC, translate_pool_message
from scenegems_tool.cluster.control_node.live.topics import create_live_channel
from scenegems_tool.cluster.control_node.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.protocol.jobs import JobSubmission, JobType
from scenegems_tool.cluster.protocol.live import SceneSample, TrajectoryPreview, instance_topic, job_instance
from scenegems_tool.cluster.protocol.messages import JobStatus
from tests.scenegems_tool.cluster.control_node.conftest import EXPECTED
from tests.scenegems_tool.cluster.control_node.fake_stores import InMemoryJobStore, InMemoryWorkerNodeStore
from tests.scenegems_tool.cluster.control_node.live.conftest import Browser, settle
from tests.scenegems_tool.cluster.control_node.live.fake_broker import FakeBroker
from tests.scenegems_tool.cluster.payloads import valid_payload
from tests.scenegems_tool.persistence.stores.builders import ManualClock, make_hello

pytestmark = pytest.mark.anyio

WORKER_NODE = "lab-1"
SCENE_POOL = "scene_generation-0"
TRAJECTORY_POOL = "trajectory_generation-0"
# The first worker node the control node registered is number 1: its pools carry that number on the broker.
SCENE_PREFIX = "scenegems/service/virtual/real/scene-generation-subsystem-1/"


@pytest.fixture
def broker() -> FakeBroker:
    return FakeBroker()


@pytest.fixture
def plane() -> ControlPlane:
    clock = ManualClock()
    worker_nodes = InMemoryWorkerNodeStore(clock)
    plane = ControlPlane("lab-control-node", worker_nodes, InMemoryJobStore(worker_nodes, clock), ExpectedFingerprints.fixed(EXPECTED), clock=clock)
    worker_nodes.register(make_hello(WORKER_NODE, slots={JobType.SCENE_GENERATION: 1, JobType.SIMULATION: 1}))
    return plane


@pytest.fixture
def channel(plane, broker):
    return create_live_channel(plane, broker=lambda: broker, settings=LiveSettings(preview_interval_s=0.0, frames_interval_s=0.0))


def _sample(request_id: str, final: bool = False) -> dict:
    return {"request-id": request_id, "valid": final, "final": final, "generated-frame": {"scenarioId": request_id}, "evaluation-data": {"best_fitness": [0.2]}}


async def test_one_broker_subscription_serves_every_observer_until_the_last_leaves(channel, broker):
    topic = instance_topic(WORKER_NODE, SCENE_POOL)
    first, second = Browser(channel), Browser(channel)
    first.socket.subscribe(topic)
    second.socket.subscribe(topic)
    (subscribed,) = await first.messages(1)
    await second.messages(1)
    assert broker.started == 1 and broker.calls == [("subscribe", SCENE_PREFIX + GENERATED_SCENE_TOPIC)]
    assert subscribed["snapshot"] == {"worker_node_id": WORKER_NODE, "instance": SCENE_POOL, "kind": "scene_generation", "state": "online", "job_id": None, "attempt": None, "observed_speed": None}

    await first.leave()
    assert broker.filters == [SCENE_PREFIX + GENERATED_SCENE_TOPIC]
    await second.leave()
    assert broker.calls[-1] == ("unsubscribe", SCENE_PREFIX + GENERATED_SCENE_TOPIC) and broker.filters == []

    third = Browser(channel)
    third.socket.subscribe(topic)
    await third.messages(1)
    assert broker.started == 1 and broker.filters == [SCENE_PREFIX + GENERATED_SCENE_TOPIC]  # the connection is kept
    await third.leave()
    await channel.close()
    assert broker.stopped == 1


async def test_pool_previews_reach_their_observers_translated(channel, broker):
    scene_topic, trajectory_topic = instance_topic(WORKER_NODE, SCENE_POOL), instance_topic(WORKER_NODE, TRAJECTORY_POOL)
    browser = Browser(channel)
    browser.socket.subscribe(scene_topic)
    browser.socket.subscribe(trajectory_topic)
    await browser.messages(2)
    trajectory_prefix = "scenegems/service/virtual/real/trajectory-generation-subsystem-1/"
    assert sorted(broker.filters) == sorted([SCENE_PREFIX + GENERATED_SCENE_TOPIC, trajectory_prefix + TRAJECTORY_PREVIEW_TOPIC, trajectory_prefix + TRAJECTORY_RESULT_TOPIC])

    broker.publish_from_its_thread(SCENE_PREFIX + GENERATED_SCENE_TOPIC, _sample("r1"))
    broker.publish_from_its_thread(trajectory_prefix + TRAJECTORY_PREVIEW_TOPIC, {"request-id": "t1", "trajectory-data": {"trajectories": [1]}})
    broker.publish_from_its_thread(trajectory_prefix + TRAJECTORY_RESULT_TOPIC, {"request-id": "t1", "trajectory-data": {"trajectories": [2]}, "valid": True, "complete": True, "error-message": None})
    broker.publish_from_its_thread("scenegems/service/virtual/real/scene-generation-subsystem-2/" + GENERATED_SCENE_TOPIC, _sample("unobserved"))  # another worker node's pool
    await settle()
    sample, preview, result = browser.socket.take()
    assert sample["topic"] == scene_topic and sample["data"] == {
        "kind": "scene_sample",
        "request_id": "r1",
        "valid": False,
        "final": False,
        "scene": {"scenarioId": "r1"},
        "evaluation_data": {"best_fitness": [0.2]},
    }
    assert preview["topic"] == trajectory_topic and preview["data"]["trajectories"] == {"trajectories": [1]} and preview["data"]["final"] is False
    assert result["data"]["final"] is True and result["data"]["complete"] is True and result["data"]["valid"] is True
    await browser.leave()


async def test_previews_are_rate_limited_but_a_final_sample_is_not(plane, broker, monotonic):
    channel = create_live_channel(plane, broker=lambda: broker, settings=LiveSettings(preview_interval_s=0.25))
    channel._clock = monotonic
    topic = instance_topic(WORKER_NODE, SCENE_POOL)
    browser = Browser(channel)
    browser.socket.subscribe(topic)
    await browser.messages(1)
    hub = channel.producers.hub
    for index in range(3):
        hub.deliver(SCENE_PREFIX + GENERATED_SCENE_TOPIC, json.dumps(_sample(f"r{index}")).encode())
    hub.deliver(SCENE_PREFIX + GENERATED_SCENE_TOPIC, json.dumps(_sample("done", final=True)).encode())
    await settle()
    assert [(message["data"]["request_id"], message["data"]["final"]) for message in browser.socket.take()] == [("r0", False), ("done", True)]
    monotonic.advance(0.25)
    channel.flush_rated(topic)
    await settle()
    assert [message["data"]["request_id"] for message in browser.socket.take()] == ["r2"]
    await browser.leave()
    await channel.close()


async def test_without_a_broker_pools_cannot_be_observed(plane):
    channel = create_live_channel(plane)
    browser = Browser(channel)
    browser.socket.subscribe(instance_topic(WORKER_NODE, SCENE_POOL))
    browser.socket.subscribe(instance_topic("no-such-worker-node", SCENE_POOL))
    no_broker, _ = await browser.messages(2)
    assert no_broker["type"] == "error" and "broker account is not configured" in no_broker["message"]
    assert channel.topics() == set()
    await browser.leave()


async def test_an_unknown_worker_node_is_an_error(channel):
    browser = Browser(channel)
    browser.socket.subscribe(instance_topic("no-such-worker-node", SCENE_POOL))
    (error,) = await browser.messages(1)
    assert error["type"] == "error" and "no worker node no-such-worker-node" in error["message"]
    await browser.leave()


async def test_a_job_instance_gets_status_and_simulation_frames(channel, plane, broker):
    job = plane.jobs.submit(JobSubmission(job_type=JobType.SIMULATION, payload=valid_payload(JobType.SIMULATION))).job
    lease = plane.jobs.claim_next(WORKER_NODE, 10.0)
    assert lease.job.job_id == job.job_id and lease.job.attempt == 1
    observations = []
    hub = channel.producers.hub
    hub.on_job_observation = lambda *arguments: observations.append(arguments)
    topic = instance_topic(WORKER_NODE, job_instance(job.job_id, 1))
    browser = Browser(channel)
    browser.socket.subscribe(topic)
    (subscribed,) = await browser.messages(1)
    assert subscribed["snapshot"]["kind"] == "simulation" and subscribed["snapshot"]["state"] == "leased"
    assert observations == [(WORKER_NODE, job.job_id, 1, True)] and broker.started == 0  # jobs need no broker

    plane.activity.status(JobStatus(lease_id=lease.lease_id, job_id=job.job_id, progress=0.25, message="step 25"))
    hub.publish_simulation_frames(WORKER_NODE, job.job_id, 1, [{"timestamp": 0}, {"timestamp": 1}])
    hub.publish_simulation_frames(WORKER_NODE, job.job_id, 1, [{"timestamp": 2}])
    hub.publish_simulation_frames(WORKER_NODE, "another-job", 1, [{"timestamp": 0}])
    await settle()
    status, frames = browser.socket.take()  # both batches waited unsent together, so they were joined
    assert status["data"] == {"kind": "status", "state": "leased", "message": "step 25", "progress": 0.25, "observed_speed": 10.0, "detail": None}
    assert frames["data"] == {"kind": "simulation_frames", "job_id": job.job_id, "frames": [{"timestamp": 0}, {"timestamp": 1}, {"timestamp": 2}]}
    hub.publish_simulation_frames(WORKER_NODE, job.job_id, 1, [{"timestamp": 3}])
    await settle()
    (later,) = browser.socket.take()
    assert later["data"]["frames"] == [{"timestamp": 3}] and later["seq"] == frames["seq"] + 1

    await browser.leave()
    assert observations[-1] == (WORKER_NODE, job.job_id, 1, False) and not hub.observes_job(job.job_id)


async def test_frames_reach_a_job_topic_that_names_another_worker_node_than_the_lease_holder(broker):
    clock = ManualClock()
    worker_nodes = InMemoryWorkerNodeStore(clock)
    plane = ControlPlane("lab-control-node", worker_nodes, InMemoryJobStore(worker_nodes, clock), ExpectedFingerprints.fixed(EXPECTED), clock=clock)
    for worker_node in (WORKER_NODE, "lab-2"):
        worker_nodes.register(make_hello(worker_node, slots={JobType.SIMULATION: 1}))
    channel = create_live_channel(plane, broker=lambda: broker, settings=LiveSettings(preview_interval_s=0.0, frames_interval_s=0.0))
    job = plane.jobs.submit(JobSubmission(job_type=JobType.SIMULATION, payload=valid_payload(JobType.SIMULATION))).job
    assert plane.jobs.claim_next(WORKER_NODE, 10.0).job.job_id == job.job_id
    hub = channel.producers.hub
    hub.on_job_observation = lambda *arguments: None
    elsewhere, later_attempt = Browser(channel), Browser(channel)
    elsewhere.socket.subscribe(instance_topic("lab-2", job_instance(job.job_id, 1)))  # say, the holder of an earlier lease
    later_attempt.socket.subscribe(instance_topic(WORKER_NODE, job_instance(job.job_id, 2)))
    await elsewhere.messages(1)
    await later_attempt.messages(1)

    hub.publish_simulation_frames(WORKER_NODE, job.job_id, 1, [{"timestamp": 0}])
    await settle()
    frames = [message["data"]["frames"] for message in elsewhere.socket.take() if message.get("data", {}).get("kind") == "simulation_frames"]
    assert frames == [[{"timestamp": 0}]]
    assert [message for message in later_attempt.socket.take() if message.get("data", {}).get("kind") == "simulation_frames"] == []  # another attempt's run
    await elsewhere.leave()
    await later_attempt.leave()


async def test_an_observed_job_instance_hears_state_changes(channel, plane):
    job = plane.jobs.submit(JobSubmission(job_type=JobType.SCENE_GENERATION, payload=valid_payload(JobType.SCENE_GENERATION))).job
    lease = plane.jobs.claim_next(WORKER_NODE, 10.0)
    topic = instance_topic(WORKER_NODE, job_instance(job.job_id, 1))
    browser = Browser(channel)
    browser.socket.subscribe(topic)
    await browser.messages(1)
    plane.jobs.accept(lease.lease_id, 30.0)
    plane.activity.changed(job.job_id)
    await channel.producers.idle()
    plane.activity.changed(job.job_id)  # nothing new: no second status
    await channel.producers.idle()
    await settle()
    (update,) = browser.socket.take()
    assert update["data"] == {"kind": "status", "state": "running", "message": "", "progress": None, "observed_speed": 10.0, "detail": None}
    await browser.leave()


def test_pool_messages_translate():
    sample = translate_pool_message(GENERATED_SCENE_TOPIC, _sample("r1", final=True))
    assert sample == SceneSample(request_id="r1", valid=True, final=True, scene={"scenarioId": "r1"}, evaluation_data={"best_fitness": [0.2]})
    preview = translate_pool_message(TRAJECTORY_PREVIEW_TOPIC, {"request-id": "t", "trajectory-data": {"a": 1}})
    assert preview == TrajectoryPreview(request_id="t", trajectories={"a": 1})
    result = translate_pool_message(TRAJECTORY_RESULT_TOPIC, {"request-id": "t", "trajectory-data": None, "valid": False, "complete": False, "error-message": "no path"})
    assert result == TrajectoryPreview(request_id="t", final=True, valid=False, complete=False, error_message="no path")
    assert translate_pool_message("heartbeat", {"type": "HeartBeat"}) is None
    assert translate_pool_message(GENERATED_SCENE_TOPIC, {"request-id": "r", "evaluation-data": "not a dict"}) is None
