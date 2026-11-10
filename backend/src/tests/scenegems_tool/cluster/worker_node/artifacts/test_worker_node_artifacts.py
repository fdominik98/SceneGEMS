import hashlib
import threading

from scenegems_tool.cluster.protocol.artifacts import TEXT_MEDIA_TYPE, ArtifactContent, ArtifactField, ArtifactKind, ArtifactRef
from scenegems_tool.cluster.protocol.jobs import JobSpec, JobType
from scenegems_tool.cluster.worker_node.artifacts.artifact_cache import ArtifactCache
from scenegems_tool.cluster.worker_node.artifacts.worker_node_artifacts import WorkerNodeArtifacts

DATA = b'{"trajectories":{}}'
SHA = hashlib.sha256(DATA).hexdigest()
REFERENCE = ArtifactRef(sha256=SHA, size_bytes=len(DATA), kind=ArtifactKind.TRAJECTORIES)
JOB = JobSpec(job_id="job-3", job_type=JobType.SIMULATION, attempt=1, idempotency_key="k")


class FakeClient:
    def __init__(self, gate=None):
        self.downloads, self.uploads = [], []
        self._gate = gate

    def download(self, sha256, max_bytes=None):
        self.downloads.append((sha256, max_bytes))
        if self._gate is not None:
            self._gate.wait(timeout=10)
        return DATA

    def upload(self, data, kind, media_type, *, job_id=None, field=None):
        self.uploads.append((data, kind, media_type, job_id, field))
        return ArtifactRef(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data), kind=kind, media_type=media_type)


def test_an_input_is_downloaded_once_then_read_from_the_cache(tmp_path):
    client = FakeClient()
    artifacts = WorkerNodeArtifacts(client, ArtifactCache(tmp_path / "cache"))
    assert artifacts.load(REFERENCE) == DATA and artifacts.load(REFERENCE) == DATA
    assert client.downloads == [(SHA, len(DATA))]


def test_two_jobs_that_need_one_input_at_once_download_it_once(tmp_path):
    gate = threading.Event()
    client = FakeClient(gate)
    artifacts = WorkerNodeArtifacts(client, ArtifactCache(tmp_path / "cache"))
    results = []
    threads = [threading.Thread(target=lambda: results.append(artifacts.load(REFERENCE))) for _ in range(3)]
    for thread in threads:
        thread.start()
    gate.set()
    for thread in threads:
        thread.join(timeout=10)
    assert results == [DATA] * 3 and len(client.downloads) == 1


def test_a_result_is_uploaded_for_its_job_and_cached(tmp_path):
    client = FakeClient()
    cache = ArtifactCache(tmp_path / "cache")
    artifacts = WorkerNodeArtifacts(client, cache)
    reference = artifacts.store(JOB, ArtifactField("trajectories", ArtifactKind.TRAJECTORIES), DATA)
    assert reference.sha256 == SHA and cache.get(SHA) == DATA
    assert client.uploads == [(DATA, ArtifactKind.TRAJECTORIES, "application/json", "job-3", "trajectories")]
    artifacts.store(JOB, ArtifactField("scenario_content", ArtifactKind.SCENE, ArtifactContent.TEXT), b"text")
    assert client.uploads[-1][2] == TEXT_MEDIA_TYPE


def test_without_a_cache_every_load_downloads():
    client = FakeClient()
    artifacts = WorkerNodeArtifacts(client)
    artifacts.load(REFERENCE)
    artifacts.load(REFERENCE)
    artifacts.store(JOB, ArtifactField("trajectories", ArtifactKind.TRAJECTORIES), DATA)
    assert len(client.downloads) == 2
