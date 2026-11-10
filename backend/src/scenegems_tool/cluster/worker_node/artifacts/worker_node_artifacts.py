"""What the job runner uses to move artifacts: load(reference) for inputs, store(job, field, data) for results.

Inputs come from the cache when it holds them, otherwise from the control node, and are cached
after their hash check. Results go to the control node as the job's result field and into the
cache, since the next stage of the same case often runs on the same worker node. Two jobs that
need the same artifact at once download it once.
"""

import threading
from typing import Optional, Protocol

from scenegems_tool.cluster.protocol.artifacts import JSON_MEDIA_TYPE, TEXT_MEDIA_TYPE, ArtifactContent, ArtifactField, ArtifactRef
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.worker_node.artifacts.artifact_cache import ArtifactCache
from scenegems_tool.cluster.worker_node.artifacts.artifact_client import ArtifactClient

LOCK_STRIPES = 32


class ArtifactTransport(Protocol):
    def load(self, reference: ArtifactRef) -> bytes: ...

    def store(self, job: JobSpec, field: ArtifactField, data: bytes) -> ArtifactRef: ...


class WorkerNodeArtifacts:
    def __init__(self, client: ArtifactClient, cache: Optional[ArtifactCache] = None):
        self.client = client
        self.cache = cache
        self._locks = [threading.Lock() for _ in range(LOCK_STRIPES)]

    def load(self, reference: ArtifactRef) -> bytes:
        sha256 = reference.sha256
        with self._locks[int(sha256[:8], 16) % LOCK_STRIPES]:
            cached = self.cache.get(sha256) if self.cache is not None else None
            if cached is not None:
                return cached
            data = self.client.download(sha256, max_bytes=reference.size_bytes)
            if self.cache is not None:
                self.cache.put(sha256, data)
            return data

    def store(self, job: JobSpec, field: ArtifactField, data: bytes) -> ArtifactRef:
        media_type = TEXT_MEDIA_TYPE if field.content == ArtifactContent.TEXT else JSON_MEDIA_TYPE
        reference = self.client.upload(data, field.kind, media_type, job_id=job.job_id, field=field.name)
        if self.cache is not None:
            self.cache.put(reference.sha256, data)
        return reference
