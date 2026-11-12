"""Simulation subsystem terminology: stored fingerprint maps take the image name scenegems-simulation-subsystem.

SceneGEMS calls what was the scenario execution subsystem its simulation subsystem, and its image
scenegems-simulation-subsystem. No table, column or enum carries the old name, but the fingerprint
maps do, as the image they are keyed by: job.required_fingerprints, campaign.pinned_fingerprints,
run_record.fingerprints, calibration_result.fingerprints and the image of a worker node's
fingerprint rows. Without the rename a pinned campaign would wait for an image no worker node
reports any more.

A calibration result is found by the hash of its fingerprints, so the hash of every renamed map is
computed again, in SQL so the revision also renders offline: the canonical JSON of a map of strings
(persistence/canonical_json.py) is its pairs in key order without whitespace. Events keep their
text: they are history. Nothing is deleted, and the downgrade renames everything back.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-11
"""

from typing import Sequence, Tuple, Union

from alembic import op

revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_IMAGE = "scenegems-scenario-execution-subsystem"
NEW_IMAGE = "scenegems-simulation-subsystem"
# (table, JSONB column) holding a map of image name to fingerprint
FINGERPRINT_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("job", "required_fingerprints"),
    ("campaign", "pinned_fingerprints"),
    ("run_record", "fingerprints"),
    ("calibration_result", "fingerprints"),
)
# The canonical JSON of a JSONB map of strings: {"key":"value",...} with the keys in code point order
CANONICAL_FINGERPRINTS = (
    "'{' || COALESCE((SELECT string_agg(to_json(pair.key)::text || ':' || to_json(pair.value)::text, ',' ORDER BY pair.key COLLATE \"C\")"
    " FROM jsonb_each_text(calibration_result.fingerprints) AS pair), '') || '}'"
)


def _rename(old: str, new: str) -> None:
    # An image is named with or without a tag, so the name ends at the closing quote or at ':'
    op.execute(f"UPDATE worker_node_fingerprint SET image = '{new}' || substr(image, {len(old) + 1}) WHERE image = '{old}' OR starts_with(image, '{old}:')")
    for table, column in FINGERPRINT_COLUMNS:
        op.execute(
            f"UPDATE {table} SET {column} = replace(replace({column}::text, '\"{old}\"', '\"{new}\"'), '\"{old}:', '\"{new}:')::jsonb"
            f" WHERE {column} IS NOT NULL AND position('\"{old}' in {column}::text) > 0"
        )
    op.execute(f"UPDATE calibration_result SET fingerprints_hash = encode(sha256(convert_to({CANONICAL_FINGERPRINTS}, 'UTF8')), 'hex')" f" WHERE position('\"{new}' in fingerprints::text) > 0")


def upgrade() -> None:
    _rename(OLD_IMAGE, NEW_IMAGE)


def downgrade() -> None:
    _rename(NEW_IMAGE, OLD_IMAGE)
