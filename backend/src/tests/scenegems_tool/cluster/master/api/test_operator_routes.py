from datetime import datetime, timezone

from fastapi import FastAPI
from starlette.testclient import TestClient

from scenegems_tool.cluster.fingerprints.components import SCENARIO_EXECUTION_IMAGE, SCENE_GENERATION_IMAGE
from scenegems_tool.cluster.master.api.master_apps import create_operator_app
from scenegems_tool.cluster.master.api.operator_routes import NODES_PATH, STATUS_PATH
from scenegems_tool.cluster.master.control_plane import ControlPlane
from scenegems_tool.cluster.master.scheduling.fingerprint_policy import ExpectedFingerprints
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.protocol.messages import Cancel, Drain, JobStatus, LeaseOffer, LogLine, LogLines, LogStream
from scenegems_tool.cluster.protocol.routes import JOBS_PATH
from tests.scenegems_tool.cluster.master.conftest import EXPECTED, EXPECTED_BY_REPOSITORY, KINEMATIC, SCENE
from tests.scenegems_tool.cluster.payloads import valid_payload
from utils.image_names import image_repository


def _submit(client, **body):
    body.setdefault("job_type", SCENE.value)
    body.setdefault("payload", valid_payload(JobType(body["job_type"])) if body["job_type"] in {job_type.value for job_type in JobType} else {})
    return client.post(JOBS_PATH, json=body)


def test_a_submission_is_queued_with_the_expected_fingerprints(client):
    response = _submit(client, payload=valid_payload(SCENE, seed=1), priority=3)
    assert response.status_code == 201
    job = response.json()
    assert job["state"] == "queued" and job["priority"] == 3 and job["attempt"] == 0
    assert job["requirements"]["fingerprints"] == {image_repository(SCENE_GENERATION_IMAGE): "fp-scene"}
    assert job["allowed_nodes"] == []


def test_a_known_idempotency_key_returns_the_first_job(client):
    first = _submit(client, idempotency_key="scene-42")
    second = _submit(client, idempotency_key="scene-42", payload=valid_payload(SCENE, seed=2))
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["job_id"] == second.json()["job_id"]


def test_an_invalid_submission_is_refused(client):
    assert _submit(client, unknown_field=1).status_code == 422
    assert _submit(client, job_type="no.such.type").status_code == 422
    assert _submit(client, max_attempts=0).status_code == 422


def test_a_payload_that_does_not_match_its_job_type_is_answered_with_422(client):
    response = _submit(client, job_type=KINEMATIC.value, payload={"runner": "kinematic", "trajectories": {"time_step": 1, "scene_list": []}})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["job_type"] == "simulation" and "no scene" in detail["message"]
    assert [error["loc"] for error in detail["errors"]] == [["kinematic", "trajectories", "inline"]], "the runner leads the path"
    assert client.get(JOBS_PATH).json() == []


def test_submissions_wait_for_the_expected_fingerprints(stores, clock):
    pending = ExpectedFingerprints(lambda: (_ for _ in ()).throw(RuntimeError("bash missing")))
    plane = ControlPlane("lab-master", stores.nodes, stores.jobs, pending, clock=clock)
    with TestClient(create_operator_app(plane)) as client:
        response = _submit(client)
        assert response.status_code == 503 and "pending" in response.json()["detail"]
        pinned = _submit(client, requirements={"fingerprints": {SCENE_GENERATION_IMAGE: "campaign-pin"}})
        assert pinned.status_code == 201  # a submission that names its fingerprints needs no listing


def test_job_queries(client, make_node, schedule):
    node = make_node("lab 1", slots={SCENE: 1})
    node.connect()
    first = _submit(client).json()
    second = _submit(client, job_type=KINEMATIC.value).json()
    schedule()
    offer = node.expect(LeaseOffer)
    node.accept(offer)

    listed = client.get(JOBS_PATH).json()
    assert [job["job_id"] for job in listed] == [first["job_id"], second["job_id"]]
    assert [job["job_id"] for job in client.get(JOBS_PATH, params={"state": "running"}).json()] == [first["job_id"]]
    assert client.get(JOBS_PATH, params={"state": "bogus"}).status_code == 422

    detail = client.get(f"{JOBS_PATH}/{first['job_id']}").json()
    assert detail["state"] == "running" and detail["lease_owner"] == node.node_id
    assert [event["kind"] for event in detail["events"]] == ["submitted", "leased", "accepted"]
    assert detail["payload"] == valid_payload(SCENE) and detail["log_lines"] == []
    assert client.get(f"{JOBS_PATH}/no-such-job").status_code == 404


def test_progress_and_log_lines_of_a_running_job(client, make_node, schedule):
    node = make_node("lab 1", slots={SCENE: 1})
    node.connect()
    job = _submit(client).json()
    schedule()
    offer = node.expect(LeaseOffer)
    node.accept(offer)
    node.send(JobStatus(lease_id=offer.lease_id, job_id=job["job_id"], progress=0.4, message="sampling"))
    node.send_and_sync(LogLines(lease_id=offer.lease_id, job_id=job["job_id"], lines=[LogLine(timestamp=datetime.now(timezone.utc), stream=LogStream.STDOUT, source="runner", text="hello")]))
    detail = client.get(f"{JOBS_PATH}/{job['job_id']}").json()
    assert detail["progress"]["progress"] == 0.4 and detail["progress"]["message"] == "sampling"
    assert [line["text"] for line in detail["log_lines"]] == ["hello"]


def test_cancel_tells_the_node(client, make_node, schedule):
    node = make_node("lab 1", slots={SCENE: 1})
    node.connect()
    job = _submit(client).json()
    schedule()
    offer = node.expect(LeaseOffer)
    node.accept(offer)
    response = client.post(f"{JOBS_PATH}/{job['job_id']}/cancel", json={"reason": "wrong batch"})
    assert response.status_code == 200 and response.json()["cancelled"] and response.json()["job"]["state"] == "cancelled"
    assert node.expect(Cancel).reason == "wrong batch"
    again = client.post(f"{JOBS_PATH}/{job['job_id']}/cancel")
    assert again.status_code == 200 and not again.json()["cancelled"]
    assert client.post(f"{JOBS_PATH}/no-such-job/cancel").status_code == 404


def test_nodes_show_connection_and_fingerprint_state(client, make_node, schedule):
    current = make_node("current", slots={SCENE: 1}, components=["scene_generation"])
    stale = make_node(
        "stale", slots={KINEMATIC: 1, SCENE: 1}, components=["simulation_layer/kinematic", "scene_generation", "control_layer/none"], fingerprints=dict(EXPECTED, **{SCENARIO_EXECUTION_IMAGE: "old"})
    )
    current.connect()
    stale.connect()
    schedule()  # the scheduler compares the fingerprints
    nodes = {node["node_id"]: node for node in client.get(NODES_PATH).json()}
    assert nodes[current.node_id]["connected"] and not nodes[current.node_id]["out_of_date"]
    assert nodes[stale.node_id]["out_of_date"]
    assert nodes[stale.node_id]["fingerprint_mismatches"] == [{"image": image_repository(SCENARIO_EXECUTION_IMAGE), "required": "fp-execution", "actual": "old"}]
    assert nodes[current.node_id]["slots"] == {"scene_generation": {"slots": 1, "slots_in_use": 0}}
    assert nodes[current.node_id]["components"] == [{"component": "scene_generation", "images": [SCENE_GENERATION_IMAGE], "state": "usable"}]
    assert nodes[stale.node_id]["components"] == [
        {"component": "control_layer/none", "images": [], "state": "usable"},  # the absence of a controller has no container
        {"component": "simulation_layer/kinematic", "images": [SCENARIO_EXECUTION_IMAGE], "state": "out_of_date"},
        {"component": "scene_generation", "images": [SCENE_GENERATION_IMAGE], "state": "usable"},
    ], "in catalog order, the stale one marked"
    assert "capabilities" not in nodes[current.node_id]
    assert client.get(f"{NODES_PATH}/{stale.node_id}").json()["status"] == "online"
    assert client.get(f"{NODES_PATH}/nobody").status_code == 404


def test_nodes_show_the_machine_they_report(client, make_node):
    named = make_node("lab 1", machine="lab-pc-3")
    bare = make_node("lab 2")
    named.connect()
    bare.connect()
    nodes = {node["node_id"]: node for node in client.get(NODES_PATH).json()}
    assert nodes[named.node_id]["machine"] == "lab-pc-3" and nodes[bare.node_id]["machine"] is None
    assert client.get(f"{NODES_PATH}/{named.node_id}").json()["machine"] == "lab-pc-3"
    assert client.post(f"{NODES_PATH}/{named.node_id}/drain").json()["machine"] == "lab-pc-3"


def test_drain_and_resume(client, make_node):
    node = make_node("lab 1")
    node.connect()
    drained = client.post(f"{NODES_PATH}/{node.node_id}/drain", json={"reason": "update"})
    assert drained.status_code == 200 and drained.json()["status"] == "draining"
    assert node.expect(Drain).reason == "update"
    assert client.post(f"{NODES_PATH}/{node.node_id}/resume").json()["status"] == "online"
    assert client.post(f"{NODES_PATH}/nobody/drain").status_code == 404
    assert client.post(f"{NODES_PATH}/nobody/resume").status_code == 404


def test_remove_forgets_an_offline_node(client, make_node, on_loop, plane, clock):
    old = make_node("lab 1")
    kept = make_node("lab 2")
    old.connect()
    kept.connect()
    assert client.post(f"{NODES_PATH}/{old.node_id}/remove").status_code == 409  # online
    old.close()
    clock.advance(plane.registry._offline_after_s + 1)
    on_loop(plane.registry.sweep_silent)
    assert client.get(f"{NODES_PATH}/{old.node_id}").json()["status"] == "offline"
    removed = client.post(f"{NODES_PATH}/{old.node_id}/remove")
    assert removed.status_code == 200 and removed.json() == {"removed": old.node_id}
    assert client.get(f"{NODES_PATH}/{old.node_id}").status_code == 404
    assert client.post(f"{NODES_PATH}/{old.node_id}/remove").status_code == 404
    assert client.post(f"{NODES_PATH}/nobody/remove").status_code == 404
    assert [node["node_id"] for node in client.get(NODES_PATH).json()] == [kept.node_id]


def test_status(client, make_node):
    node = make_node("lab 1")
    node.connect()
    status = client.get(STATUS_PATH).json()
    assert status["master_id"] == "lab-master" and status["connected_nodes"] == [node.node_id]
    assert status["expected_fingerprints"]["state"] == "ready" and status["expected_fingerprints"]["images"] == EXPECTED_BY_REPOSITORY
    assert status["live_sessions"] is False  # no gateway


def test_status_reports_whether_the_gateway_starts_live_sessions(plane):
    gateway = FastAPI()
    with TestClient(create_operator_app(plane, gateway)) as client:
        assert client.get(STATUS_PATH).json()["live_sessions"] is True
    with TestClient(create_operator_app(plane, gateway, live_sessions=False)) as client:
        assert client.get(STATUS_PATH).json()["live_sessions"] is False


def test_the_operator_app_answers_health_without_a_gateway(plane):
    with TestClient(create_operator_app(plane)) as client:
        response = client.get("/health")
    assert response.status_code == 200 and response.json() == {"status": "ok"}
