"""Monitor frames of a recorded run on demand, on a real Postgres (-m postgres), through a test client."""

import pytest
from starlette.testclient import TestClient

from scenegems_tool.cluster.control_node.api.control_node_apps import create_operator_app
from scenegems_tool.cluster.control_node.api.run_frames_routes import FRAMES_PRIORITY, frames_key, run_record_frames_key
from scenegems_tool.cluster.control_node.control_plane import ControlPlane
from scenegems_tool.cluster.control_node.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.protocol.artifacts import ArtifactKind, ArtifactRef
from scenegems_tool.cluster.protocol.jobs import JobOutcome, JobSubmission, JobType
from scenegems_tool.cluster.protocol.messages import JobResult
from scenegems_tool.cluster.protocol.routes import CAMPAIGNS_PATH, JOBS_PATH
from scenegems_tool.persistence.schema import TrajectoryGeneratorImplementation
from scenegems_tool.persistence.stores import AssuranceStores, JobStore, NewCase, NewRunRecord, WorkerNodeStore
from tests.scenegems_tool.cluster.control_node.api.test_campaign_routes import CLASS_A, YAML, small_config
from tests.scenegems_tool.cluster.control_node.conftest import EXPECTED, KINEMATIC
from tests.scenegems_tool.cluster.payloads import valid_payload
from tests.scenegems_tool.persistence.stores.builders import ManualClock, make_hello

pytestmark = pytest.mark.postgres

WORKER_NODE = "lab-1"
STATE_LOG = ArtifactRef(sha256="a" * 64, size_bytes=4096, kind=ArtifactKind.TRAJECTORIES, pointer="/trajectories").model_dump(mode="json")
FRAMES = ArtifactRef(sha256="b" * 64, size_bytes=8192, kind=ArtifactKind.FRAMES).model_dump(mode="json")


@pytest.fixture
def clock():
    return ManualClock()


@pytest.fixture
def stores(session_factory, clock) -> AssuranceStores:
    return AssuranceStores.create(session_factory, clock)


@pytest.fixture
def plane(session_factory, clock) -> ControlPlane:
    worker_nodes = WorkerNodeStore(session_factory, clock)
    worker_nodes.register(make_hello(WORKER_NODE, slots={KINEMATIC: 1, JobType.MONITORING_POST_HOC: 1}, fingerprints=dict(EXPECTED)))
    return ControlPlane("lab-control-node", worker_nodes, JobStore(session_factory, clock), ExpectedFingerprints.fixed(EXPECTED), clock=clock)


@pytest.fixture
def client(plane, stores):
    with TestClient(create_operator_app(plane, assurance=stores)) as client:
        yield client


@pytest.fixture
def campaign(client) -> dict:
    return client.post(CAMPAIGNS_PATH, content=small_config(), headers=YAML).json()


def _run_job(plane: ControlPlane, job_id: str, result: dict) -> None:
    """The worker node runs the job and reports its result."""
    lease = plane.jobs.claim_next(WORKER_NODE, 30.0)
    assert lease is not None and lease.job.job_id == job_id
    plane.jobs.accept(lease.lease_id, 30.0)
    plane.jobs.report_result(JobResult(lease_id=lease.lease_id, job_id=job_id, idempotency_key=lease.job.idempotency_key, outcome=JobOutcome.SUCCEEDED, result=result))


def _run_record(stores, campaign_id: str, case_index: int = 0, **fields) -> int:
    (case,) = stores.cases.create_cases(campaign_id, [NewCase(CLASS_A, case_index, 100 + case_index)])
    record = stores.results.add_run_record(NewRunRecord(case.case_id, 0, TrajectoryGeneratorImplementation.STRAIGHT, True, {"mode": "replay"}, {}, case.seed, **fields))
    return record.run_record_id


def _path(campaign_id: str, run_record_id: int) -> str:
    return f"{CAMPAIGNS_PATH}/{campaign_id}/run-records/{run_record_id}/frames"


def _key(campaign_id: str, attempt: int = 1, sha256: str = STATE_LOG["sha256"]) -> str:
    """The frames key of a state log in a campaign of these tests, whose cases run with config version 1."""
    return frames_key(campaign_id, 1, sha256, attempt)


def test_frames_are_requested_once_and_answered_with_the_job_then_the_frames(client, plane, stores, campaign):
    simulation = client.post(JOBS_PATH, json={"job_type": KINEMATIC.value, "payload": valid_payload(KINEMATIC)}).json()
    _run_job(plane, simulation["job_id"], {"trajectories": STATE_LOG, "steps": 10})
    run_record_id = _run_record(stores, campaign["campaign_id"], artifacts={"state_log": STATE_LOG["sha256"]}, job_id=simulation["job_id"])
    path = _path(campaign["campaign_id"], run_record_id)
    assert client.get(path).status_code == 404  # nothing requested yet

    first = client.post(path)
    assert first.status_code == 201
    view = first.json()
    job = view["job"]
    assert view["run_record_id"] == run_record_id and view["frames"] is None
    assert job["job_type"] == "monitoring.post_hoc" and job["state"] == "queued" and job["priority"] == FRAMES_PRIORITY
    assert job["idempotency_key"] == _key(campaign["campaign_id"]) == f"frames:{campaign['campaign_id']}:v1:{STATE_LOG['sha256']}"
    assert set(job["requirements"]["fingerprints"].values()) <= set(EXPECTED.values()) and job["requirements"]["fingerprints"]
    assert job["allowed_worker_nodes"] == []  # the campaign may use every worker node
    payload = plane.jobs.get(job["job_id"]).payload
    assert payload["trajectories"] == STATE_LOG  # the simulation's own reference, pointer included
    assert payload["include_frames"] is True and payload["scenario_id"] == f"run-record-{run_record_id}"
    assert payload["colregs_constraints_content"] == stores.campaigns.config_version(campaign["campaign_id"]).config["domain"]["colregs_constants"]

    again = client.post(path)
    assert again.status_code == 200 and again.json()["job"]["job_id"] == job["job_id"]
    assert client.get(path).json()["job"]["job_id"] == job["job_id"]

    _run_job(plane, job["job_id"], {"frames": FRAMES, "passed": True})
    done = client.get(path).json()
    assert done["job"]["state"] == "succeeded" and done["frames"] == FRAMES


def test_the_frames_job_keeps_to_the_campaigns_selected_worker_nodes(client, plane, stores):
    campaign = client.post(CAMPAIGNS_PATH, content=small_config(resources={"priority": 0, "worker_nodes": [WORKER_NODE, "lab-2"]}), headers=YAML).json()
    stores.artifacts.insert_if_absent(STATE_LOG["sha256"], "trajectories", 4096, "application/json")
    run_record_id = _run_record(stores, campaign["campaign_id"], artifacts={"state_log": STATE_LOG["sha256"]})
    job = client.post(_path(campaign["campaign_id"], run_record_id)).json()["job"]
    assert job["allowed_worker_nodes"] == [WORKER_NODE, "lab-2"]


def test_without_the_simulation_job_the_reference_comes_from_the_artifact_record(client, plane, stores, campaign):
    stores.artifacts.insert_if_absent(STATE_LOG["sha256"], "trajectories", 4096, "application/json")
    run_record_id = _run_record(stores, campaign["campaign_id"], artifacts={"state_log": STATE_LOG["sha256"]})
    response = client.post(_path(campaign["campaign_id"], run_record_id))
    assert response.status_code == 201
    payload = plane.jobs.get(response.json()["job"]["job_id"]).payload
    assert payload["trajectories"] == {"sha256": STATE_LOG["sha256"], "size_bytes": 4096, "kind": "trajectories", "media_type": "application/json", "pointer": None}


def test_a_run_without_a_kept_state_log_is_refused(client, stores, campaign):
    without = _run_record(stores, campaign["campaign_id"])
    response = client.post(_path(campaign["campaign_id"], without))
    assert response.status_code == 409 and "has no state log" in response.json()["detail"]
    (case,) = stores.cases.create_cases(campaign["campaign_id"], [NewCase(CLASS_A, 1, 101)])
    gone = stores.results.add_run_record(NewRunRecord(case.case_id, 0, TrajectoryGeneratorImplementation.STRAIGHT, True, {}, {}, 1, artifacts={"state_log": "c" * 64})).run_record_id
    response = client.post(_path(campaign["campaign_id"], gone))
    assert response.status_code == 409 and "no longer stored" in response.json()["detail"]


def _fail_job(plane: ControlPlane, job_id: str) -> None:
    """The worker node runs the job and reports a failure that is not retried."""
    lease = plane.jobs.claim_next(WORKER_NODE, 30.0)
    assert lease is not None and lease.job.job_id == job_id
    plane.jobs.accept(lease.lease_id, 30.0)
    plane.jobs.report_result(JobResult(lease_id=lease.lease_id, job_id=job_id, idempotency_key=lease.job.idempotency_key, outcome=JobOutcome.FAILED, error="monitor crashed"))


@pytest.fixture
def frames_path(client, stores, campaign) -> str:
    stores.artifacts.insert_if_absent(STATE_LOG["sha256"], "trajectories", 4096, "application/json")
    run_record_id = _run_record(stores, campaign["campaign_id"], artifacts={"state_log": STATE_LOG["sha256"]})
    return _path(campaign["campaign_id"], run_record_id)


def test_a_failed_frames_job_is_returned_as_it_is_without_retry(client, plane, frames_path):
    job = client.post(frames_path).json()["job"]
    _fail_job(plane, job["job_id"])
    for response in (client.post(frames_path), client.get(frames_path)):
        assert response.status_code == 200
        assert response.json()["job"]["job_id"] == job["job_id"] and response.json()["job"]["state"] == "failed"


def test_retry_submits_a_new_job_after_a_failed_one_and_get_follows_the_newest(client, plane, stores, campaign, frames_path):
    first = client.post(frames_path).json()
    base_key = _key(campaign["campaign_id"])
    _fail_job(plane, first["job"]["job_id"])

    retried = client.post(frames_path, params={"retry": "true"})
    assert retried.status_code == 201
    second = retried.json()["job"]
    assert second["job_id"] != first["job"]["job_id"] and second["state"] == "queued"
    assert second["idempotency_key"] == _key(campaign["campaign_id"], 2) == f"{base_key}:2"
    assert second["priority"] == FRAMES_PRIORITY
    assert plane.jobs.get(second["job_id"]).payload == plane.jobs.get(first["job"]["job_id"]).payload
    assert client.get(frames_path).json()["job"]["job_id"] == second["job_id"]
    assert client.post(frames_path).json()["job"]["job_id"] == second["job_id"]  # a plain ask finds the newest

    again = client.post(frames_path, params={"retry": "true"})  # the second is queued: returned as it is
    assert again.status_code == 200 and again.json()["job"]["job_id"] == second["job_id"]

    _fail_job(plane, second["job_id"])
    third = client.post(frames_path, params={"retry": "true"})
    assert third.status_code == 201 and third.json()["job"]["idempotency_key"] == f"{base_key}:3"

    _run_job(plane, third.json()["job"]["job_id"], {"frames": FRAMES, "passed": True})
    done = client.get(frames_path).json()
    assert done["job"]["job_id"] == third.json()["job"]["job_id"] and done["frames"] == FRAMES
    kept = client.post(frames_path, params={"retry": "true"})  # a succeeded job is not replaced
    assert kept.status_code == 200 and kept.json()["frames"] == FRAMES


def test_retry_submits_a_new_job_after_a_cancelled_one(client, plane, frames_path):
    first = client.post(frames_path).json()
    assert plane.jobs.cancel(first["job"]["job_id"], "operator").cancelled
    assert client.get(frames_path).json()["job"]["state"] == "cancelled"
    retried = client.post(frames_path, params={"retry": "true"})
    assert retried.status_code == 201 and retried.json()["job"]["idempotency_key"].endswith(":2")


def test_retry_without_a_request_submits_the_first_job_and_a_running_job_is_kept(client, plane, campaign, frames_path):
    first = client.post(frames_path, params={"retry": "true"})
    assert first.status_code == 201 and first.json()["job"]["idempotency_key"] == _key(campaign["campaign_id"])
    lease = plane.jobs.claim_next(WORKER_NODE, 30.0)
    plane.jobs.accept(lease.lease_id, 30.0)
    running = client.post(frames_path, params={"retry": "true"})
    assert running.status_code == 200 and running.json()["job"]["state"] == "running" and running.json()["job"]["job_id"] == first.json()["job"]["job_id"]


def test_the_newest_job_is_found_among_the_keys_of_the_same_state_log_only(client, plane, stores, campaign, frames_path):
    for sha256 in ("d" * 64, "e" * 64):
        stores.artifacts.insert_if_absent(sha256, "trajectories", 4096, "application/json")
    others = [_run_record(stores, campaign["campaign_id"], case_index=index, artifacts={"state_log": sha256}) for index, sha256 in ((1, "d" * 64), (2, "e" * 64))]
    mine = client.post(frames_path).json()
    _fail_job(plane, mine["job"]["job_id"])
    for other in others:
        assert client.post(_path(campaign["campaign_id"], other)).status_code == 201
    retried = client.post(frames_path, params={"retry": "true"}).json()
    assert retried["job"]["idempotency_key"] == _key(campaign["campaign_id"], 2)
    assert client.get(frames_path).json()["job"]["job_id"] == retried["job"]["job_id"]


def test_the_repeats_of_a_run_with_one_state_log_share_one_frames_job(client, plane, stores, campaign):
    stores.artifacts.insert_if_absent(STATE_LOG["sha256"], "trajectories", 4096, "application/json")
    (case,) = stores.cases.create_cases(campaign["campaign_id"], [NewCase(CLASS_A, 0, 100)])
    repeats = [
        stores.results.add_run_record(
            NewRunRecord(case.case_id, 0, TrajectoryGeneratorImplementation.STRAIGHT, True, {"mode": "replay"}, {}, case.seed, repeat_index=repeat, artifacts={"state_log": STATE_LOG["sha256"]})
        ).run_record_id
        for repeat in range(3)
    ]
    first, second, third = (_path(campaign["campaign_id"], run_record_id) for run_record_id in repeats)
    assert client.get(second).status_code == 404  # nothing judged the state log yet

    asked = client.post(first)
    assert asked.status_code == 201
    job_id = asked.json()["job"]["job_id"]
    # Another repeat has the same state log: the job that judges it is this one, queued or done
    waiting = client.post(second)
    assert waiting.status_code == 200 and waiting.json()["job"]["job_id"] == job_id and waiting.json()["run_record_id"] == repeats[1]
    _run_job(plane, job_id, {"frames": FRAMES, "passed": True})
    for path, run_record_id in zip((first, second, third), repeats):
        for answer in (client.post(path), client.get(path)):
            assert answer.status_code == 200
            assert (answer.json()["run_record_id"], answer.json()["job"]["job_id"], answer.json()["frames"]) == (run_record_id, job_id, FRAMES)
    assert [job.job_type for job in plane.jobs.list_jobs()] == [JobType.MONITORING_POST_HOC]  # one job judged all three


def test_a_state_log_judged_with_another_config_version_or_in_another_campaign_has_a_job_of_its_own():
    sha256 = STATE_LOG["sha256"]
    assert len({frames_key("c1", 1, sha256), frames_key("c1", 2, sha256), frames_key("c2", 1, sha256), frames_key("c1", 1, "d" * 64)}) == 4
    assert frames_key("c1", 1, sha256, 3) == f"frames:c1:v1:{sha256}:3"


def test_a_job_made_under_the_run_records_own_key_is_still_found(client, plane, stores, campaign, frames_path):
    """Frames asked for before the jobs belonged to the state log: they are not judged again."""
    run_record_id = int(frames_path.rsplit("/", 2)[1])
    payload = valid_payload(JobType.MONITORING_POST_HOC)

    def submit(key: str) -> str:
        return plane.jobs.submit(JobSubmission(job_type=JobType.MONITORING_POST_HOC, payload=payload, idempotency_key=key)).job.job_id

    earlier = submit(run_record_frames_key(run_record_id))
    submit(run_record_frames_key(run_record_id + 10))  # another run record's, not this one's
    assert client.get(frames_path).json()["job"]["job_id"] == earlier
    found = client.post(frames_path)
    assert found.status_code == 200 and found.json()["job"]["job_id"] == earlier

    assert plane.jobs.cancel(earlier, "operator").cancelled
    # A retry of it is the state log's first job, which every later request finds first
    retried = client.post(frames_path, params={"retry": "true"})
    assert retried.status_code == 201 and retried.json()["job"]["idempotency_key"] == _key(campaign["campaign_id"])
    assert client.get(frames_path).json()["job"]["job_id"] == retried.json()["job"]["job_id"]


def test_retry_still_refuses_a_run_without_a_kept_state_log(client, stores, campaign):
    without = _run_record(stores, campaign["campaign_id"])
    response = client.post(_path(campaign["campaign_id"], without), params={"retry": "true"})
    assert response.status_code == 409


def test_unknown_campaigns_and_run_records_are_404(client, stores, campaign):
    run_record_id = _run_record(stores, campaign["campaign_id"], artifacts={"state_log": "a" * 64})
    other = client.post(CAMPAIGNS_PATH, content=small_config(), headers=YAML).json()
    assert client.post(_path("no-such-campaign", run_record_id)).status_code == 404
    assert client.post(_path(campaign["campaign_id"], run_record_id + 1000)).status_code == 404
    assert client.post(_path(other["campaign_id"], run_record_id)).status_code == 404
    assert client.get(_path(other["campaign_id"], run_record_id)).status_code == 404
