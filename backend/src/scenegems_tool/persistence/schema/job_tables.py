"""Jobs and their append-only history.

A job row holds the submission, the queue state and the latest lease. The lease columns
describe the most recent lease and are only active while the state is leased or running.
Attempts count leases (the attempt number of the latest one); failed attempts count the
leases that ended in a failure or an expiry, and max_attempts limits those.

A queued job is claimed only once its available_at has passed: a retryable failure moves
it ahead by the backoff, and holding a campaign's jobs (pause) moves it to HELD_UNTIL.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import BigInteger, CheckConstraint, Float, ForeignKey, Identity, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from scenegems_tool.cluster.protocol.jobs import JobState, JobType
from scenegems_tool.persistence.schema.base import Base, enum_column, utc_timestamp

HELD_UNTIL = datetime(9999, 1, 1, tzinfo=timezone.utc)  # available_at of a held job

# The id of the writing transaction as a bigint (xid8 values stay far below 2**63)
CURRENT_TRANSACTION_ID = "(pg_current_xact_id()::text::bigint)"


class JobRow(Base):
    __tablename__ = "job"
    __table_args__ = (
        CheckConstraint("max_attempts >= 1", name="max_attempts_positive"),
        CheckConstraint("attempt >= 0", name="attempt_not_negative"),
        CheckConstraint("failed_attempts >= 0 AND failed_attempts <= attempt", name="failed_attempts_within_attempts"),
        CheckConstraint("state NOT IN ('leased', 'running') OR (lease_id IS NOT NULL AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)", name="active_lease_complete"),
        # The claim walks this index in queue order
        Index("ix_job_queue_order", text("priority DESC"), "submitted_at", "seq", postgresql_where=text("state = 'queued'")),
        Index("ix_job_active_lease_expiry", "lease_expires_at", postgresql_where=text("state IN ('leased', 'running')")),
        Index("ix_job_lease_owner_state", "lease_owner", "state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), unique=True)  # submission order among equal timestamps
    job_type: Mapped[JobType] = mapped_column(enum_column(JobType, "job_type"))
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    # JobRequirements, one column each so the claim filters on them in SQL
    required_labels: Mapped[Dict[str, str]] = mapped_column(JSONB)
    required_fingerprints: Mapped[Dict[str, str]] = mapped_column(JSONB)
    required_components: Mapped[List[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))  # contained in the claiming worker node's usable components
    min_memory_mb: Mapped[int] = mapped_column(Integer)
    min_cpus: Mapped[float] = mapped_column(Float)
    allowed_worker_nodes: Mapped[List[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))  # worker node ids that may claim the job, empty for any
    priority: Mapped[int] = mapped_column(Integer)  # higher runs first
    max_attempts: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(256), unique=True)

    state: Mapped[JobState] = mapped_column(enum_column(JobState, "state"))
    attempt: Mapped[int] = mapped_column(Integer)
    failed_attempts: Mapped[int] = mapped_column(Integer)
    lease_id: Mapped[Optional[str]] = mapped_column(String(36), unique=True)
    lease_owner: Mapped[Optional[str]] = mapped_column(ForeignKey("worker_node.id"))
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(utc_timestamp())

    submitted_at: Mapped[datetime] = mapped_column(utc_timestamp())
    available_at: Mapped[datetime] = mapped_column(utc_timestamp())  # not claimed before; backoff and holds move it
    updated_at: Mapped[datetime] = mapped_column(utc_timestamp())
    started_at: Mapped[Optional[datetime]] = mapped_column(utc_timestamp())  # first accepted lease
    finished_at: Mapped[Optional[datetime]] = mapped_column(utc_timestamp())

    result_attempt: Mapped[Optional[int]] = mapped_column(Integer)  # attempt whose result was stored last
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB)
    error: Mapped[Optional[str]] = mapped_column(Text)


class JobEventKind(str, Enum):
    SUBMITTED = "submitted"
    LEASED = "leased"  # claimed for a worker node and offered
    ACCEPTED = "accepted"
    REJECTED = "rejected"  # the worker node refused the offer; back to the queue, no failed attempt
    RELEASED = "released"  # the worker node gave the job back unfinished; back to the queue, no failed attempt
    EXPIRED = "expired"  # the lease ran out; a failed attempt
    ATTEMPT_FAILED = "attempt_failed"  # a retryable failure; back to the queue
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobEventRow(Base):
    """One state change of a job. Rows are only ever inserted.

    Event ids are taken at insert, so a transaction that commits late can make an event
    visible after one with a higher id. tx_id is the writing transaction's id: a reader
    that takes only events of transactions older than every transaction still running
    (pg_snapshot_xmin), in (tx_id, id) order, sees each event once and skips none.
    """

    __tablename__ = "job_event"
    __table_args__ = (
        Index("ix_job_event_job_id_id", "job_id", "id"),
        Index("ix_job_event_tx_id_id", "tx_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    tx_id: Mapped[int] = mapped_column(BigInteger, server_default=text(CURRENT_TRANSACTION_ID))
    job_id: Mapped[str] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(utc_timestamp())
    kind: Mapped[JobEventKind] = mapped_column(enum_column(JobEventKind, "kind"))
    from_state: Mapped[Optional[JobState]] = mapped_column(enum_column(JobState, "from_state"))
    to_state: Mapped[JobState] = mapped_column(enum_column(JobState, "to_state"))
    attempt: Mapped[int] = mapped_column(Integer)
    lease_id: Mapped[Optional[str]] = mapped_column(String(36))
    worker_node_id: Mapped[Optional[str]] = mapped_column(String(128))
    detail: Mapped[Dict[str, Any]] = mapped_column(JSONB)
