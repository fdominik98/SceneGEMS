"""Which image fingerprints the master requires, of a job and of a node.

The master's required set is the image fingerprints of the release it runs, read once at
start from its release.json (cluster/release). The deployment tool installs the same
release's images on every node, so a node of the master's release matches, and any other
node is out of date and gets no jobs.

A submission without fingerprints gets the expected ones of the images its job runs in; a
submission that names fingerprints keeps them (a campaign's pinned set, Phase 4).
"""

import logging
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, List, Optional

import anyio

from scenegems_tool.cluster.fingerprints.comparison import FingerprintMismatch, find_mismatches
from scenegems_tool.cluster.fingerprints.job_images import capability_images, job_images
from scenegems_tool.cluster.protocol.jobs import JobSubmission
from scenegems_tool.cluster.release.manifest import read_release
from scenegems_tool.persistence.stores import NodeRecord

logger = logging.getLogger(__name__)


class ListingState(str, Enum):
    PENDING = "pending"  # being read; nothing is leased meanwhile
    READY = "ready"
    FAILED = "failed"  # nothing is leased until the master is restarted with a readable release


class ExpectedFingerprints:
    """The master's expected image fingerprints, read once in the background."""

    def __init__(self, compute: Callable[[], Dict[str, str]]):
        self._compute = compute
        self._listing: Optional[Dict[str, str]] = None
        self.state = ListingState.PENDING
        self.error: Optional[str] = None

    @classmethod
    def of_release(cls, manifest: Optional[Path]) -> "ExpectedFingerprints":
        def read() -> Dict[str, str]:
            if manifest is None:
                raise ValueError("SCENEGEMS_RELEASE_MANIFEST is not set, so the master knows no release")
            return read_release(manifest).fingerprints()

        return cls(read)

    @classmethod
    def fixed(cls, listing: Dict[str, str]) -> "ExpectedFingerprints":
        expected = cls(lambda: dict(listing))
        expected._set(dict(listing))
        return expected

    def current(self) -> Optional[Dict[str, str]]:
        """Image tag to fingerprint, or None while the listing is not available."""
        return self._listing

    async def load(self) -> None:
        if self.state == ListingState.READY:
            return
        try:
            listing = await anyio.to_thread.run_sync(self._compute)
        except Exception as error:  # the master keeps serving, but leases nothing
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
        self._listing = listing
        self.state, self.error = ListingState.READY, None


def with_required_fingerprints(submission: JobSubmission, expected: Dict[str, str]) -> JobSubmission:
    """The submission with the expected fingerprints of its job's images, unless it names its own."""
    if submission.requirements.fingerprints:
        return submission
    required = {image: expected[image] for image in job_images(submission.job_type) if image in expected}
    return submission.model_copy(update={"requirements": submission.requirements.model_copy(update={"fingerprints": required})})


def node_mismatches(node: NodeRecord, expected: Dict[str, str]) -> List[FingerprintMismatch]:
    """The images the node's capabilities need whose fingerprint differs from the expected one; empty when up to date."""
    required = {image: expected[image] for image in capability_images(node.capabilities) if image in expected}
    return find_mismatches(node.fingerprints, required)
