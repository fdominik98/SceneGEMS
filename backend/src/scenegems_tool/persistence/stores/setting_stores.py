"""The cluster's settings: its domain configuration and the campaign presets operators saved.

The domain store holds one domain configuration per cluster (the cluster_domain row). Until
it is saved once, current() is None and the control node's default domain files apply. The preset
store keeps campaign configs under unique names; it knows nothing of the presets shipped as
files, which the operator API lists beside these.

Every method takes an optional session (see store_session). Contents are stored as given;
the operator API checks them first.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from scenegems_tool.persistence.clock import Clock, utc_now
from scenegems_tool.persistence.schema import CLUSTER_DOMAIN_ROW_ID, CampaignPresetRow, ClusterDomainRow
from scenegems_tool.persistence.stores.store_session import session_scope


@dataclass(frozen=True)
class ClusterDomain:
    colregs_constants: str
    vessel_types: str
    obstacle_types: str
    updated_at: datetime

    @classmethod
    def from_row(cls, row: ClusterDomainRow) -> "ClusterDomain":
        return cls(row.colregs_constants, row.vessel_types, row.obstacle_types, row.updated_at)

    def contents(self) -> Dict[str, str]:
        """The three texts by their campaign config keys (domain.colregs_constants, vessel_types, obstacle_types)."""
        return {"colregs_constants": self.colregs_constants, "vessel_types": self.vessel_types, "obstacle_types": self.obstacle_types}


class DomainStore:
    def __init__(self, session_factory: sessionmaker[Session], clock: Clock = utc_now):
        self._sessions = session_factory
        self._clock = clock

    def current(self, *, session: Optional[Session] = None) -> Optional[ClusterDomain]:
        """The saved domain configuration; None while it was never saved."""
        with session_scope(self._sessions, session) as scope:
            row = scope.get(ClusterDomainRow, CLUSTER_DOMAIN_ROW_ID, populate_existing=True)
            return None if row is None else ClusterDomain.from_row(row)

    def save(self, colregs_constants: str, vessel_types: str, obstacle_types: str, *, session: Optional[Session] = None) -> ClusterDomain:
        """Replaces the cluster's domain configuration."""
        values = dict(colregs_constants=colregs_constants, vessel_types=vessel_types, obstacle_types=obstacle_types, updated_at=self._clock())
        with session_scope(self._sessions, session) as scope:
            statement = insert(ClusterDomainRow).values(id=CLUSTER_DOMAIN_ROW_ID, **values).on_conflict_do_update(index_elements=[ClusterDomainRow.id], set_=values)
            scope.execute(statement)
            return ClusterDomain.from_row(scope.get(ClusterDomainRow, CLUSTER_DOMAIN_ROW_ID, populate_existing=True))


class PresetNameTaken(ValueError):
    pass


class UnknownPreset(LookupError):
    pass


@dataclass(frozen=True)
class SavedPreset:
    preset_id: str
    name: str
    description: str
    config: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_row(cls, row: CampaignPresetRow) -> "SavedPreset":
        return cls(row.id, row.name, row.description, dict(row.config), row.created_at, row.updated_at)


class CampaignPresetStore:
    def __init__(self, session_factory: sessionmaker[Session], clock: Clock = utc_now):
        self._sessions = session_factory
        self._clock = clock

    def list_presets(self, *, session: Optional[Session] = None) -> List[SavedPreset]:
        """Every saved preset by name."""
        with session_scope(self._sessions, session) as scope:
            query = select(CampaignPresetRow).order_by(CampaignPresetRow.name).execution_options(populate_existing=True)
            return [SavedPreset.from_row(row) for row in scope.execute(query).scalars()]

    def get(self, preset_id: str, *, session: Optional[Session] = None) -> Optional[SavedPreset]:
        with session_scope(self._sessions, session) as scope:
            row = scope.get(CampaignPresetRow, preset_id, populate_existing=True)
            return None if row is None else SavedPreset.from_row(row)

    def save(self, name: str, description: str, config: Dict[str, Any], replace: bool = False, *, session: Optional[Session] = None) -> Tuple[SavedPreset, bool]:
        """A new preset, or with replace the preset of that name with this description and config (it keeps its id); (preset, whether it replaced one).

        PresetNameTaken when a preset has the name and replace is false.
        """
        now = self._clock()
        with session_scope(self._sessions, session) as scope:
            row = scope.execute(select(CampaignPresetRow).where(CampaignPresetRow.name == name).with_for_update()).scalar_one_or_none()
            replaced = row is not None
            if replaced and not replace:
                raise PresetNameTaken(f"a saved preset is named {name!r}")
            if row is None:
                row = CampaignPresetRow(id=str(uuid4()), name=name, description=description, config=config, created_at=now, updated_at=now)
                scope.add(row)
            else:
                row.description = description
                row.config = config
                row.updated_at = now
            try:
                scope.flush()
            except IntegrityError as error:  # another request saved the name in the meantime
                raise PresetNameTaken(f"a saved preset is named {name!r}") from error
            return SavedPreset.from_row(row), replaced

    def delete(self, preset_id: str, *, session: Optional[Session] = None) -> None:
        """Deletes a saved preset; UnknownPreset when there is none with the id."""
        with session_scope(self._sessions, session) as scope:
            row = scope.get(CampaignPresetRow, preset_id)
            if row is None:
                raise UnknownPreset(preset_id)
            scope.delete(row)
