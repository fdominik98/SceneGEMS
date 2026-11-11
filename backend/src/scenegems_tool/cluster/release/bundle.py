"""Write a release bundle from the images built on this machine.

The bundle records each image's ID and fingerprint label as Docker reports them here, so
the deployment tool can tell whether a machine already has the same image, and the
control node can tell whether a worker node runs the images of this release.

./build.sh builds every image as :latest (its stale check reads the label of that tag); the
bundle tags each one with the release's image tag (roles.release_image_tag) and lists it under
that name, so every release names its own images and a machine can hold several releases.
"""

import datetime
import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

from scenegems_tool.cluster.release.manifest import FINGERPRINT_LABEL, RELEASE_FILE, Release, ReleaseError, ReleaseImage, write_release
from scenegems_tool.cluster.release.roles import CONTROL_NODE_COMPOSE_FILE, NAME_PATTERN, POSTGRES_IMAGE, PULLED_IMAGES, release_image_tag, role_images, scenegems_roles
from utils.image_names import DEFAULT_IMAGE_TAG, with_tag

RELEASE_NAME = "scenegems"
STACKS_FOLDER = "stacks"
# The compose files each role's stack is made of, relative to the repository root; they keep their names in the stack
STACK_COMPOSE_FILES: Dict[str, Tuple[str, ...]] = {
    "control-node": (f"deploy/control_node/{CONTROL_NODE_COMPOSE_FILE}",),
    "worker-node": ("deploy/worker_node/docker-compose.yml",),
}


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


def built_image(image: str) -> str:
    """The name ./build.sh built a release image under: its :latest, or the pulled image itself."""
    return image if image in PULLED_IMAGES else with_tag(image, DEFAULT_IMAGE_TAG)


def build_bundle(
    out_dir: Path,
    repo_root: Path,
    revision: str,
    dirty: bool,
    inspect: Callable[[str], Optional[InspectedImage]] = inspect_local_image,
    now: Optional[datetime.datetime] = None,
    tag: Callable[[str, str], None] = tag_local_image,
) -> Release:
    """Tag the built images with the release's image tag, write release.json and stacks/ into out_dir and return the release. Fails if an image is not built here."""
    roles = scenegems_roles(release_image_tag(revision, dirty))
    images: Dict[str, ReleaseImage] = {}
    missing = []
    for image in role_images(roles):
        found = inspect(built_image(image))
        if found is None:
            missing.append(built_image(image))
            continue
        images[image] = ReleaseImage(image_id=found.image_id, fingerprint=found.labels.get(FINGERPRINT_LABEL) or None)
    if missing:
        hint = f"; pull {POSTGRES_IMAGE} with docker pull" if POSTGRES_IMAGE in missing else ""
        raise ReleaseError(f"these images are not on this machine: {', '.join(missing)}. Build them with ./build.sh{hint}")
    unlabelled = [built_image(image) for image, found in images.items() if image not in PULLED_IMAGES and found.fingerprint is None]
    if unlabelled:
        raise ReleaseError(f"these images carry no {FINGERPRINT_LABEL} label: {', '.join(unlabelled)}. Rebuild them with ./build.sh")
    for image in images:
        if built_image(image) != image:
            tag(built_image(image), image)

    out_dir.mkdir(parents=True, exist_ok=True)
    stacks = out_dir / STACKS_FOLDER
    if stacks.exists():
        shutil.rmtree(stacks)
    for role, compose_files in STACK_COMPOSE_FILES.items():
        target = stacks / roles[role]["stack"]
        target.mkdir(parents=True)
        for compose_file in compose_files:
            shutil.copyfile(repo_root / compose_file, target / Path(compose_file).name)

    created = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat(timespec="seconds")
    release = Release(name=RELEASE_NAME, revision=revision, dirty=dirty, created_at=created, images=images, roles=roles, name_pattern=NAME_PATTERN)
    write_release(out_dir / RELEASE_FILE, release)
    return release
