"""The worker node daemon against a scripted control node over plain HTTP: hello, leases, reconnects and refusals.

Jobs are scripted (conftest.ScriptedJobs), so these tests need no Docker; the Docker test
in test_worker_node_daemon_docker.py runs real job containers.
"""

import json
import socket
import time

import pytest

from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobType
from scenegems_tool.cluster.protocol.messages import (
    Cancel,
    Drain,
    Heartbeat,
    Hello,
    JobResult,
    JobStatus,
    LeaseAccept,
    LeaseReject,
    LeaseRelease,
    LeaseRenew,
    LogLines,
    LogStream,
    ObservationFrames,
    Observe,
    ProtocolError,
    ProtocolErrorCode,
    Welcome,
)
from scenegems_tool.cluster.protocol.version import PROTOCOL_VERSION
from scenegems_tool.cluster.protocol.worker_node_description import SlotOffer
from scenegems_tool.cluster.worker_node.daemon.worker_node_daemon import DaemonStopped
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from tests.scenegems_tool.cluster.worker_node.daemon.conftest import FINGERPRINTS, make_job, make_offer, wait_for
from tests.scenegems_tool.cluster.worker_node.daemon.fake_control_node import FakeControlNode

QUIET_S = 0.6  # how long a frame that must not come is waited for


def connect(fake_control_node, start_daemon, configuration, **options):
    daemon = start_daemon(configuration, **options)
    connection = fake_control_node.wait_for_connection()
    hello = connection.expect(Hello)
    wait_for(daemon.daemon.connected.is_set)
    return daemon, connection, hello


def assert_no_frame(connection, kind, quiet_s: float = QUIET_S):
    time.sleep(quiet_s)
    assert not connection.received(kind), f"unexpected {kind.__name__}: {connection.received(kind)}"


# Start-up


def test_the_worker_node_says_hello_under_its_name_without_any_pairing(fake_control_node, worker_node_configuration, start_daemon):
    configuration = worker_node_configuration()
    daemon, connection, hello = connect(fake_control_node, start_daemon, configuration)

    assert connection.worker_node_id == hello.worker_node_id == "test-worker-node"  # the worker node id is the worker node name
    assert hello.worker_node_name == "test-worker-node"
    assert hello.software_revision == "test-revision"
    assert hello.slots == [SlotOffer(job_type=JobType.SCENE_GENERATION, slots=1), SlotOffer(job_type=JobType.SIMULATION, slots=2)]
    assert hello.components == ["asv_system/replay", "control_layer/none", "simulation_layer/kinematic", "scene_generation"]
    assert hello.labels == {"site": "lab"}
    assert hello.fingerprints == FINGERPRINTS
    assert hello.resources.cpus >= 1 and hello.resources.free_disk_mb > 0
    assert hello.running_lease_ids == []
    assert hello.machine is None
    assert not configuration.state_dir.exists() or not any(configuration.state_dir.glob("pairing*"))  # nothing is stored to pair


def test_hello_names_the_machine_from_the_configuration(fake_control_node, worker_node_configuration, start_daemon):
    _, _, hello = connect(fake_control_node, start_daemon, worker_node_configuration(SCENEGEMS_WORKER_NODE_MACHINE="lab-pc-3"))
    assert hello.machine == "lab-pc-3"


def test_heartbeats_follow_the_welcome_interval(fake_control_node, worker_node_configuration, start_daemon):
    _, connection, _ = connect(fake_control_node, start_daemon, worker_node_configuration())
    first = connection.expect(Heartbeat, skip=())
    second = connection.expect(Heartbeat, skip=())
    assert first.slots_in_use == {} and second.running_lease_ids == []


def test_the_worker_node_starts_before_its_control_node_and_connects_when_the_control_node_appears(worker_node_configuration, start_daemon):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    daemon = start_daemon(worker_node_configuration(SCENEGEMS_CONTROL_NODE_URL=f"http://127.0.0.1:{port}"))
    time.sleep(0.6)  # several refused connections, no control node yet
    assert daemon.thread.is_alive() and daemon.error is None and not daemon.daemon.connected.is_set()

    with FakeControlNode(port=port) as control_node:
        connection = control_node.wait_for_connection()
        assert connection.expect(Hello).worker_node_id == "test-worker-node"
        wait_for(daemon.daemon.connected.is_set)


def test_a_worker_node_connects_to_a_control_node_that_was_never_told_about_it(fake_control_node, worker_node_configuration, start_daemon):
    _, first, _ = connect(fake_control_node, start_daemon, worker_node_configuration(SCENEGEMS_WORKER_NODE_NAME="alpha"))
    _, second, _ = connect(fake_control_node, start_daemon, worker_node_configuration(SCENEGEMS_WORKER_NODE_NAME="beta"))
    assert (first.worker_node_id, second.worker_node_id) == ("alpha", "beta")


# Leases


def test_offer_accept_renew_and_result(fake_control_node, worker_node_configuration, start_daemon, jobs):
    fake_control_node.lease_timeout_s = 0.6  # renewals every 0.2 s
    _, connection, _ = connect(fake_control_node, start_daemon, worker_node_configuration())
    job = make_job("job-a", payload={"steps": 3})
    connection.send(make_offer("lease-a", job))
    assert connection.expect(LeaseAccept).lease_id == "lease-a"
    assert jobs.wait_started() == "job-a"

    renewal = connection.expect(LeaseRenew, skip=(Heartbeat, JobStatus, LogLines))
    assert renewal.lease_id == "lease-a"
    heartbeat = connection.expect(Heartbeat, skip=(LeaseRenew, JobStatus, LogLines))
    assert heartbeat.slots_in_use == {JobType.SIMULATION: 1} and heartbeat.running_lease_ids == ["lease-a"]
    time.sleep(1.0)  # longer than the lease timeout: renewals keep the lease
    jobs.finish("job-a", {"state_digest": "abc"})

    result = connection.expect(JobResult)
    assert result.lease_id == "lease-a" and result.job_id == "job-a" and result.idempotency_key == "job-a/key"
    assert result.outcome == JobOutcome.SUCCEEDED and result.result == {"state_digest": "abc"}
    statuses, logs = connection.received(JobStatus), connection.received(LogLines)
    assert statuses and statuses[0].message == "running job-a" and statuses[0].progress == 0.1
    texts = [line.text for frame in logs for line in frame.lines]
    assert "started job-a" in texts and any("accepted on worker node" in text for text in texts)
    assert any(line.stream == LogStream.DAEMON for frame in logs for line in frame.lines)
    # Reports of a lease always reach the control node before its result.
    result_index = connection.history.index(result)
    assert all(connection.history.index(frame) < result_index for frame in statuses + logs)


@pytest.mark.parametrize(
    "error, retryable",
    [(JobFailed("stack failed", retryable=True), True), (JobFailed("invalid payload", retryable=False), False), (RuntimeError("boom"), True)],
)
def test_a_failing_job_becomes_a_failed_result(fake_control_node, worker_node_configuration, start_daemon, jobs, error, retryable):
    _, connection, _ = connect(fake_control_node, start_daemon, worker_node_configuration())
    connection.send(make_offer("lease-f", make_job("job-f")))
    connection.expect(LeaseAccept)
    jobs.wait_started()
    jobs.fail("job-f", error)
    result = connection.expect(JobResult)
    assert result.outcome == JobOutcome.FAILED and result.retryable is retryable
    assert str(error) in result.error and result.result == {}


def test_offers_beyond_the_slots_are_rejected(fake_control_node, worker_node_configuration, start_daemon, jobs):
    _, connection, _ = connect(fake_control_node, start_daemon, worker_node_configuration())
    for lease_id in ("lease-1", "lease-2"):
        connection.send(make_offer(lease_id, make_job(f"job-{lease_id}")))
        connection.expect(LeaseAccept)
    connection.send(make_offer("lease-3", make_job("job-lease-3")))
    reject = connection.expect(LeaseReject)
    assert reject.lease_id == "lease-3" and "2 simulation slots are in use" in reject.reason

    connection.send(make_offer("lease-t", make_job("job-t", job_type=JobType.TRAJECTORY_GENERATION)))
    assert "offers no trajectory_generation slots" in connection.expect(LeaseReject).reason
    connection.send(make_offer("lease-s", make_job("job-s", job_type=JobType.SCENE_GENERATION)))
    assert connection.expect(LeaseAccept).lease_id == "lease-s"

    jobs.wait_started(), jobs.wait_started()
    jobs.finish("job-lease-1")
    connection.expect(JobResult)
    connection.send(make_offer("lease-4", make_job("job-lease-4")))
    assert connection.expect(LeaseAccept).lease_id == "lease-4"
    assert jobs.most_running <= 3


def test_cancel_stops_the_job_and_frees_its_slot(fake_control_node, worker_node_configuration, start_daemon, jobs):
    _, connection, _ = connect(fake_control_node, start_daemon, worker_node_configuration(SCENEGEMS_WORKER_NODE_SLOTS="simulation:1"))
    connection.send(make_offer("lease-c", make_job("job-c")))
    connection.expect(LeaseAccept)
    jobs.wait_started()
    connection.send(Cancel(lease_id="lease-c", job_id="job-c", reason="campaign stopped"))
    wait_for(lambda: jobs.cancelled == ["job-c"])
    connection.send(make_offer("lease-d", make_job("job-d")))
    assert connection.expect(LeaseAccept).lease_id == "lease-d"
    assert_no_frame(connection, JobResult)


def test_drain_rejects_new_leases_and_lets_running_ones_finish(fake_control_node, worker_node_configuration, start_daemon, jobs):
    _, connection, _ = connect(fake_control_node, start_daemon, worker_node_configuration())
    connection.send(make_offer("lease-r", make_job("job-r")))
    connection.expect(LeaseAccept)
    jobs.wait_started()
    connection.send(Drain(reason="maintenance"))
    connection.send(make_offer("lease-n", make_job("job-n")))
    reject = connection.expect(LeaseReject)
    assert reject.lease_id == "lease-n" and "draining (maintenance)" in reject.reason
    jobs.finish("job-r")
    assert connection.expect(JobResult).lease_id == "lease-r"


def test_running_jobs_survive_a_reconnect(fake_control_node, worker_node_configuration, start_daemon, jobs):
    _, first, _ = connect(fake_control_node, start_daemon, worker_node_configuration())
    first.send(make_offer("lease-k", make_job("job-k")))
    first.expect(LeaseAccept)
    jobs.wait_started()
    first.close()

    second = fake_control_node.wait_for_connection()
    hello = second.expect(Hello)
    assert hello.running_lease_ids == ["lease-k"]
    jobs.finish("job-k")
    result = second.expect(JobResult)
    assert result.lease_id == "lease-k" and result.outcome == JobOutcome.SUCCEEDED
    assert jobs.started.empty()  # the job ran once


def test_a_result_ready_while_disconnected_is_sent_after_the_reconnect(fake_control_node, worker_node_configuration, start_daemon, jobs):
    daemon, first, _ = connect(fake_control_node, start_daemon, worker_node_configuration(), welcome_timeout_s=0.5)
    first.send(make_offer("lease-w", make_job("job-w")))
    first.expect(LeaseAccept)
    jobs.wait_started()
    fake_control_node.hello_reply = lambda hello: None  # the control node accepts connections but never welcomes
    first.close()
    wait_for(lambda: not daemon.daemon.connected.is_set())
    jobs.finish("job-w")
    time.sleep(0.3)
    assert not first.received(JobResult)

    fake_control_node.hello_reply = None
    wait_for(daemon.daemon.connected.is_set)
    connection = fake_control_node.all_connections[-1]  # the welcomed one; connections during the outage timed out
    result = connection.expect(JobResult, skip=(Hello, Heartbeat, JobStatus, LogLines, LeaseRenew))
    assert result.lease_id == "lease-w" and result.outcome == JobOutcome.SUCCEEDED


def test_a_lease_without_confirmed_renewals_is_given_up(fake_control_node, worker_node_configuration, start_daemon, jobs):
    fake_control_node.lease_timeout_s = 0.5
    fake_control_node.renew_leases = False
    _, connection, _ = connect(fake_control_node, start_daemon, worker_node_configuration(SCENEGEMS_WORKER_NODE_SLOTS="simulation:1"))
    connection.send(make_offer("lease-l", make_job("job-l")))
    connection.expect(LeaseAccept)
    jobs.wait_started()
    wait_for(lambda: jobs.cancelled == ["job-l"], timeout_s=3.0)
    connection.send(make_offer("lease-m", make_job("job-m")))
    assert connection.expect(LeaseAccept).lease_id == "lease-m"
    assert not connection.received(JobResult)


def test_shutdown_releases_running_leases(fake_control_node, worker_node_configuration, start_daemon, jobs):
    daemon, connection, _ = connect(fake_control_node, start_daemon, worker_node_configuration())
    connection.send(make_offer("lease-s", make_job("job-s")))
    connection.expect(LeaseAccept)
    jobs.wait_started()
    daemon.stop()
    release = connection.expect(LeaseRelease)
    assert release.lease_id == "lease-s" and "stopped" in release.reason
    assert jobs.cancelled == ["job-s"]
    assert not connection.received(JobResult)


# Refusals by the control node


def test_a_control_node_of_another_protocol_version_stops_the_daemon(fake_control_node, worker_node_configuration, start_daemon):
    def newer_welcome(_hello):
        return json.dumps({"type": "welcome", "protocol_version": PROTOCOL_VERSION + 1, "control_node_id": fake_control_node.control_node_id, "heartbeat_interval_s": 1.0, "lease_timeout_s": 3.0})

    fake_control_node.hello_reply = newer_welcome
    error = start_daemon(worker_node_configuration()).wait_exit()
    assert isinstance(error, DaemonStopped)
    assert f"received {PROTOCOL_VERSION + 1}, this side speaks {PROTOCOL_VERSION}" in str(error)


def test_a_version_mismatch_error_from_the_control_node_stops_the_daemon(fake_control_node, worker_node_configuration, start_daemon):
    fake_control_node.hello_reply = lambda _hello: ProtocolError(code=ProtocolErrorCode.VERSION_MISMATCH, message="control node speaks 2")
    error = start_daemon(worker_node_configuration()).wait_exit()
    assert isinstance(error, DaemonStopped) and "control node speaks 2" in str(error)


def test_a_welcome_from_another_control_node_stops_the_daemon(fake_control_node, worker_node_configuration, start_daemon):
    fake_control_node.hello_reply = lambda _hello: Welcome(control_node_id="other-control-node", heartbeat_interval_s=1.0, lease_timeout_s=3.0)
    error = start_daemon(worker_node_configuration()).wait_exit()
    assert isinstance(error, DaemonStopped) and "'other-control-node'" in str(error)


def test_an_unreachable_control_node_is_retried_until_stopped(worker_node_configuration, start_daemon):
    configuration = worker_node_configuration(SCENEGEMS_CONTROL_NODE_URL="http://127.0.0.1:9")  # nothing listens on the discard port
    daemon = start_daemon(configuration)
    time.sleep(0.5)
    assert daemon.thread.is_alive()
    daemon.stop()
    assert daemon.error is None


# Live observation


def test_an_observed_job_relays_its_frames_until_the_control_node_stops_observing(fake_control_node, worker_node_configuration, start_daemon):
    """The job stands in for the job stack: it waits for the control node's request and feeds frames as its runner's log follower would."""

    def observed_run(job, worker_node, report, cancel):
        observation = worker_node.observations.of(job)
        control = observation.wait_for_change(0, timeout_s=10.0)
        assert control.active and control.speed == 30.0
        for index in range(25):
            observation.add_frames([({"timestamp": index}, 20)])
            time.sleep(0.01)
        control = observation.wait_for_change(control.revision, timeout_s=10.0)
        assert not control.active
        observation.add_frames([({"timestamp": 99}, 20)])  # not observed any more: dropped
        return {"state_digest": "abc"}

    _, connection, _ = connect(fake_control_node, start_daemon, worker_node_configuration(), run=observed_run)
    connection.send(make_offer("lease-o", make_job("job-o")))
    connection.expect(LeaseAccept)
    connection.send(Observe(job_id="job-o", attempt=2, active=True, speed=30.0))  # another attempt: ignored
    connection.send(Observe(job_id="job-o", attempt=1, active=True, speed=30.0))
    batches = []
    while sum(len(batch.frames) for batch in batches) < 25:
        batches.append(connection.expect(ObservationFrames, skip=(Heartbeat, JobStatus, LogLines, LeaseRenew)))
    assert [frame["timestamp"] for batch in batches for frame in batch.frames] == list(range(25))
    assert [batch.seq for batch in batches] == list(range(1, len(batches) + 1)) and len(batches) >= 2  # batched about 10 times a second
    assert all((batch.lease_id, batch.job_id, batch.attempt) == ("lease-o", "job-o", 1) for batch in batches)

    connection.send(Observe(job_id="job-o", attempt=1, active=False))
    result = connection.expect(JobResult, skip=(Heartbeat, JobStatus, LogLines, LeaseRenew))
    assert result.outcome == JobOutcome.SUCCEEDED
    assert len(connection.received(ObservationFrames)) == len(batches)
