"""Reading a worker node's `.env` file: KEY=VALUE lines, as Docker Compose writes and reads them.

Blank lines and lines starting with '#' are skipped, an `export ` prefix is allowed, and a
value in matching single or double quotes is taken without them. Anything else is an
error that names the line, so a typo fails at start instead of becoming a wrong value.
"""

import re
from pathlib import Path
from typing import Dict

_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class EnvFileError(ValueError):
    pass


def parse_env_text(text: str, source: str = ".env") -> Dict[str, str]:
    values: Dict[str, str] = {}
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or not _KEY.match(key):
            raise EnvFileError(f"{source}, line {number}: expected KEY=VALUE, got {raw_line.strip()!r}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def read_env_file(path: Path) -> Dict[str, str]:
    path = Path(path)
    return parse_env_text(path.read_text(encoding="utf-8"), str(path))
