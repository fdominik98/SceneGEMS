import json

import pytest

from scenegems_tool.cluster.protocol.codec import MalformedFrame, decode_control_node_message, decode_worker_node_message, encode
from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobType
from scenegems_tool.cluster.protocol.messages import (
    Cancel,
    Drain,
    Heartbeat,
    Hello,
    JobResult,
    JobStatus,
    LeaseAccept,
    LeaseOffer,
    LeaseReject,
    LeaseRelease,
    LeaseRenew,
    LeaseRenewed,
    LogLine,
    LogLines,
    LogStream,
    ObservationFrames,
    Observe,
    ProtocolError,
    ProtocolErrorCode,
    Welcome,
)
from scenegems_tool.cluster.protocol.version import PROTOCOL_VERSION, ProtocolVersionMismatch
from scenegems_tool.cluster.protocol.worker_node_description import SlotOffer


@pytest.fixture
def worker_node_frames(resources, instant):
    return [
        Hello(
            worker_node_id="n1",
            worker_node_name="lab-1",
            software_revision="4ac7ef2",
            slots=[SlotOffer(job_type=JobType.SIMULATION, slots=4), SlotOffer(job_type=JobType.SCENE_GENERATION, slots=1)],
            components=["asv_system/replay", "control_layer/none", "simulation_layer/kinematic", "scene_generation"],
            labels={"site": "lab"},
            resources=resources,
            fingerprints={"scenegems-simulation": "abc123"},
            running_lease_ids=["l0"],
        ),
        Heartbeat(resources=resources, slots_in_use={JobType.SIMULATION: 2}, running_lease_ids=["l1", "l2"]),
        LeaseAccept(lease_id="l1"),
        LeaseReject(lease_id="l1", reason="no free slot"),
        LeaseRenew(lease_id="l1"),
        LeaseRelease(lease_id="l1", reason="draining"),
        JobStatus(lease_id="l1", job_id="j1", progress=0.5, message="step 150 of 300"),
        JobResult(lease_id="l1", job_id="j1", idempotency_key="j1/1", outcome=JobOutcome.SUCCEEDED, result={"state_digest": "ff"}),
        LogLines(lease_id="l1", job_id="j1", lines=[LogLine(timestamp=instant, stream=LogStream.STDOUT, source="simulation.n1.0", text="ready")]),
        ObservationFrames(lease_id="l1", job_id="j1", attempt=1, seq=3, frames=[{"scenarioId": "j1", "timestamp": 12, "statesByActorId": {"0": {"x": 1.5}}}]),
    ]


@pytest.fixture
def control_node_frames(job_spec, instant):
    return [
        Welcome(control_node_id="m1", instance_number=1, heartbeat_interval_s=5.0, lease_timeout_s=30.0),
        LeaseOffer(lease_id="l1", job=job_spec, expires_at=instant),
        LeaseRenewed(lease_id="l1", expires_at=instant),
        Drain(reason="maintenance"),
        Cancel(lease_id="l1", job_id="j1", reason="cancelled by user"),
        Observe(job_id="j1", attempt=1, active=True, speed=25.0),
        ProtocolError(code=ProtocolErrorCode.UNKNOWN_LEASE, message="lease l9 is not yours"),
    ]


def test_every_worker_node_frame_round_trips(worker_node_frames):
    for frame in worker_node_frames:
        assert decode_worker_node_message(encode(frame)) == frame


def test_every_control_node_frame_round_trips(control_node_frames):
    for frame in control_node_frames:
        assert decode_control_node_message(encode(frame)) == frame


def test_bytes_are_accepted():
    assert decode_worker_node_message(encode(LeaseAccept(lease_id="l1")).encode()) == LeaseAccept(lease_id="l1")


def test_a_control_node_frame_is_not_a_worker_node_frame():
    with pytest.raises(MalformedFrame, match="drain"):
        decode_worker_node_message(encode(Drain(reason="maintenance")))


def test_version_is_checked_before_the_body():
    # a frame from another revision may have any shape: the error must name the version
    frame = {"protocol_version": PROTOCOL_VERSION + 1, "type": "hello", "renamed_field": 1}
    with pytest.raises(ProtocolVersionMismatch):
        decode_worker_node_message(json.dumps(frame))


def test_frame_without_version_is_rejected():
    with pytest.raises(ProtocolVersionMismatch):
        decode_worker_node_message(json.dumps({"type": "lease_accept", "lease_id": "l1"}))


@pytest.mark.parametrize("text", ["not json", "[1, 2]", "null"])
def test_non_object_frames_are_malformed(text):
    with pytest.raises(MalformedFrame):
        decode_worker_node_message(text)


def test_unknown_type_is_malformed():
    with pytest.raises(MalformedFrame, match="unknown"):
        decode_worker_node_message(json.dumps({"protocol_version": PROTOCOL_VERSION, "type": "unknown"}))


def test_missing_field_names_the_frame_type():
    with pytest.raises(MalformedFrame, match="lease_accept"):
        decode_worker_node_message(json.dumps({"protocol_version": PROTOCOL_VERSION, "type": "lease_accept"}))
