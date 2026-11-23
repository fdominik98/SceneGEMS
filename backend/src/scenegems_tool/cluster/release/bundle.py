"""Write a release bundle from the images built on this machine.

The bundle records each image's ID and fingerprint label as Docker reports them here, so
the deployment tool can tell whether a machine already has the same image, and the
control node can tell whether a worker node runs the images of this release.

./build.sh builds every image as :latest (its stale check reads the label of that tag); the
bundle tags each one with the release's image tag (roles.release_image_tag) and lists it under
that name, so every release names its own images and a machine can hold several releases.

The bundle is release.json and the Helm chart in chart/ (deploy/kubernetes/chart, with a copy of release.json the
chart puts into a ConfigMap, since a chart reads only its own files). Images built under another tag than latest
(a test's own tag) can be bundled under that tag as they are (build_bundle's built_tag and image_tag).
"""

import datetime
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

from scenegems_tool.cluster.release.manifest import FINGERPRINT_LABEL, RELEASE_FILE, Release, ReleaseError, ReleaseImage, write_release
from scenegems_tool.cluster.release.roles import NAME_PATTERN, POSTGRES_IMAGE, PULLED_IMAGES, release_image_tag, role_images, scenegems_chart, scenegems_roles
from utils.image_names import DEFAULT_IMAGE_TAG, with_tag

RELEASE_NAME = "scenegems"
CHART_SOURCE = "deploy/kubernetes/chart"  # relative to the repository root; the bundle holds it as the release's chart folder
FORMER_STACKS_FOLDER = "stacks"  # the compose stacks of bundles before the chart; removed from a folder a bundle is written into again


@dataclass(frozen=True)
class InspectedImage:
    image_id: str
    labels: Dict[str, str]


def inspect_local_image(tag: str) -> Optional[InspectedImage]:
    """The local image of that tag, or None when Docker has none."""
    completed = subprocess.run(["docker", "image", "inspect", "--format", "{{json .}}", tag], capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        return None
    data = json.loads(completed.stdout)
    labels = (data.get("Config") or {}).get("Labels") or {}
    return InspectedImage(image_id=data["Id"], labels=dict(labels))


def tag_local_image(source: str, target: str) -> None:
    """Give the local image source the name target as well (docker tag)."""
    subprocess.run(["docker", "tag", source, target], capture_output=True, text=True, check=True)


def built_image(image: str, built_tag: str = DEFAULT_IMAGE_TAG) -> str:
    """The name a release image was built under: its repository with built_tag (./build.sh builds :latest), or the pulled image itself."""
    return image if image in PULLED_IMAGES else with_tag(image, built_tag)


def build_bundle(
    out_dir: Path,
    repo_root: Path,
    revision: str,
    dirty: bool,
    inspect: Callable[[str], Optional[InspectedImage]] = inspect_local_image,
    now: Optional[datetime.datetime] = None,
    tag: Callable[[str, str], None] = tag_local_image,
    image_tag: Optional[str] = None,
    built_tag: str = DEFAULT_IMAGE_TAG,
) -> Release:
    """Tag the built images with the release's image tag, write release.json and chart/ into out_dir and return the release. Fails if an image is not built here.

    The images are found under built_tag (./build.sh's latest) and named with image_tag, by default the revision's
    (release_image_tag); when both are the same tag the images keep their names and nothing is tagged.
    """
    image_tag = image_tag or release_image_tag(revision, dirty)
    roles = scenegems_roles(image_tag)
    chart = scenegems_chart(image_tag)
    images: Dict[str, ReleaseImage] = {}
    missing = []
    for image in role_images(roles):
        found = inspect(built_image(image, built_tag))
        if found is None:
            missing.append(built_image(image, built_tag))
            continue
        images[image] = ReleaseImage(image_id=found.image_id, fingerprint=found.labels.get(FINGERPRINT_LABEL) or None)
    if missing:
        hint = f"; pull {POSTGRES_IMAGE} with docker pull" if POSTGRES_IMAGE in missing else ""
        raise ReleaseError(f"these images are not on this machine: {', '.join(missing)}. Build them with ./build.sh{hint}")
    unlabelled = [built_image(image, built_tag) for image, found in images.items() if image not in PULLED_IMAGES and found.fingerprint is None]
    if unlabelled:
        raise ReleaseError(f"these images carry no {FINGERPRINT_LABEL} label: {', '.join(unlabelled)}. Rebuild them with ./build.sh")
    for image in images:
        if built_image(image, built_tag) != image:
            tag(built_image(image, built_tag), image)

    out_dir.mkdir(parents=True, exist_ok=True)
    if (out_dir / FORMER_STACKS_FOLDER).is_dir():
        shutil.rmtree(out_dir / FORMER_STACKS_FOLDER)
    chart_dir = out_dir / chart.folder
    if chart_dir.exists():
        shutil.rmtree(chart_dir)
    shutil.copytree(repo_root / CHART_SOURCE, chart_dir)

    created = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat(timespec="seconds")
    release = Release(name=RELEASE_NAME, revision=revision, dirty=dirty, created_at=created, images=images, roles=roles, name_pattern=NAME_PATTERN, chart=chart)
    write_release(out_dir / RELEASE_FILE, release)
    write_release(chart_dir / RELEASE_FILE, release)
    return release
