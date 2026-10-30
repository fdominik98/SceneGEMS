"""Names of the images SceneGEMS builds: one tag for all of them, and the repository a name compares by.

Every image SceneGEMS builds is named <repository>:<tag>, the tag from SCENEGEMS_IMAGE_TAG. Without it
the tag is latest, what ./build.sh builds, so the workbench and the tests name the local builds. A
release tags its images with its revision (cluster/release/bundle.py) and its roles pass that tag to
the machines, so a master and its nodes name the release's images. Image fingerprints compare by
repository, so a tag change never hides a fingerprint (cluster/fingerprints/comparison.py).

The tag is read once, when a module that names an image is imported.
"""

import os
import re
from typing import Optional

IMAGE_TAG_VARIABLE = "SCENEGEMS_IMAGE_TAG"
DEFAULT_IMAGE_TAG = "latest"
_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")  # Docker's tag grammar


def image_tag() -> str:
    """The tag of the images SceneGEMS builds: SCENEGEMS_IMAGE_TAG when set and not empty, else latest. A malformed tag fails."""
    tag = os.environ.get(IMAGE_TAG_VARIABLE, "").strip() or DEFAULT_IMAGE_TAG
    if not _TAG.fullmatch(tag):
        raise ValueError(f"{IMAGE_TAG_VARIABLE}={tag!r} is not a Docker image tag")
    return tag


def tagged(repository: str, tag: Optional[str] = None) -> str:
    """The image name of a repository with the tag, by default the one of SCENEGEMS_IMAGE_TAG."""
    return f"{repository}:{tag or image_tag()}"


def image_repository(name: str) -> str:
    """The repository of an image name: the name without its tag and digest (a registry's port stays)."""
    name = name.split("@", 1)[0]
    colon = name.rfind(":")
    return name[:colon] if colon > name.rfind("/") else name


def with_tag(name: str, tag: str) -> str:
    """The same repository with another tag."""
    return tagged(image_repository(name), tag)
