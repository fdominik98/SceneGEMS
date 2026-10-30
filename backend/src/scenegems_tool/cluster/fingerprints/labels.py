"""The fingerprints the images on this machine carry, read from their labels."""

from typing import Any, Dict, Optional

from utils.image_names import image_repository, image_tag

FINGERPRINT_LABEL = "org.scenegems.fingerprint"


def read_image_fingerprints(client: Optional[Any] = None, tag: Optional[str] = None) -> Dict[str, str]:
    """Image repository to fingerprint for every local image with the label; this is the node's Hello.fingerprints.

    The node runs its images under one tag (SCENEGEMS_IMAGE_TAG, or tag), so a repository it has
    under that tag reports that image; a repository it has only under other tags reports one of them,
    the first by name, so a tag change alone never drops a fingerprint.
    """
    if client is None:
        import docker

        client = docker.from_env()
    tag = tag or image_tag()
    names: Dict[str, str] = {}
    for image in client.images.list():
        fingerprint = (image.labels or {}).get(FINGERPRINT_LABEL)
        if fingerprint:
            names.update((name, fingerprint) for name in image.tags)
    fingerprints: Dict[str, str] = {}
    for name, fingerprint in sorted(names.items()):
        repository = image_repository(name)
        if repository not in fingerprints or name == f"{repository}:{tag}":
            fingerprints[repository] = fingerprint
    return fingerprints
