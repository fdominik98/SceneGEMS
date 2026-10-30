"""Compare the fingerprints a node reports with the required ones.

Fingerprints are keyed by image repository, the name without its tag (utils/image_names.py): a
release tags its images with its revision, so the master, its nodes and a campaign pinned under
an older release name the same image with different tags. by_repository turns a map keyed by
full names, such as a campaign's pins from before release tags, into that form.
"""

from dataclasses import dataclass
from typing import Collection, Dict, List, Mapping, Optional, Set

from utils.image_names import image_repository

LEGACY_TAG = "latest"  # every image's tag before releases tagged their images


@dataclass(frozen=True)
class FingerprintMismatch:
    image: str  # the image repository
    required: str
    actual: Optional[str]  # None when the node has no fingerprinted image of that repository

    @property
    def missing(self) -> bool:
        return self.actual is None


def by_repository(fingerprints: Mapping[str, str], tag: Optional[str] = None) -> Dict[str, str]:
    """Image repository to fingerprint. Of several names of one repository the one tagged tag wins, else the first by name."""
    keyed: Dict[str, str] = {}
    preferred: Set[str] = set()
    for name, fingerprint in sorted(fingerprints.items()):
        repository = image_repository(name)
        is_preferred = tag is not None and name == f"{repository}:{tag}"
        if repository not in keyed or (is_preferred and repository not in preferred):
            keyed[repository] = fingerprint
        if is_preferred:
            preferred.add(repository)
    return keyed


def repositories(images: Collection[str]) -> List[str]:
    """The distinct repositories of these image names, sorted."""
    return sorted({image_repository(image) for image in images})


def fingerprints_of(images: Collection[str], fingerprints: Mapping[str, str]) -> Dict[str, str]:
    """The fingerprints of these images, keyed by repository; one listed under another tag of an image counts (a pin of an older release)."""
    keyed = by_repository(fingerprints)
    return {repository: keyed[repository] for repository in repositories(images) if repository in keyed}


def with_legacy_names(fingerprints: Mapping[str, str]) -> Dict[str, str]:
    """A node's fingerprints by repository, each also under <repository>:latest, the only name before release tags.

    The claim (JSONB containment) matches a job's required fingerprints against this: a job
    submitted since release tags requires them by repository, one submitted before by those
    names. A node stored with full names (a Hello not passed through the registry) is keyed by
    repository first.
    """
    keyed = by_repository(fingerprints, LEGACY_TAG)
    return {**keyed, **{f"{repository}:{LEGACY_TAG}": fingerprint for repository, fingerprint in keyed.items()}}


def find_mismatches(actual: Mapping[str, str], required: Mapping[str, str]) -> List[FingerprintMismatch]:
    """Required images the node lacks or has built from other inputs, compared by repository; images not required are ignored."""
    actual, required = by_repository(actual), by_repository(required)
    return [FingerprintMismatch(image, fingerprint, actual.get(image)) for image, fingerprint in sorted(required.items()) if actual.get(image) != fingerprint]
