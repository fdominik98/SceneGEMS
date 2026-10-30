import io
import uuid

import pytest

from scenegems_tool.cluster.fingerprints.labels import FINGERPRINT_LABEL, read_image_fingerprints


class _Image:
    def __init__(self, tags, labels):
        self.tags = tags
        self.labels = labels


class _Client:
    def __init__(self, images):
        self.images = self
        self._images = images

    def list(self):
        return self._images


def test_reads_the_label_of_every_image_by_repository():
    client = _Client([_Image(["a:latest", "a:v1"], {FINGERPRINT_LABEL: "abc"}), _Image(["b:latest"], {FINGERPRINT_LABEL: "def"})])
    assert read_image_fingerprints(client, tag="latest") == {"a": "abc", "b": "def"}


def test_the_image_of_the_node_s_tag_wins_over_other_tags_of_its_repository():
    client = _Client([_Image(["a:latest"], {FINGERPRINT_LABEL: "old"}), _Image(["a:rev2", "a:x"], {FINGERPRINT_LABEL: "new"})])
    assert read_image_fingerprints(client, tag="rev2") == {"a": "new"}
    assert read_image_fingerprints(client, tag="latest") == {"a": "old"}


def test_a_repository_only_under_other_tags_still_reports_its_fingerprint():
    client = _Client([_Image(["a:rev1"], {FINGERPRINT_LABEL: "abc"})])
    assert read_image_fingerprints(client, tag="rev2") == {"a": "abc"}


def test_the_tag_defaults_to_scenegems_image_tag(monkeypatch):
    client = _Client([_Image(["a:latest"], {FINGERPRINT_LABEL: "old"}), _Image(["a:rev2"], {FINGERPRINT_LABEL: "new"})])
    monkeypatch.setenv("SCENEGEMS_IMAGE_TAG", "rev2")
    assert read_image_fingerprints(client) == {"a": "new"}


def test_images_without_the_label_or_a_tag_are_skipped():
    client = _Client([_Image(["plain:latest"], {}), _Image(["none:latest"], None), _Image([], {FINGERPRINT_LABEL: "abc"})])
    assert read_image_fingerprints(client) == {}


@pytest.mark.docker
def test_reads_the_label_from_a_real_image():
    import docker

    client = docker.from_env()
    tag = f"scenegems-fingerprint-test:{uuid.uuid4().hex[:8]}"
    dockerfile = io.BytesIO(f"FROM scratch\nLABEL {FINGERPRINT_LABEL}=deadbeef\n".encode())
    client.images.build(fileobj=dockerfile, tag=tag)
    try:
        assert read_image_fingerprints(client, tag=tag.split(":")[1])["scenegems-fingerprint-test"] == "deadbeef"
    finally:
        client.images.remove(tag, force=True)
