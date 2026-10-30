"""The artifact store: large job data as content-addressed bytes, behind an interface MinIO can implement later.

An artifact's address is the sha256 of its uncompressed bytes (64 lowercase hex characters).
Every write names the hash it expects and fails when the bytes hash to anything else, so a
stored artifact is always what its address says. Equal content is stored once; storing it
again is harmless.

    writer(sha256, max_bytes)   a streaming write; commit() checks size and hash, then stores atomically
    put(data, sha256)           the same for bytes in memory
    open(sha256, compressed)    the content as a binary stream, or the stored gzip bytes
    read, exists, delete, size, stored_size
    stored_hashes(older_than_s) every stored address written more than older_than_s seconds ago

The store knows bytes only. What an artifact is (its kind and media type) and who still
needs it are recorded in Postgres (persistence/stores/artifact_records.py); recorded_artifacts.py
keeps the two in step.
"""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import BinaryIO, Iterator, Optional

from scenegems_tool.persistence.schema.artifact_tables import require_sha256_hex

COMPRESSED_ENCODING = "gzip"  # what open(compressed=True) returns, as an HTTP content coding


class ArtifactStoreError(RuntimeError):
    pass


class ArtifactNotFound(ArtifactStoreError, LookupError):
    pass


class ArtifactHashMismatch(ArtifactStoreError, ValueError):
    """The bytes written hash to another value than the address they were written to."""

    def __init__(self, expected: str, actual: str):
        super().__init__(f"the content hashes to {actual}, not {expected}")
        self.expected = expected
        self.actual = actual


class ArtifactTooLarge(ArtifactStoreError, ValueError):
    def __init__(self, max_bytes: int):
        super().__init__(f"the artifact exceeds the limit of {max_bytes} bytes")
        self.max_bytes = max_bytes


@dataclass(frozen=True)
class StoredArtifact:
    sha256: str
    size_bytes: int  # uncompressed
    stored_size_bytes: int  # as stored
    created: bool  # False when the store held the content already


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def require_artifact_hash(value: str) -> str:
    """The value when it is a sha256 address; ValueError otherwise (also against path tricks)."""
    return require_sha256_hex(value)


class ArtifactWriter(ABC):
    """One streaming write. Nothing is visible under the address before commit(); abort() discards it.

    As a context manager it aborts unless committed, so an exception leaves nothing behind.
    """

    sha256: str
    size_bytes: int  # written so far, uncompressed

    @abstractmethod
    def write(self, data: bytes) -> None:
        """Raises ArtifactTooLarge (and aborts) once more than max_bytes were written."""

    @abstractmethod
    def commit(self) -> StoredArtifact:
        """Stores the content under its address; raises ArtifactHashMismatch (and aborts) when it hashes otherwise."""

    @abstractmethod
    def abort(self) -> None:
        """Discards the write; does nothing after commit or a previous abort."""

    def __enter__(self) -> "ArtifactWriter":
        return self

    def __exit__(self, *_exc) -> None:
        self.abort()


class ArtifactStore(ABC):
    @abstractmethod
    def writer(self, sha256: str, max_bytes: Optional[int] = None) -> ArtifactWriter: ...

    @abstractmethod
    def open(self, sha256: str, compressed: bool = False) -> BinaryIO:
        """The content (or with compressed, its COMPRESSED_ENCODING bytes) as a stream; raises ArtifactNotFound."""

    @abstractmethod
    def exists(self, sha256: str) -> bool: ...

    @abstractmethod
    def delete(self, sha256: str) -> bool:
        """Removes the content; False when there was none."""

    @abstractmethod
    def size(self, sha256: str) -> int:
        """The uncompressed size; raises ArtifactNotFound."""

    @abstractmethod
    def stored_size(self, sha256: str) -> int:
        """The size as stored; raises ArtifactNotFound."""

    @abstractmethod
    def stored_hashes(self, older_than_s: float = 0.0) -> Iterator[str]:
        """The addresses of the stored artifacts first written more than older_than_s seconds ago, in no order."""

    def put(self, data: bytes, sha256: Optional[str] = None, max_bytes: Optional[int] = None) -> StoredArtifact:
        """Stores bytes in memory; without sha256 their own hash is the address."""
        with self.writer(sha256 or sha256_hex(data), max_bytes) as writer:
            writer.write(data)
            return writer.commit()

    def read(self, sha256: str) -> bytes:
        with self.open(sha256) as stream:
            return stream.read()
