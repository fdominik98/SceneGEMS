"""The cluster's own settings: its domain configuration and the campaign presets operators saved.

    cluster_domain   one row at most (id 1): the COLREGS constants, vessel types and obstacle types every
                     workbench run and every campaign without its own domain content uses. Without the row
                     the master's default domain files apply.
    campaign_preset  campaign configs saved under a name, to start the wizard from. The presets shipped in
                     the master image are files (backend/assets/campaign_presets/), not rows.
"""

from datetime import datetime
from typing import Any, Dict

from sqlalchemy import CheckConstraint, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from scenegems_tool.persistence.schema.base import Base, utc_timestamp

CLUSTER_DOMAIN_ROW_ID = 1
PRESET_NAME_LENGTH = 200


class ClusterDomainRow(Base):
    __tablename__ = "cluster_domain"
    __table_args__ = (CheckConstraint(f"id = {CLUSTER_DOMAIN_ROW_ID}", name="single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    colregs_constants: Mapped[str] = mapped_column(Text)  # YAML content, LF line endings
    vessel_types: Mapped[str] = mapped_column(Text)
    obstacle_types: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(utc_timestamp())


class CampaignPresetRow(Base):
    __tablename__ = "campaign_preset"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(PRESET_NAME_LENGTH), unique=True)
    description: Mapped[str] = mapped_column(Text)
    config: Mapped[Dict[str, Any]] = mapped_column(JSONB)  # the campaign config as saved, without its input section
    created_at: Mapped[datetime] = mapped_column(utc_timestamp())
    updated_at: Mapped[datetime] = mapped_column(utc_timestamp())
