"""The artifact routes on the node API and the operator API, over the test client.

The store is a real FileArtifactStore; the records are in memory, or in Postgres together
with the job store when the master's `stores` fixture runs on Postgres.
"""

import gzip
import json
from typing import Iterator

import pytest
from starlette.testclient import TestClient

from scenegems_tool.cluster.master.api import artifact_routes
from scenegems_tool.cluster.master.api.master_apps import create_node_api_app, create_operator_app
from scenegems_tool.cluster.master.api.operator_routes import operator_router
from scenegems_tool.cluster.master.master_artifacts import MasterArtifacts
from scenegems_tool.cluster.protocol.jobs import JobSubmission, JobType
from scenegems_tool.cluster.protocol.messages import LeaseOffer
from scenegems_tool.cluster.protocol.routes import ARTIFACTS_PATH, NODE_ID_HEADER
from scenegems_tool.persistence.artifacts.artifact_store import sha256_hex
from scenegems_tool.persistence.artifacts.file_artifact_store import FileArtifactStore
from scenegems_tool.persistence.artifacts.recorded_artifacts import RecordedArtifacts
from scenegems_tool.persistence.stores import ArtifactRecordStore, JobStore
from tests.scenegems_tool.cluster.payloads import valid_payload
from tests.scenegems_tool.persistence.artifacts.fake_artifact_records import InMemoryArtifactRecords

KINEMATIC = JobType.SIMULATION
DOCUMENT = json.dumps({"trajectories": {str(vessel): [[float(step), 0.0, 8.0, 0.0] for step in range(500)] for vessel in range(3)}}).encode()
SHA = sha256_hex(DOCUMENT)
LIMIT = len(DOCUMENT) + 100


@pytest.fixture
def records(stores, clock, request):
    if isinstance(stores.jobs, JobStore):  # the Postgres run
        return ArtifactRecordStore(request.getfixturevalue("session_factory"), clock)
    return InMemoryArtifactRecords(clock)


@pytest.fixture
def master_artifacts(tmp_path, records) -> MasterArtifacts:
    return MasterArtifacts(RecordedArtifacts(FileArtifactStore(tmp_path / "artifacts"), records), max_bytes=LIMIT)


@pytest.fixture
def client(plane, master_artifacts) -> Iterator[TestClient]:
    """The node API with the artifact routes; it replaces the master conftest's client, so make_node connects to it."""
    app = create_node_api_app(plane, run_timers=False, artifacts=master_artifacts)
    app.include_router(operator_router(plane))
    with TestClient(app) as client:
        yield client


@pytest.fixture
def operator_client(plane, master_artifacts) -> Iterator[TestClient]:
    with TestClient(create_operator_app(plane, artifacts=master_artifacts)) as client:
        yield client


@pytest.fixture
def node(make_node):
    node = make_node("lab", slots={KINEMATIC: 1})
    node.connect()
    return node


def _auth(node) -> dict:
    return {NODE_ID_HEADER: node.node_id}


def _url(sha256: str = SHA) -> str:
    return f"{ARTIFACTS_PATH}/{sha256}"


def _put(client, node, data: bytes = DOCUMENT, sha256: str = None, gzipped: bool = False, **params):
    params.setdefault("kind", "trajectories")
    headers = {**_auth(node), "Content-Type": "application/json"}
    body = gzip.compress(data) if gzipped else data
    if gzipped:
        headers["Content-Encoding"] = "gzip"
    return client.put(_url(sha256 or sha256_hex(data)), params=params, content=body, headers=headers)


# Authentication


def test_both_node_routes_need_a_node_id(client, node):
    for headers in ({}, {NODE_ID_HEADER: "Lab 1"}, {NODE_ID_HEADER: "lab/../x"}, {NODE_ID_HEADER: "#"}):
        assert client.get(_url(), headers=headers).status_code == 400
        assert client.put(_url(), params={"kind": "trajectories"}, content=DOCUMENT, headers=headers).status_code == 400
    assert _put(client, node).status_code == 201


def test_the_listeners_serve_their_own_artifact_routes(plane, master_artifacts):
    node_paths = {(route.path, method) for route in create_node_api_app(plane, artifacts=master_artifacts).routes for method in getattr(route, "methods", ())}
    operator_paths = {(route.path, method) for route in create_operator_app(plane, artifacts=master_artifacts).routes for method in getattr(route, "methods", ())}
    path = ARTIFACTS_PATH + "/{sha256}"
    assert {(path, "GET"), (path, "PUT")} <= node_paths and (path, "HEAD") not in node_paths
    assert {(path, "GET"), (path, "HEAD")} <= operator_paths and (path, "PUT") not in operator_paths
    assert path not in {route.path for route in create_node_api_app(plane).routes}  # no store, no routes


# Upload


@pytest.mark.parametrize("gzipped", [False, True])
def test_an_upload_is_stored_and_recorded(client, node, master_artifacts, records, gzipped):
    response = _put(client, node, gzipped=gzipped)
    assert response.status_code == 201
    body = response.json()
    assert body == {"sha256": SHA, "size_bytes": len(DOCUMENT), "kind": "trajectories", "media_type": "application/json", "stored_size_bytes": body["stored_size_bytes"], "created": True}
    assert master_artifacts.artifacts.store.read(SHA) == DOCUMENT
    assert records.get(SHA).stored_size_bytes == body["stored_size_bytes"] < len(DOCUMENT)
    again = _put(client, node, gzipped=not gzipped)
    assert again.status_code == 200 and again.json()["created"] is False


def test_an_upload_whose_content_hashes_otherwise_is_rejected(client, node, master_artifacts, records):
    wrong = sha256_hex(b"something else")
    for gzipped in (False, True):
        response = _put(client, node, sha256=wrong, gzipped=gzipped)
        assert response.status_code == 422 and "hash mismatch" in response.json()["detail"]
    assert not master_artifacts.artifacts.store.exists(wrong) and records.get(wrong) is None
    assert list(master_artifacts.artifacts.store.incoming.iterdir()) == []


def test_the_size_limit_holds_for_declared_streamed_and_compressed_bodies(client, node, master_artifacts):
    large = b" " * (LIMIT + 1)
    assert _put(client, node, data=large).status_code == 413  # Content-Length says so before the body is read
    chunks = (large[start : start + 4096] for start in range(0, len(large), 4096))
    streamed = client.put(_url(sha256_hex(large)), params={"kind": "trajectories"}, content=chunks, headers=_auth(node))  # chunked: no length
    assert streamed.status_code == 413
    bomb = _put(client, node, data=b"\0" * (LIMIT * 20), gzipped=True)  # tiny on the wire
    assert bomb.status_code == 413
    assert list(master_artifacts.artifacts.store.incoming.iterdir()) == []
    assert _put(client, node, data=b"x" * LIMIT).status_code == 201


def test_an_upload_streams_into_the_store_in_pieces(client, node, master_artifacts, monkeypatch):
    monkeypatch.setattr(artifact_routes, "STREAM_CHUNK_BYTES", 1024)
    writes = []
    writer_of = master_artifacts.artifacts.writer

    def spying_writer(sha256, max_bytes=None):
        writer = writer_of(sha256, max_bytes)
        write = writer.write
        writer.write = lambda data: writes.append(len(data)) or write(data)
        return writer

    monkeypatch.setattr(master_artifacts.artifacts, "writer", spying_writer)
    for gzipped in (False, True):
        writes.clear()
        data = DOCUMENT + bytes([gzipped])
        body = gzip.compress(data) if gzipped else data
        chunks = (body[start : start + 512] for start in range(0, len(body), 512))  # chunked transfer, as it arrives
        headers = {**_auth(node), "Content-Encoding": "gzip"} if gzipped else _auth(node)
        assert client.put(_url(sha256_hex(data)), params={"kind": "trajectories"}, content=chunks, headers=headers).status_code == 201
        assert sum(writes) == len(data)
        if gzipped:  # the test client hands the body over in one piece; its decompressed bytes still go in bounded pieces
            assert len(writes) > 3 and max(writes) <= 1024


def test_invalid_uploads(client, node):
    assert client.put(_url(), params={"kind": "trajectories"}, content=b"not gzip", headers={**_auth(node), "Content-Encoding": "gzip"}).status_code == 400
    assert client.put(_url(), params={"kind": "trajectories"}, content=gzip.compress(DOCUMENT)[:-12], headers={**_auth(node), "Content-Encoding": "gzip"}).status_code == 400
    assert client.put(_url(), params={"kind": "trajectories"}, content=DOCUMENT, headers={**_auth(node), "Content-Encoding": "br"}).status_code == 415
    assert _put(client, node, kind="pictures").status_code == 422
    assert client.put(f"{ARTIFACTS_PATH}/{'A' * 64}", params={"kind": "trajectories"}, content=DOCUMENT, headers=_auth(node)).status_code == 422
    assert client.put(f"{ARTIFACTS_PATH}/..%2F..%2Fsecret", params={"kind": "trajectories"}, content=DOCUMENT, headers=_auth(node)).status_code in (404, 422)


def test_concatenated_gzip_members_are_one_body(client, node, master_artifacts):
    half = len(DOCUMENT) // 2
    body = gzip.compress(DOCUMENT[:half]) + gzip.compress(DOCUMENT[half:])
    response = client.put(_url(), params={"kind": "trajectories"}, content=body, headers={**_auth(node), "Content-Encoding": "gzip"})
    assert response.status_code == 201 and master_artifacts.artifacts.store.read(SHA) == DOCUMENT


# Uploads for a job


def _leased_job(node, on_loop, plane, schedule) -> LeaseOffer:
    on_loop(plane.submit, JobSubmission(job_type=KINEMATIC, payload=valid_payload(KINEMATIC)))
    assert schedule() == 1
    return node.expect(LeaseOffer)


def _job_references(records, sha256):
    if isinstance(records, InMemoryArtifactRecords):
        return sorted((kind, holder, role) for hash_, kind, holder, role in records.references if hash_ == sha256)
    return sorted((reference.holder_kind.value, reference.holder_id, reference.role) for reference in records.references(sha256))


def test_a_job_s_result_upload_is_referenced_by_the_job(client, node, records, on_loop, plane, schedule):
    offer = _leased_job(node, on_loop, plane, schedule)
    response = _put(client, node, job_id=offer.job.job_id, field="trajectories")
    assert response.status_code == 201
    assert _job_references(records, SHA) == [("job", offer.job.job_id, "result:trajectories")]
    node.accept(offer)
    other = sha256_hex(b"[1]")
    assert _put(client, node, data=b"[1]", job_id=offer.job.job_id, field="frames").status_code == 201  # running counts too
    assert _job_references(records, other) == [("job", offer.job.job_id, "result:frames")]


def test_an_upload_for_a_job_another_node_holds_is_refused(client, node, make_node, records, on_loop, plane, schedule, master_artifacts):
    offer = _leased_job(node, on_loop, plane, schedule)
    other = make_node("other", slots={KINEMATIC: 1})
    other.connect()
    for job_id in (offer.job.job_id, "no-such-job"):
        response = _put(client, other, job_id=job_id, field="trajectories")
        assert response.status_code == 409 and "not leased to this node" in response.json()["detail"]
    assert not master_artifacts.artifacts.store.exists(SHA)
    assert _put(client, node, job_id=offer.job.job_id).status_code == 422  # a job's upload names its field
    assert _put(client, node, job_id=offer.job.job_id, field="Bad-Field").status_code == 422


# Download


def test_a_download_streams_the_content_or_its_gzip_bytes(client, node, master_artifacts, monkeypatch):
    master_artifacts.artifacts.put(DOCUMENT, "trajectories", "application/json")
    monkeypatch.setattr(artifact_routes, "STREAM_CHUNK_BYTES", 1000)
    reads = []
    open_artifact = master_artifacts.artifacts.open

    def spying_open(sha256, compressed=False):
        stream = open_artifact(sha256, compressed)
        read = stream.read
        stream.read = lambda size=-1: reads.append(size) or read(size)
        return stream

    monkeypatch.setattr(master_artifacts.artifacts, "open", spying_open)
    with client.stream("GET", _url(), headers={**_auth(node), "Accept-Encoding": "identity"}) as response:
        assert response.status_code == 200 and "content-encoding" not in response.headers
        assert int(response.headers["content-length"]) == len(DOCUMENT) and response.headers["content-type"] == "application/json"
        assert response.headers["etag"] == f'"{SHA}"'
        assert response.read() == DOCUMENT
    assert len(reads) > 3 and set(reads) == {1000}  # read from the file in pieces, never whole
    with client.stream("GET", _url(), headers={**_auth(node), "Accept-Encoding": "gzip"}) as response:
        assert response.headers["content-encoding"] == "gzip"
        raw = b"".join(response.iter_raw())
    assert int(response.headers["content-length"]) == len(raw) == master_artifacts.artifacts.store.stored_size(SHA)
    assert gzip.decompress(raw) == DOCUMENT


def test_a_download_marks_the_artifact_used(client, node, master_artifacts, records, clock):
    master_artifacts.artifacts.put(DOCUMENT, "trajectories", "application/json")
    clock.advance(100)
    assert client.get(_url(), headers=_auth(node)).content == DOCUMENT
    assert records.get(SHA).last_used_at == clock.now


def test_a_missing_artifact_is_404(client, node, operator_client):
    assert client.get(_url(), headers=_auth(node)).status_code == 404
    assert operator_client.get(_url()).status_code == 404 and operator_client.head(_url()).status_code == 404


@pytest.mark.parametrize("accept", ["gzip;q=0", "br, *;q=0.1", ""])
def test_gzip_is_sent_only_to_a_client_that_accepts_it(client, node, master_artifacts, accept):
    master_artifacts.artifacts.put(DOCUMENT, "trajectories", "application/json")
    with client.stream("GET", _url(), headers={**_auth(node), "Accept-Encoding": accept}) as response:
        assert "content-encoding" not in response.headers and response.read() == DOCUMENT


def test_the_operator_reads_artifacts_without_a_node_credential(operator_client, master_artifacts):
    master_artifacts.artifacts.put(DOCUMENT, "trajectories", "application/json")
    response = operator_client.get(_url())
    assert response.status_code == 200 and response.content == DOCUMENT  # the test client decodes gzip
    head = operator_client.head(_url(), headers={"Accept-Encoding": "identity"})
    assert head.status_code == 200 and head.content == b"" and int(head.headers["content-length"]) == len(DOCUMENT)
    assert operator_client.put(_url(), params={"kind": "trajectories"}, content=DOCUMENT).status_code == 405


def test_an_orphan_file_is_served_as_octet_stream(client, node, master_artifacts):
    master_artifacts.artifacts.store.put(DOCUMENT)
    response = client.get(_url(), headers={**_auth(node), "Accept-Encoding": "identity"})
    assert response.content == DOCUMENT and response.headers["content-type"] == "application/octet-stream"
