"""Nodes as the master knows them: identity, status, labels, resources, slots, components, fingerprints.

A node row is written from the node's Hello and updated by its heartbeats. Slots (per job type,
the node_capability table), components and fingerprints are replaced as a whole on every Hello.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.persistence.schema.base import Base, enum_column, utc_timestamp


class NodeStatus(str, Enum):
    ONLINE = "online"  # connected and receives jobs
    DRAINING = "draining"  # finishes its running jobs, receives no new ones; set by the operator
    OFFLINE = "offline"  # missed its heartbeats


class NodeRow(Base):
    __tablename__ = "node"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # node id from the Hello
    name: Mapped[str] = mapped_column(String(256))
    status: Mapped[NodeStatus] = mapped_column(enum_column(NodeStatus, "status"))
    labels: Mapped[Dict[str, str]] = mapped_column(JSONB)
    software_revision: Mapped[str] = mapped_column(String(64))
    machine: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)  # the machine the node runs on, as the deployment tool names it
    # Last reported resources, columns so the job claim filters on them in SQL
    cpus: Mapped[float] = mapped_column(Float)
    memory_mb: Mapped[int] = mapped_column(Integer)
    free_memory_mb: Mapped[int] = mapped_column(Integer)
    free_disk_mb: Mapped[int] = mapped_column(Integer)
    load_average: Mapped[float] = mapped_column(Float)
    registered_at: Mapped[datetime] = mapped_column(utc_timestamp())
    last_seen_at: Mapped[datetime] = mapped_column(utc_timestamp(), index=True)

    capabilities: Mapped[List["NodeCapabilityRow"]] = relationship(back_populates="node", cascade="all, delete-orphan", order_by="NodeCapabilityRow.job_type")  # slots per job type
    components: Mapped[List["NodeComponentRow"]] = relationship(back_populates="node", cascade="all, delete-orphan", order_by="NodeComponentRow.component")
    fingerprints: Mapped[List["NodeFingerprintRow"]] = relationship(back_populates="node", cascade="all, delete-orphan", order_by="NodeFingerprintRow.image")


class NodeCapabilityRow(Base):
    """The slots of one job type: how many jobs of it the node runs at once."""

    __tablename__ = "node_capability"
    __table_args__ = (
        CheckConstraint("slots >= 1", name="slots_positive"),
        CheckConstraint("slots_in_use >= 0", name="slots_in_use_not_negative"),
    )

    node_id: Mapped[str] = mapped_column(ForeignKey("node.id", ondelete="CASCADE"), primary_key=True)
    job_type: Mapped[JobType] = mapped_column(enum_column(JobType, "job_type"), primary_key=True)
    slots: Mapped[int] = mapped_column(Integer)
    slots_in_use: Mapped[int] = mapped_column(Integer)  # as the node last reported it; the claim counts leases itself

    node: Mapped[NodeRow] = relationship(back_populates="capabilities")


class NodeComponentRow(Base):
    """One component the node offers (cluster/fingerprints/components.py), its images installed."""

    __tablename__ = "node_component"

    node_id: Mapped[str] = mapped_column(ForeignKey("node.id", ondelete="CASCADE"), primary_key=True)
    component: Mapped[str] = mapped_column(String(64), primary_key=True)

    node: Mapped[NodeRow] = relationship(back_populates="components")


class NodeFingerprintRow(Base):
    __tablename__ = "node_fingerprint"

    node_id: Mapped[str] = mapped_column(ForeignKey("node.id", ondelete="CASCADE"), primary_key=True)
    image: Mapped[str] = mapped_column(String(256), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(256))

    node: Mapped[NodeRow] = relationship(back_populates="fingerprints")
