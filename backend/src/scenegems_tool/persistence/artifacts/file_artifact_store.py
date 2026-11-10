"""The artifact store on a local folder (the control node's artifact volume): one gzip file per artifact.

    <root>/<aa>/<bb>/<sha256>.gz   the content, gzip compressed; aa and bb are the hash's first two bytes
    <root>/.incoming/              writes in progress, on the same file system as their targets

A write goes to its own temporary file, is hashed while it is compressed, flushed to disk
(fsync) and renamed onto its address in one step, so a reader sees the whole artifact or
none, and a crash leaves at most a temporary file. Concurrent writers of one hash each
write their own temporary file; whichever renames first stores it, and the others find
equal content in place. Temporary files older than an hour are removed when a store opens.

The gzip files carry no name and a zero timestamp, so equal content gives equal files.
A stored file keeps the modification time of its first write (a later write of equal
content leaves it in place), which stored_hashes reads as the artifact's age.
"""

import gzip
import hashlib
import logging
import os
import tempfile
import time
import zlib
from pathlib import Path
from typing import BinaryIO, Iterator, List, Optional

from scenegems_tool.persistence.artifacts.artifact_store import (
    ArtifactHashMismatch,
    ArtifactNotFound,
    ArtifactStore,
    ArtifactTooLarge,
    ArtifactWriter,
    StoredArtifact,
    require_artifact_hash,
)
from scenegems_tool.persistence.schema.artifact_tables import SHA256_HEX_PATTERN

logger = logging.getLogger(__name__)

INCOMING_FOLDER = ".incoming"
FILE_SUFFIX = ".gz"
DEFAULT_COMPRESS_LEVEL = 6
STALE_INCOMING_AFTER_S = 3600.0


class FileArtifactStore(ArtifactStore):
    def __init__(self, root: Path, compress_level: int = DEFAULT_COMPRESS_LEVEL, stale_incoming_after_s: float = STALE_INCOMING_AFTER_S):
        self.root = Path(root)
        self.incoming = self.root / INCOMING_FOLDER
        self.compress_level = compress_level
        self.incoming.mkdir(parents=True, exist_ok=True)
        self._remove_stale_incoming(stale_incoming_after_s)

    def path(self, sha256: str) -> Path:
        require_artifact_hash(sha256)
        return self.root / sha256[0:2] / sha256[2:4] / f"{sha256}{FILE_SUFFIX}"

    def writer(self, sha256: str, max_bytes: Optional[int] = None) -> ArtifactWriter:
        return _FileWriter(self, require_artifact_hash(sha256), max_bytes)

    def open(self, sha256: str, compressed: bool = False) -> BinaryIO:
        path = self.path(sha256)
        try:
            return open(path, "rb") if compressed else gzip.open(path, "rb")
        except FileNotFoundError:
            raise ArtifactNotFound(sha256) from None

    def exists(self, sha256: str) -> bool:
        return self.path(sha256).is_file()

    def delete(self, sha256: str) -> bool:
        try:
            self.path(sha256).unlink()
            return True
        except FileNotFoundError:
            return False

    def size(self, sha256: str) -> int:
        # The gzip trailer's ISIZE: the size modulo 2**32, exact for the single-member files written here below 4 GiB
        try:
            with open(self.path(sha256), "rb") as stream:
                stream.seek(-4, os.SEEK_END)
                return int.from_bytes(stream.read(4), "little")
        except FileNotFoundError:
            raise ArtifactNotFound(sha256) from None

    def stored_size(self, sha256: str) -> int:
        try:
            return self.path(sha256).stat().st_size
        except FileNotFoundError:
            raise ArtifactNotFound(sha256) from None

    def stored_hashes(self, older_than_s: float = 0.0) -> Iterator[str]:
        """Each folder is listed whole before its hashes are yielded, so a caller may delete files while it iterates."""
        cutoff = time.time() - older_than_s
        for first in _hash_folders(self.root):
            for second in _hash_folders(first):
                for sha256 in _stored_before(second, cutoff):
                    yield sha256

    def _remove_stale_incoming(self, older_than_s: float) -> None:
        cutoff = time.time() - older_than_s
        for leftover in self.incoming.iterdir():
            try:
                if leftover.is_file() and leftover.stat().st_mtime < cutoff:
                    leftover.unlink()
                    logger.info("Removed the unfinished artifact write %s", leftover.name)
            except OSError:
                pass


class _FileWriter(ArtifactWriter):
    def __init__(self, store: FileArtifactStore, sha256: str, max_bytes: Optional[int]):
        self.sha256 = sha256
        self.size_bytes = 0
        self._store = store
        self._max_bytes = max_bytes
        self._hash = hashlib.sha256()
        descriptor, temporary = tempfile.mkstemp(prefix=f"{sha256[:16]}-", suffix=".tmp", dir=store.incoming)
        self._temporary = Path(temporary)
        self._raw = os.fdopen(descriptor, "wb")
        self._gzip = gzip.GzipFile(filename="", mode="wb", fileobj=self._raw, compresslevel=store.compress_level, mtime=0)
        self._done = False

    def write(self, data: bytes) -> None:
        if self._done:
            raise ValueError("the write is finished")
        self.size_bytes += len(data)
        if self._max_bytes is not None and self.size_bytes > self._max_bytes:
            self.abort()
            raise ArtifactTooLarge(self._max_bytes)
        self._hash.update(data)
        self._gzip.write(data)

    def commit(self) -> StoredArtifact:
        if self._done:
            raise ValueError("the write is finished")
        self._gzip.close()
        self._raw.flush()
        os.fsync(self._raw.fileno())
        self._raw.close()
        actual = self._hash.hexdigest()
        if actual != self.sha256:
            self.abort()
            raise ArtifactHashMismatch(self.sha256, actual)
        self._done = True
        target = self._store.path(self.sha256)
        created = self._move_into_place(target)
        return StoredArtifact(sha256=self.sha256, size_bytes=self.size_bytes, stored_size_bytes=target.stat().st_size, created=created)

    def _move_into_place(self, target: Path) -> bool:
        if target.is_file():
            self._temporary.unlink(missing_ok=True)  # equal content is in place already
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(self._temporary, target)
        except PermissionError:
            # Windows refuses to replace a file another writer just put there while it is open
            if not target.is_file():
                raise
            self._temporary.unlink(missing_ok=True)
            return False
        _sync_folder(target.parent)
        return True

    def abort(self) -> None:
        if self._done:
            return
        self._done = True
        for stream in (self._gzip, self._raw):
            try:
                stream.close()
            except (OSError, ValueError, zlib.error):
                pass
        self._temporary.unlink(missing_ok=True)


def _hash_folders(folder: Path) -> List[Path]:
    """The two-character hex subfolders of an address level; .incoming and anything else are skipped."""
    try:
        return sorted(Path(entry.path) for entry in os.scandir(folder) if len(entry.name) == 2 and all(c in "0123456789abcdef" for c in entry.name) and entry.is_dir())
    except FileNotFoundError:
        return []


def _stored_before(folder: Path, cutoff: float) -> List[str]:
    """The hashes of the artifact files in a leaf folder last modified before cutoff (seconds since the epoch)."""
    found: List[str] = []
    try:
        entries = list(os.scandir(folder))
    except FileNotFoundError:
        return found
    for entry in entries:
        sha256 = entry.name[: -len(FILE_SUFFIX)]
        if not entry.name.endswith(FILE_SUFFIX) or not SHA256_HEX_PATTERN.match(sha256):
            continue
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                found.append(sha256)
        except FileNotFoundError:
            pass  # deleted while listed
    return found


def _sync_folder(folder: Path) -> None:
    """Makes the rename durable; folders cannot be opened for fsync on Windows."""
    if os.name != "posix":
        return
    descriptor = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
