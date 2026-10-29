"""The domain presets the master offers: the YAML files under backend/assets/domain_config/.

A domain configuration is three texts, named by their campaign config keys:
colregs_constants (domain_config/colregs_constants/), vessel_types (domain_config/vessel_types/)
and obstacle_types (domain_config/static_obstacle_types/). Each .yaml file of a folder is a
preset named by its file name without the extension; one per key is the default, which a
campaign without its own content and a cluster without a saved domain configuration use.
Contents have LF line endings, so a Windows and a Linux checkout offer the same text.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Tuple

from utils.file_system_utils import COLREGS_CONSTANTS_FOLDER, STATIC_OBSTACLE_TYPES_FOLDER, VESSEL_TYPES_FOLDER

DOMAIN_KEYS = ("colregs_constants", "vessel_types", "obstacle_types")
PRESET_FOLDERS: Dict[str, Path] = {
    "colregs_constants": Path(COLREGS_CONSTANTS_FOLDER),
    "vessel_types": Path(VESSEL_TYPES_FOLDER),
    "obstacle_types": Path(STATIC_OBSTACLE_TYPES_FOLDER),
}
DEFAULT_PRESETS: Dict[str, str] = {
    "colregs_constants": "general_maritime_constants",
    "vessel_types": "vessel_types",
    "obstacle_types": "static_obstacle_types",
}
PRESET_SUFFIX = ".yaml"


@dataclass(frozen=True)
class DomainPreset:
    key: str  # colregs_constants, vessel_types or obstacle_types
    name: str  # the file name without .yaml
    content: str
    default: bool


def normalize_newlines(content: str) -> str:
    return content.replace("\r\n", "\n").replace("\r", "\n")


def read_domain_file(path: Path) -> str:
    return normalize_newlines(path.read_text(encoding="utf-8"))


def default_preset_file(key: str) -> Path:
    return PRESET_FOLDERS[key] / f"{DEFAULT_PRESETS[key]}{PRESET_SUFFIX}"


def domain_presets(folders: Mapping[str, Path] = PRESET_FOLDERS) -> Dict[str, Tuple[DomainPreset, ...]]:
    """The presets per key, by name; a missing folder offers none."""
    presets: Dict[str, Tuple[DomainPreset, ...]] = {}
    for key in DOMAIN_KEYS:
        folder = Path(folders[key])
        files = sorted(folder.glob(f"*{PRESET_SUFFIX}")) if folder.is_dir() else []
        presets[key] = tuple(DomainPreset(key, path.stem, read_domain_file(path), path.stem == DEFAULT_PRESETS[key]) for path in files)
    return presets


def default_domain() -> Dict[str, str]:
    """The default presets' contents by key: the domain configuration of a cluster that never saved one."""
    return {key: read_domain_file(default_preset_file(key)) for key in DOMAIN_KEYS}
