"""The master's artifacts: the store's files and their Postgres records, kept in step.

    commit(writer, kind, media_type, holder)  file first, then the record (and the holder's reference)
    open(sha256)                              marks the record used, then opens the file
    sweep(grace_s)                            deletes unreferenced, unused records, then their files
    sweep_orphans(grace_s)                    deletes files that had no record for grace_s seconds

The order makes a crash harmless: a file without a record is at most an orphan, a record
never names a missing file. Orphans come from a crash between a file's rename and its
record, or from a sweep that deleted a record but could not delete its file; sweep_orphans
collects them. All paths take a lock per hash, so a sweep cannot delete the file a
concurrent upload of the same content just recorded. The locks are in this process, which
is enough because a cluster has one master process; a store shared by several processes
would need the lock in the database.

One writer records outside the lock: the pipeline engine repairs a missing record inside
its own transaction (assurance/pipeline/verdicts.py record_references). Its file is a job
result the node uploaded just before reporting the result, so the grace period, counted
from the file's first write, keeps the orphan sweep away from it unless the engine falls
that far behind the results.

An upload names the job it belongs to, which becomes the artifact's first reference
(holder `job`, role `result:<field>`), in the same locked step as the record. A result
artifact therefore never waits unreferenced for the pipeline engine, and a job submitted
by hand keeps its results.
"""

import logging
import threading
from dataclasses import dataclass
from itertools import islice
from typing import BinaryIO, Iterator, List, Optional

from scenegems_tool.persistence.artifacts.artifact_store import ArtifactStore, ArtifactWriter, StoredArtifact, sha256_hex
from scenegems_tool.persistence.schema import ArtifactHolderKind
from scenegems_tool.persistence.stores.artifact_records import ArtifactRecord, ArtifactRecordStore

logger = logging.getLogger(__name__)

LOCK_STRIPES = 64
SWEEP_BATCH = 100
RESULT_ROLE_PREFIX = "result:"


def result_role(field: str) -> str:
    """The role of a job's reference to the artifact of one of its result fields."""
    return f"{RESULT_ROLE_PREFIX}{field}"


@dataclass(frozen=True)
class ArtifactHolder:
    kind: ArtifactHolderKind
    holder_id: str
    role: str
    campaign_id: Optional[str] = None


@dataclass(frozen=True)
class RecordedArtifact:
    stored: StoredArtifact
    record: ArtifactRecord
    recorded: bool  # False when the record existed already


class RecordedArtifacts:
    def __init__(self, store: ArtifactStore, records: ArtifactRecordStore, lock_stripes: int = LOCK_STRIPES):
        self.store = store
        self.records = records
        self._locks = [threading.Lock() for _ in range(lock_stripes)]

    def _lock(self, sha256: str) -> threading.Lock:
        return self._locks[int(sha256[:8], 16) % len(self._locks)]

    # Writing

    def writer(self, sha256: str, max_bytes: Optional[int] = None) -> ArtifactWriter:
        return self.store.writer(sha256, max_bytes)

    def commit(self, writer: ArtifactWriter, kind: str, media_type: str, holder: Optional[ArtifactHolder] = None) -> RecordedArtifact:
        """Stores the written content and records it; raises what the writer's commit raises, or ArtifactMismatch."""
        with self._lock(writer.sha256):
            stored = writer.commit()
            inserted = self.records.insert_if_absent(writer.sha256, kind, stored.size_bytes, media_type, stored.stored_size_bytes)
            if holder is not None:
                self.records.add_reference(writer.sha256, holder.kind, holder.holder_id, holder.role, holder.campaign_id)
        return RecordedArtifact(stored=stored, record=inserted.artifact, recorded=inserted.created)

    def put(self, data: bytes, kind: str, media_type: str, sha256: Optional[str] = None, holder: Optional[ArtifactHolder] = None, max_bytes: Optional[int] = None) -> RecordedArtifact:
        with self.writer(sha256 or sha256_hex(data), max_bytes) as writer:
            writer.write(data)
            return self.commit(writer, kind, media_type, holder)

    # Reading

    def open(self, sha256: str, compressed: bool = False) -> BinaryIO:
        """The content, after marking its record used; raises ArtifactNotFound. A file without a record is served too."""
        self.records.mark_used(sha256)
        return self.store.open(sha256, compressed)

    def record(self, sha256: str) -> Optional[ArtifactRecord]:
        return self.records.get(sha256)

    # Sweep

    def sweep(self, grace_s: float, batch: int = SWEEP_BATCH, max_batches: Optional[int] = None) -> List[str]:
        """Deletes every artifact without references that was not used for grace_s seconds; returns their hashes."""
        deleted: List[str] = []
        batches = 0
        while max_batches is None or batches < max_batches:
            batches += 1
            candidates = self.records.list_unreferenced(grace_s, batch)
            gone = [sha256 for sha256 in (candidate.artifact_hash for candidate in candidates) if self._sweep_one(sha256, grace_s)]
            deleted.extend(gone)
            if len(candidates) < batch or not gone:
                break
        if deleted:
            logger.info("Artifact sweep deleted %d unreferenced artifacts", len(deleted))
        return deleted

    def _sweep_one(self, sha256: str, grace_s: float) -> bool:
        with self._lock(sha256):
            if not self.records.delete_unreferenced([sha256], grace_s):
                return False  # referenced or used again since it was listed
            try:
                self.store.delete(sha256)
            except OSError as error:
                # The record is gone, so the file is an orphan; sweep_orphans or a later upload of the same content handles it
                logger.warning("Cannot delete the file of artifact %s: %s", sha256, error)
        return True

    def sweep_orphans(self, grace_s: float, batch: int = SWEEP_BATCH) -> List[str]:
        """Deletes the stored files first written more than grace_s seconds ago that have no record; returns their hashes."""
        deleted: List[str] = []
        for chunk in _chunks(self.store.stored_hashes(grace_s), batch):
            recorded = self.records.existing_hashes(chunk)
            deleted.extend(sha256 for sha256 in chunk if sha256 not in recorded and self._delete_orphan(sha256))
        if deleted:
            logger.info("Artifact sweep deleted %d files without a record", len(deleted))
        return deleted

    def _delete_orphan(self, sha256: str) -> bool:
        with self._lock(sha256):
            if self.records.get(sha256) is not None:
                return False  # recorded since it was listed
            try:
                return self.store.delete(sha256)
            except OSError as error:
                logger.warning("Cannot delete the artifact file %s without a record: %s", sha256, error)
                return False


def _chunks(hashes: Iterator[str], size: int) -> Iterator[List[str]]:
    while chunk := list(islice(hashes, size)):
        yield chunk
