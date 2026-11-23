"""Control node ids, worker node ids and broker usernames.

Each one becomes a single MQTT topic level (`scenegems/<control_node_id>/<worker_node_id>/...`), a part
of Docker container names and a file name. The rule below keeps
all three safe: lowercase letters, digits and hyphens, so no MQTT wildcard (`+`, `#`),
no level separator and no path component can ever appear in one.

A worker node's name is bounded tighter, at WORKER_NODE_NAME_MAX characters: the names of its objects in the
Kubernetes cluster start with it and take at most 63 characters, and with 28 its daemon's Deployment
(worker-node-<name>) and the Deployment of its pool with the longest subsystem name
(<name>-design-space-exploration-subsystem) fit whole (cluster/worker_node/instance_scope.py). The daemon, the
control node's Hello and the release's worker node role check it.
"""

import re

SCOPE_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
WORKER_NODE_NAME_MAX = 28
WORKER_NODE_NAME_PATTERN = re.compile(rf"^[a-z0-9](?:[a-z0-9-]{{0,{WORKER_NODE_NAME_MAX - 2}}}[a-z0-9])?$")


def is_scope_name(value: object) -> bool:
    return isinstance(value, str) and SCOPE_NAME_PATTERN.fullmatch(value) is not None


def is_worker_node_name(value: object) -> bool:
    """A worker node's name and id: a scope name of at most WORKER_NODE_NAME_MAX characters."""
    return isinstance(value, str) and WORKER_NODE_NAME_PATTERN.fullmatch(value) is not None
