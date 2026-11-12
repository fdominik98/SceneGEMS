import datetime
import json
from pathlib import Path

import pytest

from scenegems_tool.cluster.release.bundle import STACK_COMPOSE_FILES, InspectedImage, build_bundle
from scenegems_tool.cluster.release.manifest import FINGERPRINT_LABEL, ReleaseError, read_release
from scenegems_tool.cluster.release.roles import POSTGRES_IMAGE, role_images, scenegems_roles

REPO_ROOT = Path(__file__).resolve().parents[6]
NOW = datetime.datetime(2026, 10, 25, 12, 0, tzinfo=datetime.timezone.utc)


def _all_built(tag: str) -> InspectedImage:
    labels = {} if tag == POSTGRES_IMAGE else {FINGERPRINT_LABEL: f"fp-{tag}"}
    return InspectedImage(image_id=f"sha256:{tag}", labels=labels)


class _Tags:
    """Records the docker tag calls."""

    def __init__(self):
        self.calls = []

    def __call__(self, source: str, target: str) -> None:
        self.calls.append((source, target))


def test_the_bundle_holds_the_release_and_the_stacks(tmp_path):
    tags = _Tags()
    release = build_bundle(tmp_path, REPO_ROOT, "abc123", dirty=True, inspect=_all_built, now=NOW, tag=tags)
    assert read_release(tmp_path / "release.json") == release
    assert release.revision == "abc123" and release.dirty and release.created_at == "2026-10-25T12:00:00+00:00"
    assert sorted(release.images) == role_images(scenegems_roles("abc123-dirty"))
    assert release.images[POSTGRES_IMAGE].fingerprint is None
    for role, compose_files in STACK_COMPOSE_FILES.items():
        for compose_file in compose_files:
            stack = tmp_path / "stacks" / scenegems_roles()[role]["stack"] / Path(compose_file).name
            assert stack.read_bytes() == (REPO_ROOT / compose_file).read_bytes()
    assert sorted(path.name for path in (tmp_path / "stacks" / "control_node").iterdir()) == ["docker-compose.yml"], "one file: the control node starts no containers"


def test_the_release_tags_the_latest_builds_with_its_revision(tmp_path):
    tags = _Tags()
    release = build_bundle(tmp_path, REPO_ROOT, "abc123", dirty=False, inspect=_all_built, now=NOW, tag=tags)
    built = [image for image in release.images if image != POSTGRES_IMAGE]
    assert built and all(image.endswith(":abc123") for image in built)
    assert sorted(tags.calls) == sorted((image.replace(":abc123", ":latest"), image) for image in built)
    worker_node = "scenegems-worker-node:abc123"
    assert release.images[worker_node].image_id == "sha256:scenegems-worker-node:latest" and release.images[worker_node].fingerprint == "fp-scenegems-worker-node:latest"
    assert release.roles["worker-node"]["env"]["SCENEGEMS_IMAGE_TAG"] == "abc123" and release.roles["worker-node"]["images"] == [worker_node]


def test_a_dirty_release_tags_its_images_dirty(tmp_path):
    release = build_bundle(tmp_path, REPO_ROOT, "abc123", dirty=True, inspect=_all_built, now=NOW, tag=_Tags())
    assert "scenegems-control-node-api:abc123-dirty" in release.images and release.roles["control-node"]["env"]["SCENEGEMS_IMAGE_TAG"] == "abc123-dirty"


def test_an_older_bundle_is_replaced(tmp_path):
    stale = tmp_path / "stacks" / "old"
    stale.mkdir(parents=True)
    build_bundle(tmp_path, REPO_ROOT, "abc123", dirty=False, inspect=_all_built, now=NOW, tag=_Tags())
    assert not stale.exists()
    assert json.loads((tmp_path / "release.json").read_text(encoding="utf-8"))["revision"] == "abc123"


def test_missing_images_are_named_with_the_way_to_get_them(tmp_path):
    tags = _Tags()
    with pytest.raises(ReleaseError, match="docker pull") as error:
        build_bundle(tmp_path, REPO_ROOT, "abc123", dirty=False, inspect=lambda tag: None, now=NOW, tag=tags)
    assert "scenegems-worker-node:latest" in str(error.value), "the build's name of the image"
    assert not (tmp_path / "release.json").exists() and tags.calls == []


def test_an_image_without_a_fingerprint_label_is_refused(tmp_path):
    def unlabelled(tag):
        return InspectedImage(image_id=f"sha256:{tag}", labels={})

    tags = _Tags()
    with pytest.raises(ReleaseError, match=FINGERPRINT_LABEL):
        build_bundle(tmp_path, REPO_ROOT, "abc123", dirty=False, inspect=unlabelled, now=NOW, tag=tags)
    assert tags.calls == []
