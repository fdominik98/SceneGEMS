"""Worker nodes as the control node knows them: identity, status, labels, resources, slots, components, fingerprints.

A worker node row is written from the worker node's Hello and updated by its heartbeats. Slots (per job type,
the worker_node_capability table), components and fingerprints are replaced as a whole on every Hello.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.persistence.schema.base import Base, enum_column, utc_timestamp


class WorkerNodeStatus(str, Enum):
    ONLINE = "online"  # connected and receives jobs
    DRAINING = "draining"  # finishes its running jobs, receives no new ones; set by the operator
    OFFLINE = "offline"  # missed its heartbeats


class WorkerNodeRow(Base):
    __tablename__ = "worker_node"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)  # worker node id from the Hello
    name: Mapped[str] = mapped_column(String(256))
    status: Mapped[WorkerNodeStatus] = mapped_column(enum_column(WorkerNodeStatus, "status"))
    labels: Mapped[Dict[str, str]] = mapped_column(JSONB)
    software_revision: Mapped[str] = mapped_column(String(64))
    machine: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)  # the machine the worker node runs on, as the deployment tool names it
    # Last reported resources, columns so the job claim filters on them in SQL
    cpus: Mapped[float] = mapped_column(Float)
    memory_mb: Mapped[int] = mapped_column(Integer)
    free_memory_mb: Mapped[int] = mapped_column(Integer)
    free_disk_mb: Mapped[int] = mapped_column(Integer)
    load_average: Mapped[float] = mapped_column(Float)
    registered_at: Mapped[datetime] = mapped_column(utc_timestamp())
    last_seen_at: Mapped[datetime] = mapped_column(utc_timestamp(), index=True)

    capabilities: Mapped[List["WorkerNodeCapabilityRow"]] = relationship(back_populates="worker_node", cascade="all, delete-orphan", order_by="WorkerNodeCapabilityRow.job_type")  # slots per job type
    components: Mapped[List["WorkerNodeComponentRow"]] = relationship(back_populates="worker_node", cascade="all, delete-orphan", order_by="WorkerNodeComponentRow.component")
    fingerprints: Mapped[List["WorkerNodeFingerprintRow"]] = relationship(back_populates="worker_node", cascade="all, delete-orphan", order_by="WorkerNodeFingerprintRow.image")


class WorkerNodeCapabilityRow(Base):
    """The slots of one job type: how many jobs of it the worker node runs at once."""

    __tablename__ = "worker_node_capability"
    __table_args__ = (
        CheckConstraint("slots >= 1", name="slots_positive"),
        CheckConstraint("slots_in_use >= 0", name="slots_in_use_not_negative"),
    )

    worker_node_id: Mapped[str] = mapped_column(ForeignKey("worker_node.id", ondelete="CASCADE"), primary_key=True)
    job_type: Mapped[JobType] = mapped_column(enum_column(JobType, "job_type"), primary_key=True)
    slots: Mapped[int] = mapped_column(Integer)
    slots_in_use: Mapped[int] = mapped_column(Integer)  # as the worker node last reported it; the claim counts leases itself

    worker_node: Mapped[WorkerNodeRow] = relationship(back_populates="capabilities")


class WorkerNodeComponentRow(Base):
    """One component the worker node offers (cluster/fingerprints/components.py), its images installed."""

    __tablename__ = "worker_node_component"

    worker_node_id: Mapped[str] = mapped_column(ForeignKey("worker_node.id", ondelete="CASCADE"), primary_key=True)
    component: Mapped[str] = mapped_column(String(64), primary_key=True)

    worker_node: Mapped[WorkerNodeRow] = relationship(back_populates="components")


class WorkerNodeFingerprintRow(Base):
    __tablename__ = "worker_node_fingerprint"

    worker_node_id: Mapped[str] = mapped_column(ForeignKey("worker_node.id", ondelete="CASCADE"), primary_key=True)
    image: Mapped[str] = mapped_column(String(256), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(256))

    worker_node: Mapped[WorkerNodeRow] = relationship(back_populates="fingerprints")
