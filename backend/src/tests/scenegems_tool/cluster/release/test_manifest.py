import json

import pytest

from scenegems_tool.cluster.release.manifest import FINGERPRINT_LABEL, RELEASE_FORMAT, Release, ReleaseError, ReleaseImage, read_release, write_release


def _release(**changes) -> Release:
    values = dict(
        name="scenegems",
        revision="abc123",
        dirty=False,
        created_at="2026-10-25T12:00:00+00:00",
        images={"scenegems-worker-node:latest": ReleaseImage("sha256:1", "fp-worker-node"), "postgres:16.10-alpine": ReleaseImage("sha256:2")},
        roles={"worker-node": {"count": "many"}},
        name_pattern="^[a-z]+$",
    )
    values.update(changes)
    return Release(**values)


def test_a_release_round_trips(tmp_path):
    path = tmp_path / "release.json"
    write_release(path, _release())
    assert read_release(path) == _release()


def test_the_fingerprint_is_stored_as_the_image_label(tmp_path):
    path = tmp_path / "release.json"
    write_release(path, _release())
    images = json.loads(path.read_text(encoding="utf-8"))["images"]
    assert images["scenegems-worker-node:latest"] == {"id": "sha256:1", "labels": {FINGERPRINT_LABEL: "fp-worker-node"}}
    assert images["postgres:16.10-alpine"] == {"id": "sha256:2", "labels": {}}


def test_fingerprints_leave_out_images_without_one():
    assert _release().fingerprints() == {"scenegems-worker-node:latest": "fp-worker-node"}


def test_another_format_is_refused():
    data = _release().to_json()
    data["format"] = RELEASE_FORMAT + 1
    with pytest.raises(ReleaseError, match="not supported"):
        Release.from_json(data)


@pytest.mark.parametrize("change", [{"images": {}}, {"revision": ""}, {"images": {"a:latest": {"labels": {}}}}, {"roles": []}])
def test_incomplete_releases_are_refused(change):
    data = _release().to_json()
    data.update(change)
    with pytest.raises(ReleaseError):
        Release.from_json(data)


def test_a_missing_or_broken_file_says_which(tmp_path):
    with pytest.raises(ReleaseError, match="cannot read"):
        read_release(tmp_path / "release.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    with pytest.raises(ReleaseError, match="not JSON"):
        read_release(broken)
