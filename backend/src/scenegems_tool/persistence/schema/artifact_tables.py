"""Artifact records, their references, and calibration results.

An artifact is a content-addressed file in the control node's artifact store (P4.3); its row
records what the store holds. A reference names who needs the artifact (a case, a run, a
job, a calibration, an upload that expires), so retention can delete what nothing references
any more. Hashes are
sha256 as 64 lowercase hex characters everywhere, also in the columns of other tables.
"""

import re
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Float, ForeignKey, Identity, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from scenegems_tool.persistence.schema.base import Base, enum_column, utc_timestamp

SHA256_HEX_LENGTH = 64
SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SHA256_HEX_SQL_PATTERN = "^[0-9a-f]{64}$"


def sha256_hex_check(column: str, nullable: bool = False) -> str:
    """The CHECK constraint text that limits a column to sha256 hex strings."""
    check = f"{column} ~ '{SHA256_HEX_SQL_PATTERN}'"
    return f"{column} IS NULL OR {check}" if nullable else check


def require_sha256_hex(value: str) -> str:
    if not isinstance(value, str) or not SHA256_HEX_PATTERN.match(value):
        raise ValueError(f"expected a sha256 hash as 64 lowercase hex characters, got {value!r}")
    return value


class ArtifactHolderKind(str, Enum):
    CAMPAIGN = "campaign"
    CASE = "case"  # holder_id is the scenario_case id
    RUN = "run"  # holder_id is the run_record id
    JOB = "job"  # holder_id is the job id, for inputs and outputs of a job in flight
    CALIBRATION = "calibration"  # holder_id is the calibration_result id
    UPLOAD = "upload"  # holder_id is the artifact's hash: a file the operator uploaded, kept until expires_at


class ArtifactRow(Base):
    __tablename__ = "artifact"
    __table_args__ = (
        CheckConstraint(sha256_hex_check("hash"), name="hash_is_sha256_hex"),
        CheckConstraint("size_bytes >= 0", name="size_not_negative"),
        CheckConstraint("stored_size_bytes IS NULL OR stored_size_bytes >= 0", name="stored_size_not_negative"),
        # The retention sweep looks for old artifacts without references
        Index("ix_artifact_last_used_at", "last_used_at"),
    )

    hash: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH), primary_key=True)  # sha256 of the uncompressed content
    kind: Mapped[str] = mapped_column(String(64))  # what it holds: scene, trajectories, state_log, frames, ...
    size_bytes: Mapped[int] = mapped_column(BigInteger)  # uncompressed
    stored_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger)  # as stored (gzip), when the store reports it
    media_type: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(utc_timestamp())
    # Set when the artifact is stored again, gains or loses a reference. The sweep spares artifacts
    # used recently, so an upload is not deleted before the engine references it.
    last_used_at: Mapped[datetime] = mapped_column(utc_timestamp())


class ArtifactReferenceRow(Base):
    """One holder's need for one artifact, in one role. Holders are not foreign keys, since they live in several tables."""

    __tablename__ = "artifact_reference"
    __table_args__ = (
        UniqueConstraint("artifact_hash", "holder_kind", "holder_id", "role"),
        CheckConstraint("(holder_kind = 'upload') = (expires_at IS NOT NULL)", name="uploads_expire"),
        Index("ix_artifact_reference_holder_kind_holder_id", "holder_kind", "holder_id"),
        Index("ix_artifact_reference_campaign_id", "campaign_id"),
        Index("ix_artifact_reference_expires_at", "expires_at", postgresql_where=text("expires_at IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    artifact_hash: Mapped[str] = mapped_column(ForeignKey("artifact.hash", ondelete="RESTRICT"))
    holder_kind: Mapped[ArtifactHolderKind] = mapped_column(enum_column(ArtifactHolderKind, "holder_kind"))
    holder_id: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(64))  # scene, trajectories, state_log, frames, input, output, ...
    campaign_id: Mapped[Optional[str]] = mapped_column(ForeignKey("campaign.id", ondelete="CASCADE"))  # for retention per campaign
    created_at: Mapped[datetime] = mapped_column(utc_timestamp())
    expires_at: Mapped[Optional[datetime]] = mapped_column(utc_timestamp())  # upload references only; the sweep drops them after it


class CalibrationResultRow(Base):
    """The measured deviation of one stack, release and environment on one reference scenario.

    Stack, fingerprints and environment are JSON objects; their canonical JSON hashes form the
    key, so a lookup does not depend on key order.
    """

    __tablename__ = "calibration_result"
    __table_args__ = (
        UniqueConstraint("stack_hash", "fingerprints_hash", "environment_hash", "reference_scenario", name="uq_calibration_result_key"),  # the convention's name is too long
        CheckConstraint(sha256_hex_check("stack_hash"), name="stack_hash_is_sha256_hex"),
        CheckConstraint(sha256_hex_check("fingerprints_hash"), name="fingerprints_hash_is_sha256_hex"),
        CheckConstraint(sha256_hex_check("environment_hash"), name="environment_hash_is_sha256_hex"),
        CheckConstraint("repeats >= 1", name="repeats_positive"),
        CheckConstraint("deviation_bound_m IS NULL OR deviation_bound_m >= 0", name="deviation_bound_not_negative"),
        Index("ix_calibration_result_stack_hash_fingerprints_hash", "stack_hash", "fingerprints_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    stack: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    stack_hash: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH))
    fingerprints: Mapped[Dict[str, str]] = mapped_column(JSONB)  # image name to build fingerprint
    fingerprints_hash: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH))
    environment: Mapped[Dict[str, Any]] = mapped_column(JSONB)
    environment_hash: Mapped[str] = mapped_column(String(SHA256_HEX_LENGTH))
    reference_scenario: Mapped[str] = mapped_column(String(256))
    repeats: Mapped[int] = mapped_column(Integer)
    exact: Mapped[bool] = mapped_column(Boolean)  # every repeat had the same state digest
    deviation_bound_m: Mapped[Optional[float]] = mapped_column(Float)  # largest deviation between repeats; none when exact
    envelope: Mapped[Dict[str, Any]] = mapped_column(JSONB)  # the deviation envelope as the calibration job reports it
    campaign_id: Mapped[Optional[str]] = mapped_column(ForeignKey("campaign.id", ondelete="SET NULL"))  # the calibration campaign
    note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(utc_timestamp())
    updated_at: Mapped[datetime] = mapped_column(utc_timestamp())
