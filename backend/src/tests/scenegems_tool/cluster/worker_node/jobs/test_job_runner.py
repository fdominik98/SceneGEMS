import hashlib
import json

import pytest

from scenegems_tool.cluster.protocol.artifacts import ArtifactContent, ArtifactKind, ArtifactRef, encode_document
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.worker_node.artifacts.artifact_client import ArtifactHashMismatch, ArtifactTransferError
from scenegems_tool.cluster.worker_node.job_report import JobFailed
from scenegems_tool.cluster.worker_node.jobs import job_runner
from scenegems_tool.cluster.worker_node.jobs.job_types import JOB_TYPE_MODULES


def test_every_job_type_has_a_module_with_a_runner():
    assert set(JOB_TYPE_MODULES) == set(JobType)
    for module in JOB_TYPE_MODULES.values():
        assert callable(module.run)


def test_runner_container_job_types_have_an_in_container_part():
    for job_type in (JobType.SIMULATION, JobType.CALIBRATION_DEVIATION):
        assert callable(JOB_TYPE_MODULES[job_type].execute)


def test_the_job_types_of_a_pool_have_no_in_container_part():
    """They are requests to a long-lived subsystem: no container is started for them."""
    for job_type in (JobType.SCENE_GENERATION, JobType.TRAJECTORY_GENERATION, JobType.MONITORING_POST_HOC):
        assert not hasattr(JOB_TYPE_MODULES[job_type], "execute")


def test_run_job_dispatches_to_the_job_type(monkeypatch, worker_node, make_job):
    calls = []
    module = JOB_TYPE_MODULES[JobType.SIMULATION]
    monkeypatch.setattr(module, "run", lambda job, worker_node, report, cancel: calls.append((job.job_id, report, cancel)) or {"ok": True})
    assert job_runner.run_job(make_job(JobType.SIMULATION, {}), worker_node, "report") == {"ok": True}
    assert calls == [("job-1", "report", None)]


def test_run_job_refuses_a_type_the_worker_node_has_no_slots_for(worker_node, make_job):
    with pytest.raises(JobFailed):
        job_runner.run_job(make_job(JobType.MONITORING_POST_HOC, {}), worker_node, report=None)


# Artifacts


class FakeTransport:
    """The worker node's artifact transport over a dict of stored documents."""

    def __init__(self, documents=None, failure=None):
        self.documents = dict(documents or {})
        self.loads, self.stores = [], []
        self.failure = failure

    def load(self, reference):
        self.loads.append(reference.sha256)
        if self.failure is not None:
            raise self.failure
        return self.documents[reference.sha256]

    def store(self, job, field, data):
        if self.failure is not None:
            raise self.failure
        sha256 = hashlib.sha256(data).hexdigest()
        self.documents[sha256] = data
        self.stores.append((job.job_id, field.name))
        return ArtifactRef(sha256=sha256, size_bytes=len(data), kind=field.kind)


def _stored(transport, document, kind=ArtifactKind.TRAJECTORIES, pointer=None):
    data = encode_document(document, ArtifactContent.JSON)
    sha256 = hashlib.sha256(data).hexdigest()
    transport.documents[sha256] = data
    return ArtifactRef(sha256=sha256, size_bytes=len(data), kind=kind, pointer=pointer).model_dump(mode="json")


def _missing_reference():
    return ArtifactRef(sha256="a" * 64, size_bytes=1, kind=ArtifactKind.TRAJECTORIES).model_dump(mode="json")


@pytest.fixture
def ran(monkeypatch):
    """What the kinematic job's run saw; it returns a result with trajectories."""
    seen = {}

    def run(job, worker_node, report, cancel):
        seen["payload"] = job.payload
        return {"run_record": {"steps": 3}, "steps": 3, "state_digest": "d", "trajectories": {"0": [[1.0, 2.0]]}}

    monkeypatch.setattr(JOB_TYPE_MODULES[JobType.SIMULATION], "run", run)
    return seen


class Report:
    def __init__(self):
        self.lines = []

    def status(self, message, progress=None):
        self.lines.append(message)

    def log(self, source, text, stream=None):
        pass


def test_references_are_resolved_before_the_job_runs_and_results_go_back_as_references(worker_node, make_job, ran):
    transport = FakeTransport()
    worker_node.artifacts = transport
    trajectories = {"0": [[0.0, 0.0, 8.0, 0.0]], "1": [[3000.0, 0.0, 8.0, 3.14]]}
    reference = _stored(transport, {"algorithm_desc": "straight", "trajectories": trajectories}, kind=ArtifactKind.TRAJECTORY_DATA, pointer="/trajectories")
    report = Report()
    result = job_runner.run_job(make_job(JobType.SIMULATION, {"trajectories": reference, "include_trajectories": True}), worker_node, report)
    assert ran["payload"] == {"trajectories": trajectories, "include_trajectories": True}
    stored = ArtifactRef.model_validate(result["trajectories"])
    assert stored.kind == ArtifactKind.TRAJECTORIES and json.loads(transport.documents[stored.sha256]) == {"0": [[1.0, 2.0]]}
    assert transport.stores == [("job-1", "trajectories")]
    assert (result["steps"], result["state_digest"], result["run_record"]) == (3, "d", {"steps": 3})  # small fields stay inline
    assert report.lines == ["Downloading 1 input artifacts", f"Uploading the trajectories artifact ({stored.size_bytes} bytes)"]


def test_a_job_without_references_runs_as_before(worker_node, make_job, ran):
    payload = {"trajectories": {"0": [[0.0, 0.0, 8.0, 0.0]]}}
    assert job_runner.run_job(make_job(JobType.SIMULATION, payload), worker_node, Report())["trajectories"] == {"0": [[1.0, 2.0]]}  # no transport: inline
    transport = FakeTransport()
    worker_node.artifacts = transport
    job = make_job(JobType.SIMULATION, payload)
    result = job_runner.run_job(job, worker_node, Report())
    assert ran["payload"] is job.payload and transport.loads == []  # the very job, untouched
    assert ArtifactRef.model_validate(result["trajectories"]).sha256 in transport.documents


def test_references_on_a_worker_node_without_transport_fail_for_good(worker_node, make_job, ran):
    with pytest.raises(JobFailed) as failed:
        job_runner.run_job(make_job(JobType.SIMULATION, {"trajectories": _missing_reference()}), worker_node, Report())
    assert not failed.value.retryable and "no artifact transport" in str(failed.value) and "payload" not in ran


@pytest.mark.parametrize(
    "failure, retryable",
    [
        (ArtifactTransferError("connection reset", retryable=True), True),
        (ArtifactTransferError("HTTP 404", retryable=False, status=404), False),
        (ArtifactHashMismatch("hashes to something else"), False),
    ],
)
def test_download_failures_keep_their_retryability(worker_node, make_job, ran, failure, retryable):
    worker_node.artifacts = FakeTransport(failure=failure)
    with pytest.raises(JobFailed) as failed:
        job_runner.run_job(make_job(JobType.SIMULATION, {"trajectories": _missing_reference()}), worker_node, Report())
    assert failed.value.retryable == retryable and "payload" not in ran


def test_an_upload_failure_is_retryable(worker_node, make_job, ran):
    worker_node.artifacts = FakeTransport(failure=ArtifactTransferError("the control node is restarting", retryable=True, status=503))
    with pytest.raises(JobFailed) as failed:
        job_runner.run_job(make_job(JobType.SIMULATION, {"trajectories": {"0": []}}), worker_node, Report())
    assert failed.value.retryable and "upload" in str(failed.value)


def test_a_reference_that_does_not_fit_its_document_fails_for_good(worker_node, make_job, ran):
    transport = FakeTransport()
    worker_node.artifacts = transport
    reference = _stored(transport, {"other": 1}, pointer="/trajectories")
    with pytest.raises(JobFailed) as failed:
        job_runner.run_job(make_job(JobType.SIMULATION, {"trajectories": reference}), worker_node, Report())
    assert not failed.value.retryable and "payload" not in ran


def test_text_inputs_and_lists_of_references(worker_node, make_job, monkeypatch):
    transport = FakeTransport()
    worker_node.artifacts = transport
    worker_node.slots.update({JobType.TRAJECTORY_GENERATION: 1, JobType.CALIBRATION_DEVIATION: 1})
    seen = []
    for job_type in (JobType.TRAJECTORY_GENERATION, JobType.CALIBRATION_DEVIATION):
        monkeypatch.setattr(JOB_TYPE_MODULES[job_type], "run", lambda job, worker_node, report, cancel: seen.append(job.payload) or {})
    scene = {"best_scene": {"actors": []}}
    scene_reference = _stored(transport, scene, kind=ArtifactKind.SCENE)
    job_runner.run_job(make_job(JobType.TRAJECTORY_GENERATION, {"scenario_content": scene_reference, "colregs_constraints_content": ""}), worker_node, Report())
    assert json.loads(seen[0]["scenario_content"]) == scene  # a text field gets the document as a string
    first = _stored(transport, {"0": [[0.0]]})
    job_runner.run_job(make_job(JobType.CALIBRATION_DEVIATION, {"trajectories": [first, {"0": [[1.0]]}], "reference": "r"}), worker_node, Report())
    assert seen[1]["trajectories"] == [{"0": [[0.0]]}, {"0": [[1.0]]}]  # each item inline or a reference
