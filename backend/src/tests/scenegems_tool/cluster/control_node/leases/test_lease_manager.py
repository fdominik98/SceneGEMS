"""Lease timing with a manual clock: offers, running leases, renewals, expiry and the retry limit."""

import anyio
import pytest

from scenegems_tool.cluster.control_node.control_plane import ControlPlane
from scenegems_tool.cluster.control_node.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.protocol.jobs import JobState, JobSubmission, JobType
from scenegems_tool.cluster.protocol.messages import Cancel, LeaseAccept, LeaseOffer, LeaseRenew, LeaseRenewed
from tests.scenegems_tool.cluster.control_node.conftest import EXPECTED
from tests.scenegems_tool.cluster.control_node.fake_socket import RecordingSocket
from tests.scenegems_tool.cluster.control_node.fake_stores import InMemoryJobStore, InMemoryWorkerNodeStore
from tests.scenegems_tool.cluster.payloads import valid_payload
from tests.scenegems_tool.persistence.stores.builders import ManualClock, make_hello


class Harness:
    """A control plane on in-memory stores with one connected worker node behind a recording socket."""

    def __init__(self):
        self.clock = ManualClock()
        worker_nodes = InMemoryWorkerNodeStore(self.clock)
        self.jobs = InMemoryJobStore(worker_nodes, self.clock)
        self.plane = ControlPlane("lab-control-node", worker_nodes, self.jobs, ExpectedFingerprints.fixed(EXPECTED), clock=self.clock)
        self.socket = RecordingSocket()
        self.session = anyio.run(self.plane.open_session, make_hello("worker-node-a", slots={JobType.SCENE_GENERATION: 2}, fingerprints=dict(EXPECTED)), self.socket)

    def run(self, function, *arguments):
        return anyio.run(function, *arguments)

    def offer(self, **fields) -> LeaseOffer:
        fields.setdefault("payload", valid_payload(JobType.SCENE_GENERATION))
        job = self.run(self.plane.submit, JobSubmission(job_type=JobType.SCENE_GENERATION, **fields)).job
        assert self.run(self.plane.scheduler.run_once) == 1
        offer = self.socket.of_type(LeaseOffer)[-1]
        assert offer.job.job_id == job.job_id
        return offer

    def accept(self, offer: LeaseOffer) -> LeaseRenewed:
        self.run(self.plane.leases.accept, self.session, LeaseAccept(lease_id=offer.lease_id))
        return self.socket.frames[-1]

    def renew(self, offer: LeaseOffer):
        self.run(self.plane.leases.renew, self.session, LeaseRenew(lease_id=offer.lease_id))
        return self.socket.frames[-1]

    def sweep(self):
        return self.run(self.plane.leases.sweep_expired)

    def state(self, offer: LeaseOffer):
        return self.jobs.get(offer.job.job_id)


@pytest.fixture
def harness() -> Harness:
    return Harness()


def test_an_offer_holds_ten_seconds(harness):
    offer = harness.offer()
    assert (offer.expires_at - harness.clock.now).total_seconds() == 10
    harness.clock.advance(9.9)
    assert harness.sweep() == []
    harness.clock.advance(0.1)
    assert [lease.lease_id for lease in harness.sweep()] == [offer.lease_id]
    assert harness.state(offer).state == JobState.QUEUED and harness.state(offer).failed_attempts == 1


def test_accepting_starts_a_thirty_second_lease(harness):
    offer = harness.offer()
    harness.clock.advance(5)
    renewed = harness.accept(offer)
    assert isinstance(renewed, LeaseRenewed) and (renewed.expires_at - harness.clock.now).total_seconds() == 30
    harness.clock.advance(29.9)
    assert harness.sweep() == []
    harness.clock.advance(0.1)
    assert len(harness.sweep()) == 1
    assert harness.socket.of_type(Cancel)[-1].lease_id == offer.lease_id


def test_renewing_every_ten_seconds_keeps_the_lease(harness):
    offer = harness.offer()
    harness.accept(offer)
    for _ in range(12):  # two minutes
        harness.clock.advance(10)
        renewed = harness.renew(offer)
        assert isinstance(renewed, LeaseRenewed)
        assert harness.sweep() == []
    assert harness.state(offer).state == JobState.RUNNING


def test_two_lost_renewals_are_survived_and_a_third_is_not(harness):
    offer = harness.offer()
    harness.accept(offer)
    harness.clock.advance(29)
    assert harness.sweep() == []
    assert isinstance(harness.renew(offer), LeaseRenewed)
    harness.clock.advance(30)
    assert len(harness.sweep()) == 1
    assert isinstance(harness.renew(offer), Cancel)


def test_expiries_use_up_the_attempts(harness):
    offer = harness.offer(max_attempts=2)
    harness.accept(offer)
    harness.clock.advance(30)
    harness.sweep()
    assert harness.run(harness.plane.scheduler.run_once) == 1
    again = harness.socket.of_type(LeaseOffer)[-1]
    assert again.job.attempt == 2
    harness.accept(again)
    harness.clock.advance(30)
    expired = harness.sweep()
    assert expired[0].job.state == JobState.FAILED
    assert harness.run(harness.plane.scheduler.run_once) == 0


def test_a_disconnect_withdraws_unaccepted_offers_without_an_attempt(harness):
    offer = harness.offer()
    harness.run(harness.plane.close_session, harness.session)
    state = harness.state(offer)
    assert state.state == JobState.QUEUED and state.failed_attempts == 0
    assert harness.plane.registry.connected() == []


def test_a_disconnect_keeps_accepted_leases_until_they_expire(harness):
    offer = harness.offer()
    harness.accept(offer)
    harness.run(harness.plane.close_session, harness.session)
    assert harness.state(offer).state == JobState.RUNNING
    harness.clock.advance(30)
    assert len(harness.sweep()) == 1
    assert len(harness.socket.of_type(Cancel)) == 0  # nobody to tell


def test_an_undeliverable_offer_goes_straight_back(harness):
    harness.socket.deliverable = False
    job = harness.run(harness.plane.submit, JobSubmission(job_type=JobType.SCENE_GENERATION, payload=valid_payload(JobType.SCENE_GENERATION))).job
    assert harness.run(harness.plane.scheduler.run_once) == 0
    state = harness.jobs.get(job.job_id)
    assert state.state == JobState.QUEUED and state.failed_attempts == 0 and harness.session.leases == {}
