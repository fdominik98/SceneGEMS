"""The control node's artifact store with its routes' limit and its sweep timer (P4.3).

The sweep runs on the control node's event loop next to the control plane's timers, started and
stopped by the worker node API's lifespan (api/control_node_apps.py). Each round deletes the artifacts
that nothing references and nobody used for the grace period, then the files that had no
record for the grace period (recorded_artifacts.py); the store calls run in a worker
thread. A round first drops the operator uploads whose 24 hours passed
(ArtifactRecordStore.remove_expired_uploads), which makes an upload that no campaign took
over unreferenced, and so deleted once the grace period passes.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import List, Optional

import anyio

from scenegems_tool.cluster.control_node.api.artifact_routes import DEFAULT_MAX_ARTIFACT_BYTES
from scenegems_tool.persistence.artifacts.recorded_artifacts import RecordedArtifacts

logger = logging.getLogger(__name__)


@dataclass
class ControlNodeArtifacts:
    artifacts: RecordedArtifacts
    max_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES
    sweep_interval_s: float = 600.0  # 0: no sweep
    sweep_grace_s: float = 3600.0

    def __post_init__(self) -> None:
        self._task: Optional[asyncio.Task] = None

    async def sweep_once(self) -> List[str]:
        """One round; returns the hashes of the artifacts deleted, recorded ones first, then the files without a record."""
        expired = await anyio.to_thread.run_sync(self.artifacts.records.remove_expired_uploads)
        if expired:
            logger.info("Artifact sweep dropped the expired upload holds of %d artifacts", len(expired))
        deleted = await anyio.to_thread.run_sync(self.artifacts.sweep, self.sweep_grace_s)
        return deleted + await anyio.to_thread.run_sync(self.artifacts.sweep_orphans, self.sweep_grace_s)

    async def _sweep_loop(self) -> None:
        while True:
            await asyncio.sleep(self.sweep_interval_s)
            try:
                await self.sweep_once()
            except Exception:
                logger.exception("Artifact sweep failed; retrying in %.0f s", self.sweep_interval_s)

    def start_sweep(self) -> None:
        if self.sweep_interval_s > 0 and self._task is None:
            self._task = asyncio.create_task(self._sweep_loop())

    async def stop_sweep(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
