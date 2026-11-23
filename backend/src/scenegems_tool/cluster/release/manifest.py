"""The release file, release.json: the revision, its images, its Helm chart and the roles of the cluster.

The deployment tool reads the images, the chart and the roles to install a cluster; the control node reads the
image fingerprints to know which worker nodes are up to date (cluster/control_node/scheduling). The file
is JSON with a format number, so a reader of another format fails with a clear message.

Format 2 adds the chart: the folder of the bundle that holds it, the Helm release and namespace it is installed
as, and the chart values every cluster gets (roles.py has the rules for building a values file). A cluster is
installed from the chart only: the roles have no compose fields and the bundle no compose stacks.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

RELEASE_FILE = "release.json"
RELEASE_FORMAT = 2
FINGERPRINT_LABEL = "org.scenegems.fingerprint"
CHART_FOLDER = "chart"  # the chart's folder in the bundle, beside release.json
CHART_HELM_RELEASE = "scenegems"
CHART_NAMESPACE = "scenegems"
_FOLDER = re.compile(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*")  # relative, forward slashes
_DNS_LABEL = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?")
_HELM_RELEASE_MAX = 53  # Helm's limit for a release name
_NAMESPACE_MAX = 63


class ReleaseError(ValueError):
    """The release file is missing, malformed or of another format."""


@dataclass(frozen=True)
class ReleaseImage:
    """One image of the release, as built on the machine that made the bundle."""

    image_id: str
    fingerprint: Optional[str] = None  # None for images SceneGEMS does not build (postgres)

    def to_json(self) -> Dict[str, Any]:
        labels = {FINGERPRINT_LABEL: self.fingerprint} if self.fingerprint else {}
        return {"id": self.image_id, "labels": labels}

    @classmethod
    def from_json(cls, tag: str, data: Any) -> "ReleaseImage":
        if not isinstance(data, dict) or not isinstance(data.get("id"), str) or not data["id"]:
            raise ReleaseError(f"image {tag!r} needs an id")
        labels = data.get("labels") or {}
        if not isinstance(labels, dict):
            raise ReleaseError(f"labels of image {tag!r} must be an object")
        fingerprint = labels.get(FINGERPRINT_LABEL)
        return cls(image_id=data["id"], fingerprint=fingerprint if isinstance(fingerprint, str) and fingerprint else None)


@dataclass(frozen=True)
class ReleaseChart:
    """The release's Helm chart: its folder in the bundle, the Helm release and namespace a cluster installs it as, and the values every cluster gets.

    The values are a template like a role's values: text may use {cluster} and {release.revision} (roles.py).
    """

    folder: str = CHART_FOLDER
    helm_release: str = CHART_HELM_RELEASE
    namespace: str = CHART_NAMESPACE
    values: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> Dict[str, Any]:
        return {"folder": self.folder, "helm_release": self.helm_release, "namespace": self.namespace, "values": self.values}

    @classmethod
    def from_json(cls, data: Any) -> "ReleaseChart":
        if not isinstance(data, dict):
            raise ReleaseError("the release needs a chart object")
        folder = data.get("folder")
        if not isinstance(folder, str) or not _FOLDER.fullmatch(folder) or ".." in folder.split("/"):
            raise ReleaseError(f"the chart's folder {folder!r} must be a relative path inside the bundle")
        for key, limit in (("helm_release", _HELM_RELEASE_MAX), ("namespace", _NAMESPACE_MAX)):
            value = data.get(key)
            if not isinstance(value, str) or len(value) > limit or not _DNS_LABEL.fullmatch(value):
                raise ReleaseError(f"the chart's {key} {value!r} must be lowercase letters, digits and hyphens, at most {limit} characters")
        values = data.get("values", {})
        if not isinstance(values, dict):
            raise ReleaseError("the chart's values must be an object")
        return cls(folder=folder, helm_release=data["helm_release"], namespace=data["namespace"], values=values)


@dataclass(frozen=True)
class Release:
    name: str
    revision: str
    dirty: bool  # built from uncommitted changes; the fingerprints still identify the images
    created_at: str
    images: Dict[str, ReleaseImage]  # image tag to image
    roles: Dict[str, Any] = field(default_factory=dict)  # see roles.py
    name_pattern: str = ""  # regular expression for cluster ids and instance names
    chart: ReleaseChart = field(default_factory=ReleaseChart)

    def fingerprints(self) -> Dict[str, str]:
        """Image tag to fingerprint, for the images SceneGEMS builds."""
        return {tag: image.fingerprint for tag, image in self.images.items() if image.fingerprint}

    def to_json(self) -> Dict[str, Any]:
        return {
            "format": RELEASE_FORMAT,
            "name": self.name,
            "revision": self.revision,
            "dirty": self.dirty,
            "created_at": self.created_at,
            "images": {tag: image.to_json() for tag, image in sorted(self.images.items())},
            "chart": self.chart.to_json(),
            "roles": self.roles,
            "name_pattern": self.name_pattern,
        }

    @classmethod
    def from_json(cls, data: Any) -> "Release":
        if not isinstance(data, dict):
            raise ReleaseError("the release file must hold a JSON object")
        if data.get("format") != RELEASE_FORMAT:
            raise ReleaseError(f"release format {data.get('format')!r} is not supported; this SceneGEMS reads format {RELEASE_FORMAT}. Build the bundle again with ./build.sh --release <folder>")
        images = data.get("images")
        if not isinstance(images, dict) or not images:
            raise ReleaseError("the release lists no images")
        for key in ("name", "revision", "created_at"):
            if not isinstance(data.get(key), str) or not data[key]:
                raise ReleaseError(f"the release needs {key!r}")
        roles = data.get("roles", {})
        if not isinstance(roles, dict):
            raise ReleaseError("roles must be an object")
        return cls(
            name=data["name"],
            revision=data["revision"],
            dirty=bool(data.get("dirty", False)),
            created_at=data["created_at"],
            images={tag: ReleaseImage.from_json(tag, image) for tag, image in images.items()},
            roles=roles,
            name_pattern=str(data.get("name_pattern") or ""),
            chart=ReleaseChart.from_json(data.get("chart")),
        )


def read_release(path: Path) -> Release:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise ReleaseError(f"cannot read the release file {path}: {error.strerror or error}") from error
    try:
        data = json.loads(text)
    except ValueError as error:
        raise ReleaseError(f"the release file {path} is not JSON: {error}") from error
    return Release.from_json(data)


def write_release(path: Path, release: Release) -> None:
    Path(path).write_text(json.dumps(release.to_json(), indent=2) + "\n", encoding="utf-8", newline="\n")
