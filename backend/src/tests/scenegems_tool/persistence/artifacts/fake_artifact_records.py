"""An in-memory ArtifactRecordStore with the methods the artifact store and its routes use.

It follows persistence/stores/artifact_records.py: one record per hash (another size raises
ArtifactMismatch), a repeated insert marks the record used, references need a record, and
the sweep's queries see only unreferenced records unused for the grace period.
"""

import threading
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Collection, Dict, List, Optional, Set, Tuple

from scenegems_tool.persistence.schema.artifact_tables import require_sha256_hex
from scenegems_tool.persistence.stores.artifact_records import ArtifactInsert, ArtifactMismatch, ArtifactRecord, UnknownArtifact

ReferenceKey = Tuple[str, str, str, str]  # hash, holder kind, holder id, role


class InMemoryArtifactRecords:
    def __init__(self, clock):
        self._clock = clock
        self._lock = threading.Lock()
        self.records: Dict[str, ArtifactRecord] = {}
        self.references: Set[ReferenceKey] = set()
        self.expiry: Dict[ReferenceKey, datetime] = {}  # upload references only
        self.calls: List[str] = []  # method names in call order, for ordering checks

    def insert_if_absent(self, artifact_hash: str, kind: str, size_bytes: int, media_type: str, stored_size_bytes: Optional[int] = None, *, session=None) -> ArtifactInsert:
        require_sha256_hex(artifact_hash)
        with self._lock:
            self.calls.append("insert_if_absent")
            now = self._clock()
            record = self.records.get(artifact_hash)
            if record is None:
                record = ArtifactRecord(artifact_hash, kind, size_bytes, stored_size_bytes, media_type, now, now)
                self.records[artifact_hash] = record
                return ArtifactInsert(record, True)
            if record.size_bytes != size_bytes:
                raise ArtifactMismatch(f"artifact {artifact_hash} has {record.size_bytes} bytes on record, not {size_bytes}")
            record = self.records[artifact_hash] = replace(record, last_used_at=now)
            return ArtifactInsert(record, False)

    def get(self, artifact_hash: str, *, session=None) -> Optional[ArtifactRecord]:
        return self.records.get(artifact_hash)

    def existing_hashes(self, artifact_hashes: Collection[str], *, session=None) -> Set[str]:
        with self._lock:
            self.calls.append("existing_hashes")
            return {sha256 for sha256 in artifact_hashes if sha256 in self.records}

    def mark_used(self, artifact_hash: str, *, session=None) -> Optional[ArtifactRecord]:
        with self._lock:
            self.calls.append("mark_used")
            record = self.records.get(artifact_hash)
            if record is None:
                return None
            record = self.records[artifact_hash] = replace(record, last_used_at=self._clock())
            return record

    def add_reference(self, artifact_hash: str, holder_kind, holder_id: str, role: str, campaign_id: Optional[str] = None, *, session=None) -> bool:
        with self._lock:
            self.calls.append("add_reference")
            if artifact_hash not in self.records:
                raise UnknownArtifact(artifact_hash)
            key = (artifact_hash, getattr(holder_kind, "value", holder_kind), str(holder_id), role)
            created = key not in self.references
            self.references.add(key)
            self.records[artifact_hash] = replace(self.records[artifact_hash], last_used_at=self._clock())
            return created

    def add_upload_reference(self, artifact_hash: str, expires_at: datetime, *, session=None) -> ReferenceKey:
        """The operator's upload hold; a second upload keeps the later expiry."""
        with self._lock:
            self.calls.append("add_upload_reference")
            if artifact_hash not in self.records:
                raise UnknownArtifact(artifact_hash)
            key = (artifact_hash, "upload", artifact_hash, "upload")
            self.references.add(key)
            self.expiry[key] = max(expires_at, self.expiry.get(key, expires_at))
            self.records[artifact_hash] = replace(self.records[artifact_hash], last_used_at=self._clock())
            return key

    def remove_expired_uploads(self, *, session=None) -> List[str]:
        with self._lock:
            self.calls.append("remove_expired_uploads")
            now = self._clock()
            expired = [key for key, expires_at in self.expiry.items() if expires_at <= now]
            for key in expired:
                self.references.discard(key)
                del self.expiry[key]
                self.records[key[0]] = replace(self.records[key[0]], last_used_at=now)
            return sorted({key[0] for key in expired})

    def remove_references_of(self, holder_kind, holder_id: str, roles: Optional[Collection[str]] = None, *, session=None) -> List[str]:
        with self._lock:
            kind = getattr(holder_kind, "value", holder_kind)
            removed = {key for key in self.references if key[1] == kind and key[2] == str(holder_id) and (roles is None or key[3] in roles)}
            self.references -= removed
            for key in removed:
                self.records[key[0]] = replace(self.records[key[0]], last_used_at=self._clock())
            return sorted({key[0] for key in removed})

    def _unreferenced_unused(self, artifact_hash: str, unused_for_s: float) -> bool:
        cutoff = self._clock() - timedelta(seconds=unused_for_s)
        record = self.records.get(artifact_hash)
        return record is not None and record.last_used_at <= cutoff and not any(key[0] == artifact_hash for key in self.references)

    def list_unreferenced(self, unused_for_s: float, limit: Optional[int] = 100, *, session=None) -> List[ArtifactRecord]:
        with self._lock:
            found = sorted(
                (record for record in self.records.values() if self._unreferenced_unused(record.artifact_hash, unused_for_s)), key=lambda record: (record.last_used_at, record.artifact_hash)
            )
            return found[:limit]

    def delete_unreferenced(self, artifact_hashes: Collection[str], unused_for_s: float, *, session=None) -> List[str]:
        with self._lock:
            self.calls.append("delete_unreferenced")
            deleted = sorted(sha256 for sha256 in set(artifact_hashes) if self._unreferenced_unused(sha256, unused_for_s))
            for sha256 in deleted:
                del self.records[sha256]
            return deleted
