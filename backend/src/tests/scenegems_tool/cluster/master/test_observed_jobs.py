"""Live simulations on the master: browsers on the live channel, a node on a recording control socket, the real control plane.

Observe goes to the node holding the job when the first browser observes its instance, with
the chosen speed, again on a speed change, on a reconnect and on a late accept, and off when
the last browser leaves; the node's ObservationFrames reach the browsers.
"""

import pytest

from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.live.live_channel import LiveSettings
from scenegems_tool.cluster.master.live.topics import create_live_channel
from scenegems_tool.cluster.master.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.protocol.jobs import JobSubmission, JobType
from scenegems_tool.cluster.protocol.live import instance_topic, job_instance
from scenegems_tool.cluster.protocol.messages import LeaseAccept, LeaseOffer, ObservationFrames, Observe
from tests.scenegems_tool.cluster.master.conftest import EXPECTED
from tests.scenegems_tool.cluster.master.fake_socket import RecordingSocket
from tests.scenegems_tool.cluster.master.fake_stores import InMemoryJobStore, InMemoryNodeStore
from tests.scenegems_tool.cluster.master.live.conftest import Browser, settle
from tests.scenegems_tool.cluster.payloads import valid_payload
from tests.scenegems_tool.persistence.stores.builders import ManualClock, make_hello

pytestmark = pytest.mark.anyio

NODE = "lab-1"
KINEMATIC = JobType.SIMULATION


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def plane() -> ControlPlane:
    clock = ManualClock()
    nodes = InMemoryNodeStore(clock)
    return ControlPlane("lab-master", nodes, InMemoryJobStore(nodes, clock), ExpectedFingerprints.fixed(EXPECTED), clock=clock)


@pytest.fixture
def channel(plane):
    return create_live_channel(plane, settings=LiveSettings(frames_interval_s=0.0))


async def connect(plane: ControlPlane, running_lease_ids=()):
    socket = RecordingSocket()
    hello = make_hello(NODE, slots={KINEMATIC: 1}, fingerprints=dict(EXPECTED)).model_copy(update={"running_lease_ids": list(running_lease_ids)})
    return await plane.open_session(hello, socket), socket


async def offered_job(plane: ControlPlane, socket: RecordingSocket):
    """A kinematic job offered to the node (attempt 1); returns it and its lease id."""
    job = plane.jobs.submit(JobSubmission(job_type=KINEMATIC, payload=valid_payload(KINEMATIC))).job
    assert await plane.scheduler.run_once() == 1
    (offer,) = socket.of_type(LeaseOffer)
    return job, offer.lease_id


async def running_job(plane: ControlPlane, session, socket: RecordingSocket):
    job, lease_id = await offered_job(plane, socket)
    await plane.handle_frame(session, LeaseAccept(lease_id=lease_id))
    return job, lease_id


async def observes(socket: RecordingSocket, plane: ControlPlane):
    await plane.observations.settle()
    await settle()
    return [(frame.job_id, frame.attempt, frame.active, frame.speed) for frame in socket.of_type(Observe)]


def subscribe(browser: Browser, topic: str, speed=None) -> None:
    message = {"version": 1, "type": "subscribe", "topic": topic}
    if speed is not None:
        message["options"] = {"speed": speed}
    browser.socket.client_sends(message)


def configure(browser: Browser, topic: str, speed: float) -> None:
    browser.socket.client_sends({"version": 1, "type": "configure", "topic": topic, "options": {"speed": speed}})


async def test_the_first_observer_turns_observation_on_at_its_speed_and_the_last_turns_it_off(plane, channel):
    session, socket = await connect(plane)
    job, _ = await running_job(plane, session, socket)
    topic = instance_topic(NODE, job_instance(job.job_id, 1))
    first, second = Browser(channel), Browser(channel)

    subscribe(first, topic, speed=25)
    (subscribed,) = await first.messages(1)
    assert subscribed["snapshot"]["observed_speed"] == 25.0
    assert await observes(socket, plane) == [(job.job_id, 1, True, 25.0)]

    subscribe(second, topic)  # no options: the job's speed stays
    (subscribed,) = await second.messages(1)
    assert subscribed["snapshot"]["observed_speed"] == 25.0 and len(await observes(socket, plane)) == 1

    configure(second, topic, 50)  # the latest request wins for every observer
    await settle()
    assert (await observes(socket, plane))[-1] == (job.job_id, 1, True, 50.0)
    for browser in (first, second):  # every observer hears the new speed in a status of the job instance
        (update,) = await browser.messages(1)
        assert update["type"] == "update" and update["data"] == {"kind": "status", "state": "running", "message": "", "progress": None, "observed_speed": 50.0}
    configure(first, topic, 50)  # the same speed again changes nothing
    await settle()
    assert len(await observes(socket, plane)) == 2 and first.socket.take() == [] and second.socket.take() == []

    await first.leave()
    assert len(await observes(socket, plane)) == 2  # one observer is left
    await second.leave()
    assert (await observes(socket, plane))[-1] == (job.job_id, 1, False, 10.0)  # the speed went with the last observer

    third = Browser(channel)
    subscribe(third, topic)
    (subscribed,) = await third.messages(1)
    assert subscribed["snapshot"]["observed_speed"] == 10.0
    assert (await observes(socket, plane))[-1] == (job.job_id, 1, True, 10.0)
    await third.leave()


async def test_the_nodes_frames_reach_the_observers(plane, channel):
    session, socket = await connect(plane)
    job, lease_id = await running_job(plane, session, socket)
    topic = instance_topic(NODE, job_instance(job.job_id, 1))
    browser = Browser(channel)
    subscribe(browser, topic)
    await browser.messages(1)

    frames = [{"scenarioId": job.job_id, "timestamp": 0}, {"scenarioId": job.job_id, "timestamp": 1}]
    await plane.handle_frame(session, ObservationFrames(lease_id=lease_id, job_id=job.job_id, attempt=1, seq=1, frames=frames))
    (update,) = await browser.messages(1)
    assert update["data"] == {"kind": "simulation_frames", "job_id": job.job_id, "frames": frames}

    await plane.handle_frame(session, ObservationFrames(lease_id="not-its-lease", job_id=job.job_id, attempt=1, seq=2, frames=frames))
    await settle()
    assert browser.socket.take() == []  # a lease the node does not hold
    await browser.leave()


async def test_frames_nobody_observes_are_answered_with_observe_off(plane, channel):
    session, socket = await connect(plane)
    job, lease_id = await running_job(plane, session, socket)
    await plane.handle_frame(session, ObservationFrames(lease_id=lease_id, job_id=job.job_id, attempt=1, seq=7, frames=[{"timestamp": 0}]))
    assert await observes(socket, plane) == [(job.job_id, 1, False, 10.0)]


async def test_a_reconnecting_node_is_told_again(plane, channel):
    session, socket = await connect(plane)
    job, lease_id = await running_job(plane, session, socket)
    browser = Browser(channel)
    subscribe(browser, instance_topic(NODE, job_instance(job.job_id, 1)), speed=40)
    await browser.messages(1)
    assert await observes(socket, plane) == [(job.job_id, 1, True, 40.0)]

    await plane.close_session(session)
    session, socket = await connect(plane, running_lease_ids=[lease_id])  # the job kept running through the reconnect
    assert await observes(socket, plane) == [(job.job_id, 1, True, 40.0)]
    await browser.leave()
    assert (await observes(socket, plane))[-1][2] is False


async def test_an_observation_that_began_before_the_accept_is_sent_with_it(plane, channel):
    session, socket = await connect(plane)
    job, lease_id = await offered_job(plane, socket)
    browser = Browser(channel)
    subscribe(browser, instance_topic(NODE, job_instance(job.job_id, 1)), speed=5)
    await browser.messages(1)
    assert await observes(socket, plane) == [(job.job_id, 1, True, 5.0)]  # sent to the node the job is offered to; it has no lease yet
    await plane.handle_frame(session, LeaseAccept(lease_id=lease_id))
    assert await observes(socket, plane) == [(job.job_id, 1, True, 5.0)] * 2
    await browser.leave()


async def test_two_instance_topics_of_one_attempt_count_as_one_observation(plane, channel):
    session, socket = await connect(plane)
    job, _ = await running_job(plane, session, socket)
    instance = job_instance(job.job_id, 1)
    first, second = Browser(channel), Browser(channel)
    subscribe(first, instance_topic(NODE, instance))
    subscribe(second, instance_topic("another-node", instance))  # the browser names the node; the frame goes to the job's
    await first.messages(1)
    await second.messages(1)
    assert len(await observes(socket, plane)) == 1
    await first.leave()
    assert len(await observes(socket, plane)) == 1
    await second.leave()
    assert (await observes(socket, plane))[-1][2] is False


async def test_options_belong_to_job_instance_topics(plane, channel):
    browser = Browser(channel)
    subscribe(browser, "nodes", speed=20)
    (error,) = await browser.messages(1)
    assert error["type"] == "error" and error["topic"] == "nodes" and "take no options" in error["message"]
    subscribe(browser, instance_topic(NODE, "scene_generation-0"), speed=20)
    (error,) = await browser.messages(1)
    assert error["type"] == "error" and "only job instance topics take options" in error["message"]
    configure(browser, "instance:lab-1/job-x-1", 20)
    (error,) = await browser.messages(1)
    assert error == {"version": 1, "type": "error", "message": "not subscribed", "topic": "instance:lab-1/job-x-1"}
    assert channel.topics() == set()
    await browser.leave()
