"""The control node's view of its worker nodes: who is connected, and each worker node's status from its heartbeats.

The status lives in the worker node store: a Hello or heartbeat makes a worker node online, the
operator's drain makes it draining, and the silence sweep makes a worker node offline after
ControlTiming.worker_node_offline_after_s without a heartbeat and closes its socket, so the worker node
reconnects and reconciles its leases. The connected sessions live here, in memory: one
per worker node, a newer connection of the same worker node replaces the older one.

on_change hears the id of every worker node whose view may have changed (connect, disconnect,
heartbeat, drain, resume, offline, out of date); the live channel's worker nodes topic sets it.
"""

import logging
from functools import partial
from typing import Callable, Dict, FrozenSet, List, Optional

import anyio

from scenegems_tool.cluster.control_node.registry.worker_node_session import WorkerNodeSession
from scenegems_tool.cluster.control_node.scheduling.fingerprint_policy import stale_components, worker_node_mismatches
from scenegems_tool.cluster.fingerprints.comparison import LEGACY_TAG, by_repository
from scenegems_tool.cluster.protocol.messages import Drain, Heartbeat, Hello
from scenegems_tool.persistence.schema import WorkerNodeStatus
from scenegems_tool.persistence.stores import WorkerNodeRecord, WorkerNodeStore

logger = logging.getLogger(__name__)

CLOSE_REPLACED = 4000  # a newer connection of the same worker node took over
CLOSE_SILENT = 4001  # no heartbeat for ControlTiming.worker_node_offline_after_s


class WorkerNodeRegistry:
    def __init__(self, worker_node_store: WorkerNodeStore, worker_node_offline_after_s: float):
        self._worker_nodes = worker_node_store
        self._offline_after_s = worker_node_offline_after_s
        self._sessions: Dict[str, WorkerNodeSession] = {}
        self.on_change: Callable[[str], None] = _ignore

    # Connections

    def connected(self) -> List[WorkerNodeSession]:
        """Open sessions past their Welcome, oldest connection first."""
        return [session for session in self._sessions.values() if session.ready and not session.closed]

    def session(self, worker_node_id: str) -> Optional[WorkerNodeSession]:
        return self._sessions.get(worker_node_id)

    async def register(self, hello: Hello) -> WorkerNodeRecord:
        # Stored by image repository; a worker node older than release tags names its images, all :latest, by tag
        hello = hello.model_copy(update={"fingerprints": by_repository(hello.fingerprints, LEGACY_TAG)})
        return await anyio.to_thread.run_sync(self._worker_nodes.register, hello)

    async def connect(self, session: WorkerNodeSession) -> None:
        """Makes the session the worker node's connection; an older connection of the worker node is handed over and closed."""
        previous = self._sessions.pop(session.worker_node_id, None)
        self._sessions[session.worker_node_id] = session
        if previous is not None and previous is not session:
            previous.hand_over()
            logger.info("Worker node %s reconnected; closing its previous connection", session.worker_node_id)
            await previous.close(CLOSE_REPLACED, "replaced by a newer connection of this worker node")
        self.on_change(session.worker_node_id)

    def disconnect(self, session: WorkerNodeSession) -> bool:
        """Forgets the session unless a newer one replaced it; True when it was the worker node's connection."""
        session.closed = True
        if self._sessions.get(session.worker_node_id) is session:
            del self._sessions[session.worker_node_id]
            self.on_change(session.worker_node_id)
            return True
        return False

    # Status

    async def heartbeat(self, session: WorkerNodeSession, heartbeat: Heartbeat) -> None:
        record = await anyio.to_thread.run_sync(self._worker_nodes.heartbeat, session.worker_node_id, heartbeat)
        if record is not None:
            session.record = record
            self.on_change(session.worker_node_id)

    def refresh_out_of_date(self, session: WorkerNodeSession, expected: Optional[Dict[str, str]]) -> FrozenSet[str]:
        """Compares the worker node's fingerprints with the expected ones per component; returns its stale components (empty when up to date)."""
        if expected is None:
            return frozenset()
        mismatches = worker_node_mismatches(session.record, expected)
        stale = stale_components(session.record.components, mismatches)
        if mismatches != session.out_of_date or stale != session.stale_components:
            if stale - session.stale_components:
                logger.warning(
                    "Worker node %s is out of date for %s, which get no jobs there: %s",
                    session.worker_node_id,
                    ", ".join(sorted(stale)),
                    ", ".join(mismatch.image for mismatch in mismatches),
                )
            session.out_of_date = mismatches
            session.stale_components = stale
            self.on_change(session.worker_node_id)
        return stale

    async def drain(self, worker_node_id: str, reason: str) -> Optional[WorkerNodeRecord]:
        record = await anyio.to_thread.run_sync(self._worker_nodes.set_status, worker_node_id, WorkerNodeStatus.DRAINING)
        session = self._sessions.get(worker_node_id)
        if record is not None and session is not None:
            session.record = record
            await session.send(Drain(reason=reason))
        if record is not None:
            self.on_change(worker_node_id)
        return record

    async def resume(self, worker_node_id: str) -> Optional[WorkerNodeRecord]:
        """Ends a drain. An offline worker node stays offline until it is heard from again."""
        record = await anyio.to_thread.run_sync(self._worker_nodes.get, worker_node_id)
        if record is None or record.status != WorkerNodeStatus.DRAINING:
            return record
        record = await anyio.to_thread.run_sync(self._worker_nodes.set_status, worker_node_id, WorkerNodeStatus.ONLINE)
        session = self._sessions.get(worker_node_id)
        if record is not None and session is not None:
            session.record = record
        if record is not None:
            self.on_change(worker_node_id)
        return record

    async def remove(self, worker_node_id: str) -> Optional[bool]:
        """Forgets an offline worker node; None for an unknown worker node, False for one that is connected or not offline."""
        session = self._sessions.get(worker_node_id)
        if session is not None and not session.closed:
            return False if await anyio.to_thread.run_sync(self._worker_nodes.get, worker_node_id) is not None else None
        removed = await anyio.to_thread.run_sync(self._worker_nodes.remove_offline, worker_node_id)
        if removed:
            self._sessions.pop(worker_node_id, None)
            self.on_change(worker_node_id)
        return removed

    async def sweep_silent(self) -> List[str]:
        """Marks silent worker nodes offline and closes their sockets; returns their ids."""
        silent = await anyio.to_thread.run_sync(partial(self._worker_nodes.mark_silent_worker_nodes_offline, self._offline_after_s))
        for worker_node_id in silent:
            session = self._sessions.get(worker_node_id)
            if session is not None:
                logger.warning("Worker node %s sent no heartbeat for %.0f s; closing its connection", worker_node_id, self._offline_after_s)
                await session.close(CLOSE_SILENT, "no heartbeat")
            self.on_change(worker_node_id)
        return silent

    # Queries

    async def worker_nodes(self) -> List[WorkerNodeRecord]:
        return await anyio.to_thread.run_sync(self._worker_nodes.list_worker_nodes)

    async def worker_node(self, worker_node_id: str) -> Optional[WorkerNodeRecord]:
        return await anyio.to_thread.run_sync(self._worker_nodes.get, worker_node_id)


def _ignore(_worker_node_id: str) -> None:
    pass
