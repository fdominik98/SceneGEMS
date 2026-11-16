"""The fingerprints a worker node reports: those of the release it is deployed with.

A worker node in a Kubernetes cluster has no image store of its own to read labels from. Its pods run the images
the chart was given, which are the release's, so its Hello reports the image fingerprints of the release manifest
(release.json) it is deployed with, keyed by image repository as the control node compares them
(comparison.by_repository). The fingerprint is still the label org.scenegems.fingerprint of each built image,
which the release records when it is built (cluster/release/bundle.py).
"""

from pathlib import Path
from typing import Dict, Union

from scenegems_tool.cluster.fingerprints.comparison import by_repository
from scenegems_tool.cluster.release.manifest import FINGERPRINT_LABEL, read_release

__all__ = ["FINGERPRINT_LABEL", "release_fingerprints"]


def release_fingerprints(manifest: Union[str, Path]) -> Dict[str, str]:
    """Image repository to fingerprint for every fingerprinted image of the release; ReleaseError when the file cannot be read."""
    return by_repository(read_release(Path(manifest)).fingerprints())
