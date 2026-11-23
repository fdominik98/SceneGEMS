"""The fingerprints a worker node reports come from the release manifest it is deployed with, keyed as the control node compares them."""

import pytest

from scenegems_tool.cluster.fingerprints.comparison import find_mismatches
from scenegems_tool.cluster.fingerprints.labels import FINGERPRINT_LABEL, release_fingerprints
from scenegems_tool.cluster.release.manifest import Release, ReleaseError, ReleaseImage, read_release, write_release


def write_manifest(path, images) -> None:
    write_release(path, Release(name="scenegems", revision="abc123", dirty=False, created_at="2026-11-16T12:00:00+00:00", images=images))


def test_every_fingerprinted_image_of_the_release_is_reported_by_repository(tmp_path):
    manifest = tmp_path / "release.json"
    write_manifest(
        manifest,
        {
            "scenegems-simulation-subsystem:abc123": ReleaseImage("sha256:1", "fp-simulation"),
            "scenegems-monitoring-subsystem:abc123": ReleaseImage("sha256:2", "fp-monitoring"),
            "postgres:16.10-alpine": ReleaseImage("sha256:3"),  # not built by SceneGEMS: no fingerprint
        },
    )
    assert release_fingerprints(manifest) == {"scenegems-simulation-subsystem": "fp-simulation", "scenegems-monitoring-subsystem": "fp-monitoring"}
    assert release_fingerprints(str(manifest)) == release_fingerprints(manifest)


def test_a_worker_node_of_the_control_nodes_release_matches_it(tmp_path):
    """The control node requires the fingerprints of its own release.json (fingerprint_policy.ExpectedFingerprints.of_release), keyed by tag."""
    manifest = tmp_path / "release.json"
    write_manifest(manifest, {"scenegems-simulation-subsystem:abc123": ReleaseImage("sha256:1", "fp-simulation")})
    required = read_release(manifest).fingerprints()
    assert find_mismatches(release_fingerprints(manifest), required) == []
    assert find_mismatches({"scenegems-simulation-subsystem": "fp-older"}, required)[0].image == "scenegems-simulation-subsystem"


def test_an_unreadable_manifest_fails_with_the_releases_error(tmp_path):
    with pytest.raises(ReleaseError, match="cannot read the release file"):
        release_fingerprints(tmp_path / "missing.json")
    broken = tmp_path / "release.json"
    broken.write_text('{"format": 1}', encoding="utf-8")
    with pytest.raises(ReleaseError, match="format"):
        release_fingerprints(broken)


def test_the_label_is_the_one_the_release_records():
    assert FINGERPRINT_LABEL == "org.scenegems.fingerprint"
