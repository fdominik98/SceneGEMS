"""Which image fingerprints the control node requires, of a job and of a worker node.

The control node's required set is the image fingerprints of the release it runs, read once at
start from its release.json (cluster/release). The deployment tool installs the same
release's images on every worker node, so a worker node of the control node's release matches. Out of date is
per component (cluster/fingerprints/components.py): a component whose images differ from the
release is stale and unusable on that worker node, while the worker node's other components keep working.

A submission without fingerprints gets the expected ones of the images of its required components;
a submission that names fingerprints keeps them (a campaign's pinned set, Phase 4).

Every fingerprint map here is keyed by image repository (cluster/fingerprints/comparison.py): a
release tags its images with its revision, so the control node's tag, a worker node's and that of a campaign
pinned under an older release may differ while the image is the same.
"""

import logging
from enum import Enum
from pathlib import Path
from typing import Callable, Collection, Dict, FrozenSet, List, Optional

import anyio

from scenegems_tool.cluster.fingerprints.comparison import FingerprintMismatch, by_repository, find_mismatches, fingerprints_of, repositories
from scenegems_tool.cluster.fingerprints.components import component_images, images_of
from scenegems_tool.cluster.protocol.jobs import JobSubmission
from scenegems_tool.cluster.release.manifest import read_release
from scenegems_tool.persistence.stores import WorkerNodeRecord

logger = logging.getLogger(__name__)


class ListingState(str, Enum):
    PENDING = "pending"  # being read; nothing is leased meanwhile
    READY = "ready"
    FAILED = "failed"  # nothing is leased until the control node is restarted with a readable release


class ExpectedFingerprints:
    """The control node's expected image fingerprints, read once in the background."""

    def __init__(self, compute: Callable[[], Dict[str, str]]):
        self._compute = compute
        self._listing: Optional[Dict[str, str]] = None
        self.state = ListingState.PENDING
        self.error: Optional[str] = None

    @classmethod
    def of_release(cls, manifest: Optional[Path]) -> "ExpectedFingerprints":
        def read() -> Dict[str, str]:
            if manifest is None:
                raise ValueError("SCENEGEMS_RELEASE_MANIFEST is not set, so the control node knows no release")
            return read_release(manifest).fingerprints()

        return cls(read)

    @classmethod
    def fixed(cls, listing: Dict[str, str]) -> "ExpectedFingerprints":
        expected = cls(lambda: dict(listing))
        expected._set(dict(listing))
        return expected

    def current(self) -> Optional[Dict[str, str]]:
        """Image repository to fingerprint, or None while the listing is not available."""
        return self._listing

    async def load(self) -> None:
        if self.state == ListingState.READY:
            return
        try:
            listing = await anyio.to_thread.run_sync(self._compute)
        except Exception as error:  # the control node keeps serving, but leases nothing
            self.state, self.error = ListingState.FAILED, f"{type(error).__name__}: {error}"
            logger.error("Could not read the expected image fingerprints, so no job will be leased: %s", self.error)
            return
        if not listing:
            self.state, self.error = ListingState.FAILED, "the release lists no fingerprinted image"
            logger.error("The release lists no fingerprinted image, so no job will be leased")
            return
        self._set(listing)
        logger.info("Expected image fingerprints ready for %d images", len(listing))

    def _set(self, listing: Dict[str, str]) -> None:
        self._listing = by_repository(listing)
        self.state, self.error = ListingState.READY, None


def with_required_fingerprints(submission: JobSubmission, expected: Dict[str, str]) -> JobSubmission:
    """The submission with the expected fingerprints of its required components' images, unless it names its own; either keyed by repository."""
    if submission.requirements.fingerprints:
        required = by_repository(submission.requirements.fingerprints)
    else:
        required = fingerprints_of(images_of(submission.requirements.components), expected)
    return submission.model_copy(update={"requirements": submission.requirements.model_copy(update={"fingerprints": required})})


def worker_node_mismatches(worker_node: WorkerNodeRecord, expected: Dict[str, str]) -> List[FingerprintMismatch]:
    """The images the worker node's components need whose fingerprint differs from the expected one; empty when up to date."""
    return find_mismatches(worker_node.fingerprints, fingerprints_of(images_of(worker_node.components), expected))


def stale_components(components: Collection[str], mismatches: Collection[FingerprintMismatch]) -> FrozenSet[str]:
    """The components that need an image among the mismatches: unusable on the worker node until it is updated."""
    stale_images = {mismatch.image for mismatch in mismatches}
    catalog = component_images()
    return frozenset(component for component in components if stale_images & set(repositories(catalog.get(component, ()))))
