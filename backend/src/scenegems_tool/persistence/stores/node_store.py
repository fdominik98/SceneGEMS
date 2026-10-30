"""Nodes from their Hello and heartbeats, and their status, as the master's registry calls them.

Status rules: a Hello or a heartbeat makes a node online, except that a draining node
stays draining until the operator ends the drain. A node that has been silent too long
becomes offline (mark_silent_nodes_offline), draining or not; when it comes back it is
online, so a drain must be issued again after an outage.
"""

from datetime import timedelta
from typing import List, Optional

from sqlalchemy import case, delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from scenegems_tool.cluster.protocol.messages import Heartbeat, Hello
from scenegems_tool.persistence.clock import Clock, utc_now
from scenegems_tool.persistence.database import transaction
from scenegems_tool.persistence.schema import JobRow, NodeCapabilityRow, NodeComponentRow, NodeFingerprintRow, NodeRow, NodeStatus
from scenegems_tool.persistence.stores.job_lifecycle import ACTIVE_STATES
from scenegems_tool.persistence.stores.node_records import NodeRecord


class NodeStore:
    def __init__(self, session_factory: sessionmaker[Session], clock: Clock = utc_now):
        self._sessions = session_factory
        self._clock = clock

    def register(self, hello: Hello) -> NodeRecord:
        """Creates or updates the node from its Hello and replaces its slots, components and fingerprints.

        Slot usage starts at zero until the first heartbeat.
        """
        now = self._clock()
        resources = hello.resources
        values = dict(
            name=hello.node_name,
            labels=hello.labels,
            software_revision=hello.software_revision,
            machine=hello.machine,
            cpus=resources.cpus,
            memory_mb=resources.memory_mb,
            free_memory_mb=resources.free_memory_mb,
            free_disk_mb=resources.free_disk_mb,
            load_average=resources.load_average,
            last_seen_at=now,
        )
        node_table = NodeRow.__table__
        with transaction(self._sessions) as session:
            # The upsert locks the row, so two Hellos of one node apply one after the other
            session.execute(
                insert(NodeRow)
                .values(id=hello.node_id, status=NodeStatus.ONLINE, registered_at=now, **values)
                .on_conflict_do_update(
                    index_elements=[NodeRow.id],
                    set_=dict(values, status=case((node_table.c.status == NodeStatus.DRAINING.value, NodeStatus.DRAINING.value), else_=NodeStatus.ONLINE.value)),
                )
            )
            session.execute(delete(NodeCapabilityRow).where(NodeCapabilityRow.node_id == hello.node_id))
            session.execute(delete(NodeComponentRow).where(NodeComponentRow.node_id == hello.node_id))
            session.execute(delete(NodeFingerprintRow).where(NodeFingerprintRow.node_id == hello.node_id))
            session.add_all(NodeCapabilityRow(node_id=hello.node_id, job_type=offer.job_type, slots=offer.slots, slots_in_use=0) for offer in hello.slots)
            session.add_all(NodeComponentRow(node_id=hello.node_id, component=component) for component in sorted(set(hello.components)))
            session.add_all(NodeFingerprintRow(node_id=hello.node_id, image=image, fingerprint=fingerprint) for image, fingerprint in hello.fingerprints.items())
            session.flush()
            return NodeRecord.from_row(self._load(session, hello.node_id))

    def heartbeat(self, node_id: str, heartbeat: Heartbeat) -> Optional[NodeRecord]:
        """Records the node as seen now with its resources and slot usage; None for an unknown node."""
        now = self._clock()
        with transaction(self._sessions) as session:
            row = self._load(session, node_id, lock=True)
            if row is None:
                return None
            resources = heartbeat.resources
            row.cpus = resources.cpus
            row.memory_mb = resources.memory_mb
            row.free_memory_mb = resources.free_memory_mb
            row.free_disk_mb = resources.free_disk_mb
            row.load_average = resources.load_average
            row.last_seen_at = now
            if row.status == NodeStatus.OFFLINE:
                row.status = NodeStatus.ONLINE
            for capability in row.capabilities:
                capability.slots_in_use = heartbeat.slots_in_use.get(capability.job_type, 0)
            session.flush()
            return NodeRecord.from_row(row)

    def set_status(self, node_id: str, status: NodeStatus) -> Optional[NodeRecord]:
        """Sets the status directly, for the operator's drain and its end; None for an unknown node."""
        with transaction(self._sessions) as session:
            row = self._load(session, node_id, lock=True)
            if row is None:
                return None
            row.status = status
            session.flush()
            return NodeRecord.from_row(row)

    def mark_silent_nodes_offline(self, silent_for_s: float) -> List[str]:
        """Marks offline every node not seen for silent_for_s seconds; returns their ids, sorted."""
        cutoff = self._clock() - timedelta(seconds=silent_for_s)
        with transaction(self._sessions) as session:
            statement = update(NodeRow).where(NodeRow.status != NodeStatus.OFFLINE, NodeRow.last_seen_at < cutoff).values(status=NodeStatus.OFFLINE).returning(NodeRow.id)
            return sorted(session.execute(statement).scalars())

    def remove_offline(self, node_id: str) -> Optional[bool]:
        """Deletes an offline node with its slots, components and fingerprints; None for an unknown node, False for one that is not offline or still holds a lease.

        The node's finished and queued jobs lose their lease owner, which has a foreign key to the node; run records and events keep the node id they carry.
        A node that is heard from again registers anew.
        """
        with transaction(self._sessions) as session:
            row = self._load(session, node_id, lock=True)
            if row is None:
                return None
            if row.status != NodeStatus.OFFLINE:
                return False
            if session.execute(select(JobRow.id).where(JobRow.lease_owner == node_id, JobRow.state.in_(ACTIVE_STATES)).limit(1)).first() is not None:
                return False
            session.execute(update(JobRow).where(JobRow.lease_owner == node_id).values(lease_owner=None))
            session.delete(row)
            return True

    def get(self, node_id: str) -> Optional[NodeRecord]:
        with transaction(self._sessions) as session:
            row = self._load(session, node_id)
            return None if row is None else NodeRecord.from_row(row)

    def list_nodes(self, status: Optional[NodeStatus] = None) -> List[NodeRecord]:
        with transaction(self._sessions) as session:
            query = select(NodeRow).order_by(NodeRow.id)
            if status is not None:
                query = query.where(NodeRow.status == status)
            return [NodeRecord.from_row(row) for row in session.execute(query).scalars()]

    @staticmethod
    def _load(session: Session, node_id: str, lock: bool = False) -> Optional[NodeRow]:
        query = select(NodeRow).where(NodeRow.id == node_id).execution_options(populate_existing=True)
        if lock:
            query = query.with_for_update(key_share=True)  # FOR NO KEY UPDATE, as the job claim takes it
        return session.execute(query).scalar_one_or_none()
