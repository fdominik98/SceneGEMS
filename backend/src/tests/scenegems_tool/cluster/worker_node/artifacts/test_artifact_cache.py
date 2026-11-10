import hashlib
import os

import pytest

from scenegems_tool.cluster.worker_node.artifacts.artifact_cache import ArtifactCache


def _entry(text: str):
    data = text.encode()
    return hashlib.sha256(data).hexdigest(), data


A, B, C = _entry("a" * 100), _entry("b" * 100), _entry("c" * 100)


def _age(cache, sha256, seconds_ago):
    stamp = os.path.getmtime(cache.path(sha256)) - seconds_ago
    os.utime(cache.path(sha256), (stamp, stamp))


def test_a_cached_artifact_is_returned_after_its_hash_check(tmp_path):
    cache = ArtifactCache(tmp_path / "cache", max_bytes=1000)
    assert cache.get(A[0]) is None
    assert cache.put(*A)
    assert cache.get(A[0]) == A[1] and cache.size_bytes == 100


def test_a_damaged_entry_is_removed_and_counts_as_a_miss(tmp_path):
    cache = ArtifactCache(tmp_path / "cache", max_bytes=1000)
    cache.put(*A)
    cache.path(A[0]).write_bytes(b"tampered")
    assert cache.get(A[0]) is None and not cache.path(A[0]).exists() and cache.size_bytes == 0


def test_the_least_recently_used_entries_go_when_the_cache_is_full(tmp_path):
    cache = ArtifactCache(tmp_path / "cache", max_bytes=250)
    cache.put(*A)
    cache.put(*B)
    _age(cache, A[0], 200)
    _age(cache, B[0], 100)
    assert cache.get(A[0]) == A[1]  # a hit renews A, so B is now the oldest
    cache.put(*C)
    assert cache.get(B[0]) is None and cache.get(A[0]) == A[1] and cache.get(C[0]) == C[1]
    assert cache.size_bytes == 200


def test_an_artifact_larger_than_the_cache_is_not_cached(tmp_path):
    cache = ArtifactCache(tmp_path / "cache", max_bytes=50)
    assert not cache.put(*A) and cache.get(A[0]) is None


def test_entries_survive_a_restart_and_leftovers_are_removed(tmp_path):
    cache = ArtifactCache(tmp_path / "cache", max_bytes=1000)
    cache.put(*A)
    (tmp_path / "cache" / ".abc-123.tmp").write_bytes(b"half")
    reopened = ArtifactCache(tmp_path / "cache", max_bytes=1000)
    assert reopened.get(A[0]) == A[1] and reopened.size_bytes == 100
    assert not (tmp_path / "cache" / ".abc-123.tmp").exists()
    smaller = ArtifactCache(tmp_path / "cache", max_bytes=10)  # a lower bound applies at once
    assert smaller.size_bytes == 0


def test_only_hashes_name_entries(tmp_path):
    cache = ArtifactCache(tmp_path / "cache")
    with pytest.raises(ValueError):
        cache.get("../pairing.json")
