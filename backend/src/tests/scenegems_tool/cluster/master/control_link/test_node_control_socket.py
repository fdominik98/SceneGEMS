"""The node control WebSocket with scripted nodes: handshake, leases, results and refusals."""

import json
from datetime import timedelta

import pytest

from scenegems_tool.cluster.master.control_link.node_control_socket import CLOSE_PROTOCOL_ERROR
from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobState, JobSubmission
from scenegems_tool.cluster.protocol.messages import Cancel, Heartbeat, LeaseOffer, LeaseRenewed, ProtocolError, ProtocolErrorCode, Welcome
from scenegems_tool.cluster.protocol.version import PROTOCOL_VERSION
from scenegems_tool.persistence.schema import NodeStatus
from tests.scenegems_tool.cluster.master.conftest import EXPECTED_BY_REPOSITORY, SCENE
from tests.scenegems_tool.cluster.payloads import valid_payload
from tests.scenegems_tool.persistence.stores.builders import make_resources


def _submit(on_loop, plane, **fields):
    job_type = fields.pop("job_type", SCENE)
    fields.setdefault("payload", valid_payload(job_type))
    return on_loop(plane.submit, JobSubmission(job_type=job_type, **fields)).job


def test_hello_is_answered_with_welcome_and_the_node_is_online(make_node, plane, stores):
    node = make_node("lab 1")
    welcome = node.connect()
    assert welcome == Welcome(master_id="lab-master", heartbeat_interval_s=5.0, lease_timeout_s=30.0)
    assert stores.nodes.get(node.node_id).status == NodeStatus.ONLINE
    assert [session.node_id for session in plane.registry.connected()] == [node.node_id]


def test_offer_accept_renew_result(make_node, plane, stores, on_loop, schedule, clock):
    node = make_node("lab 1")
    node.connect()
    job = _submit(on_loop, plane, payload=valid_payload(SCENE, seed=1))
    assert schedule() == 1
    offer = node.expect(LeaseOffer)
    assert offer.job.job_id == job.job_id and offer.job.attempt == 1
    assert offer.job.requirements.fingerprints == {"scenegems-scene-generation-subsystem": "fp-scene"}
    assert offer.expires_at == clock.now + timedelta(seconds=10)

    renewed = node.accept(offer)
    assert renewed.lease_id == offer.lease_id and stores.jobs.get(job.job_id).state == JobState.RUNNING
    clock.advance(10)
    assert node.renew(offer.lease_id) == LeaseRenewed(lease_id=offer.lease_id, expires_at=clock.now + timedelta(seconds=30))

    node.succeed(offer, {"valid": True})
    stored = stores.jobs.get(job.job_id)
    assert stored.state == JobState.SUCCEEDED and stored.result == {"valid": True}


def test_a_node_connects_without_any_credential_and_the_hello_names_it(make_node, stores):
    node = make_node("lab 1")
    node.connect()  # no header, no pairing: the master trusts the VPN
    assert stores.nodes.get(node.node_id).node_id == node.node_id


@pytest.mark.parametrize("node_id", ["Lab 1", "lab/1", "lab+", "#", "-lab", ""])
def test_a_hello_with_an_unusable_node_id_is_refused(make_node, stores, node_id):
    node = make_node("lab 1")
    node.hello_frame = node.hello_frame.model_copy(update={"node_id": node_id})
    node.open()
    node.send(node.hello_frame)  # the id becomes a topic level and part of Docker names
    error = node.expect(ProtocolError)
    assert error.code == ProtocolErrorCode.MALFORMED_FRAME and "node id" in error.message
    assert node.expect_close() == CLOSE_PROTOCOL_ERROR
    assert stores.nodes.get(node_id) is None


def test_version_mismatch_is_refused_with_a_clear_error(make_node, stores):
    node = make_node("lab 1")
    node.open()
    frame = json.loads(node.hello_frame.model_dump_json())
    frame["protocol_version"] = PROTOCOL_VERSION + 1
    node.send_text(json.dumps(frame))
    error = node.expect(ProtocolError)
    assert error.code == ProtocolErrorCode.VERSION_MISMATCH and "same SceneGEMS revision" in error.message
    assert node.expect_close() == CLOSE_PROTOCOL_ERROR
    assert stores.nodes.get(node.node_id) is None


def test_first_frame_must_be_hello(make_node):
    node = make_node("lab 1")
    node.open()
    node.send(Heartbeat(resources=make_resources()))
    assert node.expect(ProtocolError).code == ProtocolErrorCode.MALFORMED_FRAME
    assert node.expect_close() == CLOSE_PROTOCOL_ERROR


def test_malformed_frame_after_hello_keeps_the_connection(make_node, plane, on_loop, schedule):
    node = make_node("lab 1")
    node.connect()
    node.send_text("not json")
    assert node.expect(ProtocolError).code == ProtocolErrorCode.MALFORMED_FRAME
    node.send_text(json.dumps({"type": "lease_renew", "protocol_version": PROTOCOL_VERSION}))
    assert node.expect(ProtocolError).code == ProtocolErrorCode.MALFORMED_FRAME
    _submit(on_loop, plane)
    schedule()
    node.expect(LeaseOffer)


def test_version_change_after_hello_closes_the_connection(make_node):
    node = make_node("lab 1")
    node.connect()
    node.send_text(json.dumps({"type": "heartbeat", "protocol_version": PROTOCOL_VERSION + 1}))
    assert node.expect(ProtocolError).code == ProtocolErrorCode.VERSION_MISMATCH
    assert node.expect_close() == CLOSE_PROTOCOL_ERROR


def test_renewal_of_an_expired_lease_is_cancelled(make_node, plane, stores, on_loop, schedule, clock):
    node = make_node("lab 1")
    node.connect()
    job = _submit(on_loop, plane)
    schedule()
    offer = node.expect(LeaseOffer)
    node.accept(offer)
    clock.advance(31)
    cancel = node.renew(offer.lease_id)
    assert isinstance(cancel, Cancel) and cancel.lease_id == offer.lease_id and cancel.job_id == job.job_id
    # the late result does not count
    node.send(node.result(offer, JobOutcome.SUCCEEDED))
    assert node.expect(ProtocolError).code == ProtocolErrorCode.UNKNOWN_LEASE
    on_loop(plane.leases.sweep_expired)
    assert stores.jobs.get(job.job_id).state == JobState.QUEUED and stores.jobs.get(job.job_id).failed_attempts == 1


def test_a_node_cannot_act_on_another_nodes_lease(make_node, plane, stores, on_loop, schedule):
    owner, other = make_node("lab 1", slots={SCENE: 1}), make_node("lab 2", slots={SCENE: 1})
    owner.connect()
    job = _submit(on_loop, plane)
    schedule()
    offer = owner.expect(LeaseOffer)
    other.connect()
    other.send(other.result(offer, JobOutcome.SUCCEEDED, {"forged": True}))
    assert other.expect(ProtocolError).code == ProtocolErrorCode.UNKNOWN_LEASE
    cancel = other.renew(offer.lease_id)
    assert isinstance(cancel, Cancel) and cancel.lease_id == offer.lease_id
    assert stores.jobs.get(job.job_id).state == JobState.LEASED
    owner.accept(offer)


def test_expired_lease_of_a_connected_node_is_cancelled_and_requeued(make_node, plane, stores, on_loop, schedule, clock):
    node = make_node("lab 1")
    node.connect()
    job = _submit(on_loop, plane)
    schedule()
    offer = node.expect(LeaseOffer)
    node.accept(offer)
    clock.advance(30)
    expired = on_loop(plane.leases.sweep_expired)
    assert [lease.lease_id for lease in expired] == [offer.lease_id]
    cancel = node.expect(Cancel)
    assert cancel.lease_id == offer.lease_id and cancel.job_id == job.job_id
    schedule()
    again = node.expect(LeaseOffer)
    assert again.job.job_id == job.job_id and again.job.attempt == 2


def test_the_expected_fingerprints_are_in_every_offer(make_node, plane, on_loop, schedule):
    node = make_node("lab 1", slots={SCENE: 1})
    node.connect()
    _submit(on_loop, plane)
    schedule()
    assert set(node.expect(LeaseOffer).job.requirements.fingerprints.items()) <= set(EXPECTED_BY_REPOSITORY.items())
