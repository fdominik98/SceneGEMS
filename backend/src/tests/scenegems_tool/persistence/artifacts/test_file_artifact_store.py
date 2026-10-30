import gzip
import hashlib
import os
import threading
import time

import pytest

from scenegems_tool.persistence.artifacts.artifact_store import COMPRESSED_ENCODING, ArtifactHashMismatch, ArtifactNotFound, ArtifactTooLarge, sha256_hex
from scenegems_tool.persistence.artifacts.file_artifact_store import INCOMING_FOLDER, FileArtifactStore

DOCUMENT = b'{"trajectories":{"0":[[0.0,0.0,8.0,0.0]]}}' * 2000
SHA = sha256_hex(DOCUMENT)


@pytest.fixture
def store(tmp_path) -> FileArtifactStore:
    return FileArtifactStore(tmp_path / "artifacts")


def _incoming(store):
    return sorted(path.name for path in store.incoming.iterdir())


def test_content_is_stored_gzip_compressed_under_its_hash(store):
    stored = store.put(DOCUMENT)
    assert (stored.sha256, stored.size_bytes, stored.created) == (SHA, len(DOCUMENT), True)
    path = store.root / SHA[:2] / SHA[2:4] / f"{SHA}.gz"
    assert path.is_file() and stored.stored_size_bytes == path.stat().st_size < len(DOCUMENT) / 10
    assert gzip.decompress(path.read_bytes()) == DOCUMENT
    assert store.read(SHA) == DOCUMENT
    with store.open(SHA, compressed=True) as stream:
        assert gzip.decompress(stream.read()) == DOCUMENT
    assert COMPRESSED_ENCODING == "gzip"
    assert store.exists(SHA) and store.size(SHA) == len(DOCUMENT) and store.stored_size(SHA) == stored.stored_size_bytes
    assert _incoming(store) == []


def test_equal_content_gives_equal_files_and_is_stored_once(store, tmp_path):
    other = FileArtifactStore(tmp_path / "other")
    store.put(DOCUMENT)
    other.put(DOCUMENT)
    assert store.path(SHA).read_bytes() == other.path(SHA).read_bytes()  # no name, no timestamp in the gzip header
    again = store.put(DOCUMENT, SHA)
    assert not again.created and again.size_bytes == len(DOCUMENT)


def test_a_streamed_write_is_invisible_until_committed(store):
    with store.writer(SHA) as writer:
        for start in range(0, len(DOCUMENT), 1000):
            writer.write(DOCUMENT[start : start + 1000])
        assert not store.exists(SHA) and len(_incoming(store)) == 1
        stored = writer.commit()
    assert stored.created and store.read(SHA) == DOCUMENT and _incoming(store) == []


def test_content_that_hashes_otherwise_is_rejected_and_leaves_nothing(store):
    wrong = "0" * 64
    with pytest.raises(ArtifactHashMismatch) as raised:
        store.put(DOCUMENT, wrong)
    assert (raised.value.expected, raised.value.actual) == (wrong, SHA)
    assert not store.exists(wrong) and not store.exists(SHA) and _incoming(store) == []


def test_a_write_over_the_limit_is_aborted(store):
    writer = store.writer(SHA, max_bytes=len(DOCUMENT) - 1)
    writer.write(DOCUMENT[:100])
    with pytest.raises(ArtifactTooLarge):
        writer.write(DOCUMENT[100:])
    assert _incoming(store) == [] and not store.exists(SHA)
    assert store.put(DOCUMENT, max_bytes=len(DOCUMENT)).created


def test_an_abandoned_write_leaves_nothing(store):
    with pytest.raises(RuntimeError):
        with store.writer(SHA) as writer:
            writer.write(DOCUMENT[:500])
            raise RuntimeError("the upload broke off")
    assert _incoming(store) == [] and not store.exists(SHA)
    writer.abort()  # again: nothing happens


def test_concurrent_writers_of_one_hash_store_it_once(store):
    barrier = threading.Barrier(8)
    results, errors = [], []

    def write():
        try:
            with store.writer(SHA) as writer:
                writer.write(DOCUMENT)
                barrier.wait(timeout=10)
                results.append(writer.commit())
        except Exception as error:  # handed to the test
            errors.append(error)

    threads = [threading.Thread(target=write) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert errors == [] and len(results) == 8
    assert any(result.created for result in results)
    assert store.read(SHA) == DOCUMENT and _incoming(store) == []


def test_readers_never_see_a_partial_artifact(store):
    stop = threading.Event()
    seen = []

    def read():
        while not stop.is_set():
            try:
                seen.append(hashlib.sha256(store.read(SHA)).hexdigest())
            except ArtifactNotFound:
                pass
            except PermissionError:
                assert os.name == "nt"  # Windows refuses to open a file while its deletion is pending

    reader = threading.Thread(target=read)
    reader.start()
    try:
        for _ in range(20):
            store.put(DOCUMENT)
            try:
                store.delete(SHA)
            except PermissionError:
                pass  # Windows: the reader has the file open
    finally:
        stop.set()
        reader.join(timeout=10)
    assert set(seen) <= {SHA}


def test_missing_artifacts(store):
    missing = "1" * 64
    for call in (store.read, store.size, store.stored_size, lambda sha: store.open(sha, compressed=True)):
        with pytest.raises(ArtifactNotFound):
            call(missing)
    assert not store.exists(missing) and not store.delete(missing)
    store.put(DOCUMENT)
    assert store.delete(SHA) and not store.exists(SHA)


@pytest.mark.parametrize("address", ["../../etc/passwd", "A" * 64, "a" * 63, "g" * 64, ""])
def test_only_hashes_are_addresses(store, address):
    with pytest.raises(ValueError):
        store.path(address)
    with pytest.raises(ValueError):
        store.writer(address)


def test_stale_unfinished_writes_are_removed_when_the_store_opens(tmp_path):
    root = tmp_path / "artifacts"
    FileArtifactStore(root)
    stale, fresh = root / INCOMING_FOLDER / "stale.tmp", root / INCOMING_FOLDER / "fresh.tmp"
    stale.write_bytes(b"x")
    fresh.write_bytes(b"y")
    old = time.time() - 7200
    os.utime(stale, (old, old))
    FileArtifactStore(root)
    assert not stale.exists() and fresh.exists()


def _age(store, sha256, seconds):
    then = time.time() - seconds
    os.utime(store.path(sha256), (then, then))


def test_stored_hashes_lists_the_files_older_than_the_age(store):
    old, young = store.put(b'{"old":true}').sha256, store.put(b'{"young":true}').sha256
    _age(store, old, 7200)
    _age(store, young, 60)
    assert list(store.stored_hashes(3600)) == [old]
    assert sorted(store.stored_hashes(30)) == sorted([old, young])


def test_stored_hashes_skips_unfinished_writes_and_foreign_files(store):
    stored = store.put(DOCUMENT).sha256
    _age(store, stored, 7200)
    old = time.time() - 7200
    # another folder for the upper case name: Windows file systems ignore case, so in SHA's folder it would be SHA's own file
    strays = [store.incoming / f"{'b' * 64}.gz", store.root / SHA[:2] / SHA[2:4] / "notes.gz", store.root / "zz" / "yy" / f"{'c' * 64}.gz", store.root / "dd" / "dd" / f"{'D' * 64}.gz"]
    for stray in strays:
        stray.parent.mkdir(parents=True, exist_ok=True)
        stray.write_bytes(b"x")
        os.utime(stray, (old, old))
    assert list(store.stored_hashes(3600)) == [stored]


def test_files_can_be_deleted_while_stored_hashes_iterates(store):
    hashes = [store.put(f'{{"n":{n}}}'.encode()).sha256 for n in range(5)]
    for sha256 in hashes:
        _age(store, sha256, 7200)
    seen = []
    for sha256 in store.stored_hashes(3600):
        seen.append(sha256)
        store.delete(sha256)
    assert sorted(seen) == sorted(hashes) and list(store.stored_hashes(0)) == []


def test_stored_hashes_of_an_empty_store(store):
    assert list(store.stored_hashes()) == []


def test_empty_content(store):
    stored = store.put(b"")
    assert stored.sha256 == hashlib.sha256(b"").hexdigest() and store.read(stored.sha256) == b"" and store.size(stored.sha256) == 0
