"""Control node ids, worker node ids and broker usernames.

Each one becomes a single MQTT topic level (`scenegems/<control_node_id>/<worker_node_id>/...`), a part
of Docker container names and a file name. The rule below keeps
all three safe: lowercase letters, digits and hyphens, so no MQTT wildcard (`+`, `#`),
no level separator and no path component can ever appear in one.
"""

import re

SCOPE_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def is_scope_name(value: object) -> bool:
    return isinstance(value, str) and SCOPE_NAME_PATTERN.fullmatch(value) is not None
