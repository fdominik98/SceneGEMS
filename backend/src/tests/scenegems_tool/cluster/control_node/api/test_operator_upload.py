"""The operator's artifact upload, POST /cluster/artifacts?kind=, over the test client with the file store and in-memory records."""

import gzip
import json
from datetime import timedelta
from typing import Iterator

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from scenegems_tool.cluster.control_node.api import artifact_routes
from scenegems_tool.cluster.control_node.api.artifact_routes import UPLOAD_HOLD, UPLOAD_KINDS, operator_artifact_router
from scenegems_tool.cluster.control_node.api.control_node_apps import create_operator_app, create_worker_node_api_app
from scenegems_tool.cluster.control_node.control_node_artifacts import ControlNodeArtifacts
from scenegems_tool.cluster.protocol.routes import ARTIFACTS_PATH
from scenegems_tool.persistence.artifacts.artifact_store import sha256_hex
from scenegems_tool.persistence.artifacts.file_artifact_store import FileArtifactStore
from scenegems_tool.persistence.artifacts.recorded_artifacts import RecordedArtifacts
from scenegems_tool.persistence.stores.artifact_records import UnknownArtifact
from tests.scenegems_tool.persistence.artifacts.fake_artifact_records import InMemoryArtifactRecords
from tests.scenegems_tool.persistence.stores.builders import ManualClock

SCENE = json.dumps({"_data": [[{"id": 1, "type": "MiniUSV", "is_vessel": True}, {"x": 0.0, "y": 0.0}]], "dcpa": None}).encode()
SHA = sha256_hex(SCENE)
LIMIT = 1000
JSON = {"Content-Type": "application/json"}


@pytest.fixture
def clock():
    return ManualClock()


@pytest.fixture
def records(clock):
    return InMemoryArtifactRecords(clock)


@pytest.fixture
def artifacts(tmp_path, records) -> RecordedArtifacts:
    return RecordedArtifacts(FileArtifactStore(tmp_path / "artifacts"), records)


@pytest.fixture
def client(artifacts, clock) -> Iterator[TestClient]:
    """The upload router alone, so the hold's expiry runs on the test's clock."""
    app = FastAPI()
    app.include_router(operator_artifact_router(artifacts, LIMIT, clock=clock))
    with TestClient(app) as client:
        yield client


def post(client, content=SCENE, kind="scene", headers=JSON):
    return client.post(ARTIFACTS_PATH, content=content, headers=headers, params={"kind": kind})


HOLD = (SHA, "upload", SHA, "upload")  # the upload reference of the artifact: hash, holder kind, holder id, role


def test_an_upload_is_stored_recorded_and_answered_as_a_reference(client, artifacts):
    response = post(client)
    assert response.status_code == 201
    assert response.json() == {"sha256": SHA, "size_bytes": len(SCENE), "kind": "scene", "media_type": "application/json", "pointer": None}
    assert artifacts.store.read(SHA) == SCENE
    record = artifacts.record(SHA)
    assert (record.kind, record.size_bytes, record.media_type) == ("scene", len(SCENE), "application/json")
    assert client.get(f"{ARTIFACTS_PATH}/{SHA}").content == SCENE


def test_the_upload_is_held_for_24_hours(client, records, clock):
    post(client)
    assert records.expiry[HOLD] == clock.now + UPLOAD_HOLD == clock.now + timedelta(hours=24)
    assert HOLD in records.references


def test_uploading_the_same_file_again_answers_200_and_extends_the_hold(client, records, clock):
    assert post(client).status_code == 201
    first = records.expiry[HOLD]
    clock.advance(3600)
    again = post(client)
    assert again.status_code == 200 and again.json()["sha256"] == SHA
    assert records.expiry[HOLD] == first + timedelta(hours=1)


def test_an_artifact_stored_before_keeps_its_kind(client, artifacts):
    artifacts.put(SCENE, "trajectory_data", "application/json")
    assert post(client, kind="trajectories").json()["kind"] == "trajectory_data"


@pytest.mark.parametrize("kind", UPLOAD_KINDS)
def test_every_upload_kind_is_accepted(client, kind):
    assert post(client, content=SCENE + kind.encode(), kind=kind).json()["kind"] == kind


def test_other_kinds_are_refused(client, artifacts):
    for kind in ("frames", "state_log", "calibration", "trajectory_data", ""):
        assert post(client, kind=kind).status_code == 422, kind
    assert client.post(ARTIFACTS_PATH, content=SCENE, headers=JSON).status_code == 422  # no kind
    assert not artifacts.store.exists(SHA)


def test_an_empty_body_is_refused(client):
    response = post(client, content=b"")
    assert response.status_code == 422 and "empty" in response.json()["detail"]


def test_the_media_type_is_the_content_type_and_json_by_default(client):
    assert post(client, headers={"Content-Type": "application/x-yaml"}).json()["media_type"] == "application/x-yaml"
    assert post(client, content=SCENE + b" ", headers={}).json()["media_type"] == "application/json"
    assert post(client, content=SCENE + b"  ", headers={"Content-Type": "\x01bad"}).status_code in (422, 400)


def test_a_body_over_the_limit_is_refused_by_its_length(client, artifacts):
    big = b"x" * (LIMIT + 1)
    response = post(client, content=big)
    assert response.status_code == 413 and not artifacts.store.exists(sha256_hex(big))


def test_a_streamed_body_over_the_limit_is_refused_and_leaves_nothing_behind(client, artifacts, records):
    def chunks():
        for _ in range(LIMIT // 100 + 5):
            yield b"y" * 100

    response = client.post(ARTIFACTS_PATH, content=chunks(), headers=JSON, params={"kind": "scene"})  # no Content-Length
    assert response.status_code == 413
    assert records.records == {} and not list((artifacts.store.root / ".incoming").iterdir())


def test_a_compressed_body_is_refused(client):
    response = post(client, content=gzip.compress(SCENE), headers={**JSON, "Content-Encoding": "gzip"})
    assert response.status_code == 415 and "not compressed" in response.json()["detail"]
    assert post(client, headers={**JSON, "Content-Encoding": "br"}).status_code == 415


def test_a_body_larger_than_the_spool_memory_is_stored_whole(client, artifacts, monkeypatch):
    monkeypatch.setattr(artifact_routes, "SPOOL_MEMORY_BYTES", 16)
    monkeypatch.setattr(artifact_routes, "STREAM_CHUNK_BYTES", 64)  # several chunks through the hash and the writer
    content = json.dumps({"scene_list": [{"n": index} for index in range(40)]}).encode()
    assert 16 < len(content) < LIMIT
    response = post(client, content=content, kind="trajectories")
    assert response.status_code == 201 and response.json()["sha256"] == sha256_hex(content) and response.json()["size_bytes"] == len(content)
    assert artifacts.store.read(sha256_hex(content)) == content


def test_a_sweep_that_took_the_artifact_meanwhile_answers_409(client, records, monkeypatch):
    def swept(*_arguments, **_keywords):
        raise UnknownArtifact(SHA)

    monkeypatch.setattr(records, "add_upload_reference", swept)
    response = post(client)
    assert response.status_code == 409 and "swept" in response.json()["detail"]


def test_the_operator_app_serves_the_upload_with_the_control_nodes_size_limit(plane_with_artifacts):
    plane, control_node_artifacts = plane_with_artifacts
    with TestClient(create_operator_app(plane, artifacts=control_node_artifacts)) as client:
        assert post(client).status_code == 201
        assert post(client, content=b"z" * (control_node_artifacts.max_bytes + 1)).status_code == 413


def test_the_upload_is_not_on_the_worker_node_api(plane_with_artifacts):
    plane, control_node_artifacts = plane_with_artifacts
    with TestClient(create_worker_node_api_app(plane, run_timers=False, artifacts=control_node_artifacts)) as client:
        assert post(client).status_code == 404


@pytest.fixture
def plane_with_artifacts(memory_plane, artifacts):
    return memory_plane, ControlNodeArtifacts(artifacts, max_bytes=LIMIT)
