import os
import threading
import time

import pytest

from scenegems_tool.persistence.artifacts.artifact_store import ArtifactHashMismatch, ArtifactNotFound, sha256_hex
from scenegems_tool.persistence.artifacts.file_artifact_store import FileArtifactStore
from scenegems_tool.persistence.artifacts.recorded_artifacts import ArtifactHolder, RecordedArtifacts, result_role
from scenegems_tool.persistence.schema import ArtifactHolderKind
from tests.scenegems_tool.persistence.artifacts.fake_artifact_records import InMemoryArtifactRecords

DOCUMENT = b'{"scene":"head-on"}' * 50
SHA = sha256_hex(DOCUMENT)
GRACE_S = 3600.0
JOB = ArtifactHolder(ArtifactHolderKind.JOB, "job-7", result_role("trajectories"))


def _references(records, sha256):
    if isinstance(records, InMemoryArtifactRecords):
        return sorted((kind, holder, role) for hash_, kind, holder, role in records.references if hash_ == sha256)
    return sorted((reference.holder_kind.value, reference.holder_id, reference.role) for reference in records.references(sha256))


def test_an_upload_stores_the_file_then_records_it_with_its_sizes(artifacts, records, clock):
    recorded = artifacts.put(DOCUMENT, "scene", "application/json")
    assert recorded.recorded and recorded.stored.created
    record = records.get(SHA)
    assert (record.kind, record.size_bytes, record.stored_size_bytes, record.media_type, record.created_at) == (
        "scene",
        len(DOCUMENT),
        recorded.stored.stored_size_bytes,
        "application/json",
        clock.now,
    )
    assert artifacts.store.read(SHA) == DOCUMENT
    clock.advance(10)
    again = artifacts.put(DOCUMENT, "scene", "application/json")
    assert not again.recorded and records.get(SHA).last_used_at == clock.now


def test_a_job_s_upload_is_referenced_by_the_job(artifacts, records):
    artifacts.put(DOCUMENT, "trajectories", "application/json", holder=JOB)
    assert _references(records, SHA) == [("job", "job-7", "result:trajectories")]
    artifacts.put(DOCUMENT, "trajectories", "application/json", holder=JOB)  # a second attempt adds nothing
    assert _references(records, SHA) == [("job", "job-7", "result:trajectories")]


def test_a_rejected_upload_records_nothing(artifacts, records):
    with pytest.raises(ArtifactHashMismatch):
        artifacts.put(DOCUMENT, "scene", "application/json", sha256="0" * 64)
    assert records.get("0" * 64) is None and records.get(SHA) is None


def test_the_file_comes_before_the_record(tmp_path, clock):
    records = InMemoryArtifactRecords(clock)
    artifacts = RecordedArtifacts(FileArtifactStore(tmp_path / "artifacts"), records)

    def failing_insert(*_arguments, **_options):
        raise ConnectionError("the database is gone")

    records.insert_if_absent = failing_insert
    with pytest.raises(ConnectionError):
        artifacts.put(DOCUMENT, "scene", "application/json")
    assert artifacts.store.exists(SHA) and records.get(SHA) is None  # an orphan file, never a record without a file


def test_reading_marks_the_record_used(artifacts, records, clock):
    artifacts.put(DOCUMENT, "scene", "application/json")
    clock.advance(GRACE_S + 1)
    with artifacts.open(SHA) as stream:
        assert stream.read() == DOCUMENT
    assert records.get(SHA).last_used_at == clock.now
    assert artifacts.sweep(GRACE_S) == []
    with pytest.raises(ArtifactNotFound):
        artifacts.open("2" * 64)


def test_the_sweep_deletes_unreferenced_artifacts_after_the_grace_period(artifacts, records, clock):
    kept, swept, young = b'{"kept":1}', b'{"swept":2}', b'{"young":3}'
    artifacts.put(kept, "scene", "application/json", holder=JOB)
    artifacts.put(swept, "scene", "application/json")
    clock.advance(GRACE_S + 1)
    artifacts.put(young, "scene", "application/json")
    assert artifacts.sweep(GRACE_S) == [sha256_hex(swept)]
    assert records.get(sha256_hex(swept)) is None and not artifacts.store.exists(sha256_hex(swept))
    for content in (kept, young):
        assert records.get(sha256_hex(content)) is not None and artifacts.store.exists(sha256_hex(content))
    # Once the job's reference goes, the kept artifact is swept after its grace period too
    records.remove_references_of(ArtifactHolderKind.JOB, "job-7")
    assert artifacts.sweep(GRACE_S) == []
    clock.advance(GRACE_S + 1)
    assert sorted(artifacts.sweep(GRACE_S)) == sorted([sha256_hex(kept), sha256_hex(young)])


def test_the_sweep_works_through_every_batch(artifacts, clock):
    contents = [f'{{"n":{index}}}'.encode() for index in range(7)]
    for content in contents:
        artifacts.put(content, "scene", "application/json")
    clock.advance(GRACE_S + 1)
    assert sorted(artifacts.sweep(GRACE_S, batch=3)) == sorted(sha256_hex(content) for content in contents)


def test_the_sweep_deletes_the_record_before_the_file(tmp_path, clock):
    records = InMemoryArtifactRecords(clock)
    store = FileArtifactStore(tmp_path / "artifacts")
    order = []
    delete_file = store.delete
    store.delete = lambda sha256: order.append(("file", records.get(sha256) is None)) or delete_file(sha256)
    artifacts = RecordedArtifacts(store, records)
    artifacts.put(DOCUMENT, "scene", "application/json")
    clock.advance(GRACE_S + 1)
    assert artifacts.sweep(GRACE_S) == [SHA]
    assert order == [("file", True)]


def test_an_upload_during_a_sweep_keeps_its_file(tmp_path, clock):
    """The sweep has deleted the record and is about to delete the file when the same content is uploaded again."""
    records = InMemoryArtifactRecords(clock)
    store = FileArtifactStore(tmp_path / "artifacts")
    artifacts = RecordedArtifacts(store, records)
    artifacts.put(DOCUMENT, "scene", "application/json")
    clock.advance(GRACE_S + 1)
    record_deleted, upload_done = threading.Event(), threading.Event()
    delete_records = records.delete_unreferenced

    def delete_then_pause(hashes, unused_for_s, **options):
        deleted = delete_records(hashes, unused_for_s, **options)
        record_deleted.set()
        upload_done.wait(timeout=0.5)  # the upload must wait for the sweep's lock, so this times out
        return deleted

    records.delete_unreferenced = delete_then_pause
    uploader = threading.Thread(target=lambda: (record_deleted.wait(timeout=10), artifacts.put(DOCUMENT, "scene", "application/json"), upload_done.set()))
    uploader.start()
    assert artifacts.sweep(GRACE_S) == [SHA]
    uploader.join(timeout=10)
    assert upload_done.is_set()
    assert records.get(SHA) is not None and store.exists(SHA) and store.read(SHA) == DOCUMENT


def _age_file(artifacts, sha256, seconds):
    then = time.time() - seconds
    os.utime(artifacts.store.path(sha256), (then, then))


def test_the_orphan_sweep_deletes_old_files_without_a_record(artifacts, records):
    orphan = artifacts.store.put(b'{"orphan":true}').sha256  # a file whose record was never written
    recorded = artifacts.put(DOCUMENT, "scene", "application/json").stored.sha256
    young = artifacts.store.put(b'{"young orphan":true}').sha256
    _age_file(artifacts, orphan, GRACE_S + 60)
    _age_file(artifacts, recorded, GRACE_S + 60)
    assert artifacts.sweep_orphans(GRACE_S) == [orphan]
    assert not artifacts.store.exists(orphan)
    assert artifacts.store.exists(recorded) and records.get(recorded) is not None  # its record keeps it, however old the file
    assert artifacts.store.exists(young)  # inside the grace period
    assert artifacts.sweep_orphans(GRACE_S) == []


def test_an_orphan_recorded_while_the_sweep_runs_is_kept(artifacts, records, monkeypatch):
    sha256 = artifacts.store.put(DOCUMENT).sha256
    _age_file(artifacts, sha256, GRACE_S + 60)
    existing = records.existing_hashes

    def record_meanwhile(hashes, **options):
        found = existing(hashes, **options)  # listed without a record
        artifacts.put(DOCUMENT, "scene", "application/json")  # then an upload of equal content records it
        return found

    monkeypatch.setattr(records, "existing_hashes", record_meanwhile)
    assert artifacts.sweep_orphans(GRACE_S) == []
    assert artifacts.store.exists(sha256) and records.get(sha256) is not None


def test_the_orphan_sweep_checks_records_in_batches(artifacts, records, monkeypatch):
    orphans = [artifacts.store.put(f'{{"orphan":{n}}}'.encode()).sha256 for n in range(5)]
    for sha256 in orphans:
        _age_file(artifacts, sha256, GRACE_S + 60)
    batches = []
    existing = records.existing_hashes
    monkeypatch.setattr(records, "existing_hashes", lambda hashes, **options: batches.append(len(hashes)) or existing(hashes, **options))
    assert sorted(artifacts.sweep_orphans(GRACE_S, batch=2)) == sorted(orphans)
    assert sorted(batches) == [1, 2, 2]


def test_a_file_without_a_record_is_still_served(artifacts):
    artifacts.store.put(DOCUMENT)
    with artifacts.open(SHA) as stream:
        assert stream.read() == DOCUMENT
    assert artifacts.record(SHA) is None
