"""The catalog of functional scenarios a campaign draws its classes from.

The catalog is backend/assets/generated_functional_models/all/, found the way
utils/file_system_utils finds the assets, so it is the same in a checkout and in the
backend image the master runs. A class is one .problem file; its id is its path relative
to all/ without the extension (`3vessel_0obstacle_scenarios/fec5`). Each class
carries the sha256 of its content with LF line endings (equal in a Windows and a Linux
checkout) and its vessel and obstacle counts, read from the instances it declares.
"""

import hashlib
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from utils.file_system_utils import FUNCTIONAL_MODELS_FOLDER

CATALOG_FOLDER = Path(FUNCTIONAL_MODELS_FOLDER) / "all"
PROBLEM_SUFFIX = ".problem"

_OWN_SHIP = re.compile(r"^OS\(\w+\)\.\s*$", re.MULTILINE)
_TARGET_SHIP = re.compile(r"^TS\(\w+\)\.\s*$", re.MULTILINE)
_STATIC_OBSTACLE = re.compile(r"^StaticObstacle\(\w+\)\.\s*$", re.MULTILINE)
_DIGITS = re.compile(r"(\d+)")


class UnknownClassId(LookupError):
    pass


def natural_key(text: str) -> Tuple:
    """Sorts fec2 before fec10; every part is an (int, str) pair, so any two ids compare."""
    return tuple((int(part), "") if part.isdigit() else (-1, part) for part in _DIGITS.split(text))


def read_problem(path: Path) -> str:
    """A .problem file's content with LF line endings."""
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def count_instances(content: str) -> Tuple[int, int]:
    """(vessels, static obstacles) a functional scenario declares: its own ship and target ships, its obstacles."""
    return len(_OWN_SHIP.findall(content)) + len(_TARGET_SHIP.findall(content)), len(_STATIC_OBSTACLE.findall(content))


@dataclass(frozen=True)
class ScenarioClass:
    class_id: str
    path: Path
    content_hash: str  # sha256 of the content with LF line endings
    vessel_count: int
    obstacle_count: int

    @property
    def folder(self) -> str:
        return self.class_id.split("/", 1)[0]

    def read_content(self) -> str:
        return read_problem(self.path)


class ClassCatalog:
    def __init__(self, root: Path = CATALOG_FOLDER):
        self.root = Path(root)
        self._classes: Optional[Dict[str, ScenarioClass]] = None

    @classmethod
    def default(cls) -> "ClassCatalog":
        return _default_catalog()

    def classes(self) -> Tuple[ScenarioClass, ...]:
        """Every class in catalog order: by folder, then by file, numbers in numeric order."""
        return tuple(self._load().values())

    def folders(self) -> Tuple[str, ...]:
        return tuple(dict.fromkeys(scenario_class.folder for scenario_class in self.classes()))

    def get(self, class_id: str) -> ScenarioClass:
        found = self._load().get(class_id)
        if found is None:
            raise UnknownClassId(f"no FEC {class_id!r} in the catalog at {self.root}")
        return found

    def expand(self, pattern: str) -> Tuple[ScenarioClass, ...]:
        """The classes a pattern names, in catalog order: by folder without a slash, by class id with one."""
        if "/" in pattern:
            return tuple(scenario_class for scenario_class in self.classes() if fnmatchcase(scenario_class.class_id, pattern))
        return tuple(scenario_class for scenario_class in self.classes() if fnmatchcase(scenario_class.folder, pattern))

    def __contains__(self, class_id: str) -> bool:
        return class_id in self._load()

    def __len__(self) -> int:
        return len(self._load())

    def __iter__(self) -> Iterator[ScenarioClass]:
        return iter(self.classes())

    def _load(self) -> Dict[str, ScenarioClass]:
        if self._classes is None:
            if not self.root.is_dir():
                raise FileNotFoundError(f"the FEC catalog folder {self.root} does not exist")
            found: List[ScenarioClass] = []
            for path in self.root.glob(f"*/*{PROBLEM_SUFFIX}"):
                content = read_problem(path)
                vessels, obstacles = count_instances(content)
                class_id = f"{path.parent.name}/{path.stem}"
                found.append(ScenarioClass(class_id, path, hashlib.sha256(content.encode("utf-8")).hexdigest(), vessels, obstacles))
            self._classes = {scenario_class.class_id: scenario_class for scenario_class in sorted(found, key=lambda item: natural_key(item.class_id))}
        return self._classes


@lru_cache(maxsize=1)
def _default_catalog() -> ClassCatalog:
    return ClassCatalog()
