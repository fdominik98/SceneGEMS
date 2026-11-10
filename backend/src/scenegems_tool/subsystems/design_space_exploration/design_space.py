"""The input of a design space exploration: the specification text and the scope, as operators write them.

A specification is Refinery source: the metamodel (enums and classes), the predicates and the well-formedness
constraints (error predicates) of a scenario family, the first part of every FEC specification in the catalog, and
whatever the family fixes (the default pins the own ship). The scope says how many instances of a class a model has:

    TS = 2, StaticObstacle = 0        exactly two target ships, no static obstacle
    TS = 1..3                         one to three target ships

Entries are separated by commas; each is `<class> = <count>` or `<class> = <lower>..<upper>`. Both bounds must be
whole numbers, since the exploration only ends when every upper bound is finite. parse_scope gives the entries in the
form the Refinery generator takes them (`TS=2`, `TS=1..3`).

A generated model is the specification's metamodel and constraints as given, followed by the model (its instances and
relations, the fixed ones included), so it reads as a FEC specification of the catalog does: functional_level/models/model_parser.py parses it from its first `declare`.
"""

import hashlib
import re
from functools import lru_cache
from typing import Tuple

from utils.file_system_utils import ASSET_FOLDER

DEFAULT_SPECIFICATION_FILE = f"{ASSET_FOLDER}/design_space/default_specification.problem"
DEFAULT_SCOPE = "TS = 2, StaticObstacle = 0"
MAX_SCOPE_COUNT = 1000  # a typo guard: no scenario family has this many vessels

# The instances a model declares, as the class catalog counts them (assurance/campaign/class_catalog.py)
_VESSEL = re.compile(r"^(?:OS|TS)\(\w+\)\.\s*$", re.MULTILINE)
_STATIC_OBSTACLE = re.compile(r"^StaticObstacle\(\w+\)\.\s*$", re.MULTILINE)
_ENTRY = re.compile(r"^\s*(?P<type>[A-Za-z_]\w*)\s*=\s*(?P<lower>\d+)\s*(?:\.\.\s*(?P<upper>\d+)\s*)?$")


class ScopeError(ValueError):
    """A scope that is not a list of `<class> = <count>` or `<class> = <lower>..<upper>` entries."""


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def parse_scope(scope: str) -> Tuple[str, ...]:
    """The scope's entries as the generator takes them (`TS=2`, `StaticObstacle=0..1`), in the order given; raises ScopeError."""
    entries = [entry for entry in scope.split(",")]
    if not scope.strip():
        raise ScopeError("the scope is empty; give at least one entry such as TS = 2")
    parsed = []
    seen = set()
    for entry in entries:
        match = _ENTRY.match(entry)
        if match is None:
            raise ScopeError(f"{entry.strip()!r} is not a scope entry; write <class> = <count> or <class> = <lower>..<upper>, for example TS = 2 or TS = 1..3")
        name, lower = match.group("type"), int(match.group("lower"))
        upper = int(match.group("upper")) if match.group("upper") is not None else lower
        if upper < lower:
            raise ScopeError(f"{entry.strip()!r}: the upper bound {upper} is below the lower bound {lower}")
        if upper > MAX_SCOPE_COUNT:
            raise ScopeError(f"{entry.strip()!r}: a scope bound is at most {MAX_SCOPE_COUNT}")
        if name in seen:
            raise ScopeError(f"the scope names {name} twice")
        seen.add(name)
        parsed.append(f"{name}={lower}" if upper == lower else f"{name}={lower}..{upper}")
    return tuple(parsed)


def count_instances(model: str) -> Tuple[int, int]:
    """(vessels, static obstacles) a generated model declares: its own ship and target ships, its obstacles."""
    return len(_VESSEL.findall(model)), len(_STATIC_OBSTACLE.findall(model))


def exploration_hash(specification: str, scope: str) -> str:
    """The hash that pins what an exploration explores: the specification with LF line endings and the scope's entries."""
    canonical = normalize_newlines(specification) + "\n\x00" + ",".join(parse_scope(scope))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@lru_cache(maxsize=1)
def default_specification() -> str:
    """The specification the master ships: the catalog's metamodel and constraints with the own ship fixed."""
    with open(DEFAULT_SPECIFICATION_FILE, encoding="utf-8") as file:
        return normalize_newlines(file.read())
