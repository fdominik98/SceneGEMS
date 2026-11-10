"""A bounded cache of artifacts in the worker node's state volume, so a worker node downloads each input once.

    <folder>/<sha256>   the uncompressed content; written to a temporary file and renamed

Every read checks the content's hash; an entry that fails is removed and counts as a
miss, so a damaged cache costs a download, never a wrong input. When the entries exceed
max_bytes, the least recently used ones go (a hit renews an entry's time). The cache is
shared by the worker node's job threads and may be read while another thread writes the same
entry; content addressing makes both copies equal.
"""

import hashlib
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = 2 * 1024 * 1024 * 1024
_ENTRY = re.compile(r"^[0-9a-f]{64}$")


class ArtifactCache:
    def __init__(self, folder: Path, max_bytes: int = DEFAULT_MAX_BYTES):
        self.folder = Path(folder)
        self.max_bytes = max_bytes
        self.folder.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._sizes: Dict[str, int] = {}
        for path in self.folder.iterdir():
            if _ENTRY.match(path.name) and path.is_file():
                self._sizes[path.name] = path.stat().st_size
            elif path.suffix == ".tmp":
                path.unlink(missing_ok=True)  # a write a stopped daemon left unfinished
        self._evict()

    @property
    def size_bytes(self) -> int:
        with self._lock:
            return sum(self._sizes.values())

    def path(self, sha256: str) -> Path:
        if not _ENTRY.match(sha256):
            raise ValueError(f"not a sha256 address: {sha256!r}")
        return self.folder / sha256

    def get(self, sha256: str) -> Optional[bytes]:
        """The cached content after its hash check, or None."""
        path = self.path(sha256)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return None
        if hashlib.sha256(data).hexdigest() != sha256:
            logger.warning("Removing artifact %s from the cache: its content does not match its hash", sha256)
            self._remove(sha256)
            return None
        try:
            os.utime(path)
        except OSError:
            pass
        return data

    def put(self, sha256: str, data: bytes) -> bool:
        """Caches the content when it fits; False when it is larger than the whole cache. The caller checked the hash."""
        if len(data) > self.max_bytes:
            return False
        path = self.path(sha256)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{sha256[:16]}-", suffix=".tmp", dir=self.folder)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
            try:
                os.replace(temporary, path)
            except PermissionError:
                if not path.is_file():  # Windows: another thread wrote the same entry and has it open
                    raise
        finally:
            Path(temporary).unlink(missing_ok=True)
        with self._lock:
            self._sizes[sha256] = len(data)
        self._evict(keep=sha256)
        return True

    def _remove(self, sha256: str) -> None:
        try:
            self.path(sha256).unlink(missing_ok=True)
        except OSError:
            return  # in use on Windows; the next eviction tries again
        with self._lock:
            self._sizes.pop(sha256, None)

    def _evict(self, keep: Optional[str] = None) -> None:
        with self._lock:
            total = sum(self._sizes.values())
            if total <= self.max_bytes:
                return
            entries = sorted(self._sizes, key=self._last_used)
        for sha256 in entries:
            if total <= self.max_bytes:
                return
            if sha256 == keep:
                continue
            size = self._sizes.get(sha256, 0)
            self._remove(sha256)
            if sha256 not in self._sizes:
                total -= size

    def _last_used(self, sha256: str) -> float:
        try:
            return self.path(sha256).stat().st_mtime
        except OSError:
            return time.time()
