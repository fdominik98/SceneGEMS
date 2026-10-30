"""The master's view of its nodes: who is connected, and each node's status from its heartbeats.

The status lives in the node store: a Hello or heartbeat makes a node online, the
operator's drain makes it draining, and the silence sweep makes a node offline after
ControlTiming.node_offline_after_s without a heartbeat and closes its socket, so the node
reconnects and reconciles its leases. The connected sessions live here, in memory: one
per node, a newer connection of the same node replaces the older one.

on_change hears the id of every node whose view may have changed (connect, disconnect,
heartbeat, drain, resume, offline, out of date); the live channel's nodes topic sets it.
"""

import logging
from functools import partial
from typing import Callable, Dict, FrozenSet, List, Optional

import anyio

from scenegems_tool.cluster.fingerprints.comparison import LEGACY_TAG, by_repository
from scenegems_tool.cluster.master.registry.node_session import NodeSession
from scenegems_tool.cluster.master.scheduling.fingerprint_policy import node_mismatches, stale_components
from scenegems_tool.cluster.protocol.messages import Drain, Heartbeat, Hello
from scenegems_tool.persistence.schema import NodeStatus
from scenegems_tool.persistence.stores import NodeRecord, NodeStore

logger = logging.getLogger(__name__)

CLOSE_REPLACED = 4000  # a newer connection of the same node took over
CLOSE_SILENT = 4001  # no heartbeat for ControlTiming.node_offline_after_s


class NodeRegistry:
    def __init__(self, node_store: NodeStore, node_offline_after_s: float):
        self._nodes = node_store
        self._offline_after_s = node_offline_after_s
        self._sessions: Dict[str, NodeSession] = {}
        self.on_change: Callable[[str], None] = _ignore

    # Connections

    def connected(self) -> List[NodeSession]:
        """Open sessions past their Welcome, oldest connection first."""
        return [session for session in self._sessions.values() if session.ready and not session.closed]

    def session(self, node_id: str) -> Optional[NodeSession]:
        return self._sessions.get(node_id)

    async def register(self, hello: Hello) -> NodeRecord:
        # Stored by image repository; a node older than release tags names its images, all :latest, by tag
        hello = hello.model_copy(update={"fingerprints": by_repository(hello.fingerprints, LEGACY_TAG)})
        return await anyio.to_thread.run_sync(self._nodes.register, hello)

    async def connect(self, session: NodeSession) -> None:
        """Makes the session the node's connection; an older connection of the node is handed over and closed."""
        previous = self._sessions.pop(session.node_id, None)
        self._sessions[session.node_id] = session
        if previous is not None and previous is not session:
            previous.hand_over()
            logger.info("Node %s reconnected; closing its previous connection", session.node_id)
            await previous.close(CLOSE_REPLACED, "replaced by a newer connection of this node")
        self.on_change(session.node_id)

    def disconnect(self, session: NodeSession) -> bool:
        """Forgets the session unless a newer one replaced it; True when it was the node's connection."""
        session.closed = True
        if self._sessions.get(session.node_id) is session:
            del self._sessions[session.node_id]
            self.on_change(session.node_id)
            return True
        return False

    # Status

    async def heartbeat(self, session: NodeSession, heartbeat: Heartbeat) -> None:
        record = await anyio.to_thread.run_sync(self._nodes.heartbeat, session.node_id, heartbeat)
        if record is not None:
            session.record = record
            self.on_change(session.node_id)

    def refresh_out_of_date(self, session: NodeSession, expected: Optional[Dict[str, str]]) -> FrozenSet[str]:
        """Compares the node's fingerprints with the expected ones per component; returns its stale components (empty when up to date)."""
        if expected is None:
            return frozenset()
        mismatches = node_mismatches(session.record, expected)
        stale = stale_components(session.record.components, mismatches)
        if mismatches != session.out_of_date or stale != session.stale_components:
            if stale - session.stale_components:
                logger.warning(
                    "Node %s is out of date for %s, which get no jobs there: %s",
                    session.node_id,
                    ", ".join(sorted(stale)),
                    ", ".join(mismatch.image for mismatch in mismatches),
                )
            session.out_of_date = mismatches
            session.stale_components = stale
            self.on_change(session.node_id)
        return stale

    async def drain(self, node_id: str, reason: str) -> Optional[NodeRecord]:
        record = await anyio.to_thread.run_sync(self._nodes.set_status, node_id, NodeStatus.DRAINING)
        session = self._sessions.get(node_id)
        if record is not None and session is not None:
            session.record = record
            await session.send(Drain(reason=reason))
        if record is not None:
            self.on_change(node_id)
        return record

    async def resume(self, node_id: str) -> Optional[NodeRecord]:
        """Ends a drain. An offline node stays offline until it is heard from again."""
        record = await anyio.to_thread.run_sync(self._nodes.get, node_id)
        if record is None or record.status != NodeStatus.DRAINING:
            return record
        record = await anyio.to_thread.run_sync(self._nodes.set_status, node_id, NodeStatus.ONLINE)
        session = self._sessions.get(node_id)
        if record is not None and session is not None:
            session.record = record
        if record is not None:
            self.on_change(node_id)
        return record

    async def remove(self, node_id: str) -> Optional[bool]:
        """Forgets an offline node; None for an unknown node, False for one that is connected or not offline."""
        session = self._sessions.get(node_id)
        if session is not None and not session.closed:
            return False if await anyio.to_thread.run_sync(self._nodes.get, node_id) is not None else None
        removed = await anyio.to_thread.run_sync(self._nodes.remove_offline, node_id)
        if removed:
            self._sessions.pop(node_id, None)
            self.on_change(node_id)
        return removed

    async def sweep_silent(self) -> List[str]:
        """Marks silent nodes offline and closes their sockets; returns their ids."""
        silent = await anyio.to_thread.run_sync(partial(self._nodes.mark_silent_nodes_offline, self._offline_after_s))
        for node_id in silent:
            session = self._sessions.get(node_id)
            if session is not None:
                logger.warning("Node %s sent no heartbeat for %.0f s; closing its connection", node_id, self._offline_after_s)
                await session.close(CLOSE_SILENT, "no heartbeat")
            self.on_change(node_id)
        return silent

    # Queries

    async def nodes(self) -> List[NodeRecord]:
        return await anyio.to_thread.run_sync(self._nodes.list_nodes)

    async def node(self, node_id: str) -> Optional[NodeRecord]:
        return await anyio.to_thread.run_sync(self._nodes.get, node_id)


def _ignore(_node_id: str) -> None:
    pass
