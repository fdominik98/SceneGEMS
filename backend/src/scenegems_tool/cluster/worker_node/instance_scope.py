"""Identity of one subsystem instance on a worker node, and every name derived from it.

Contract with the broker access rules (design doc 13.7, "Cluster topic scope"):
    topic prefix      scenegems/<control_node_id>/<worker_node_id>/<instance_id>/
    docker names      scenegems-<control_node_id>-<worker_node_id>-<instance_id> (compose project, containers, networks)
    instance id       <subsystem>-<index> for a pooled service, job-<job_id> for a per-job stack

The ids are lowercase letters, digits, '-' and '_', so every derived name is valid as an
MQTT topic level, a Docker container name and a compose project name. A live session of the
workbench is an instance too: worker node `workbench`, instance `live-<session>` (InstanceScope.live_session).
Its Docker names always come from the scope; its topic prefix is used only on the control node's
broker (gateway/socket_session.py), since other brokers carry unscoped WARA-PS topics.
"""

import re
from dataclasses import dataclass

from utils.file_system_utils import RUNTIME_ASSETS_FOLDER

SCOPE_ROOT = "scenegems"
LIVE_SESSION_WORKER_NODE_ID = "workbench"  # the worker node level of the workbench's live sessions
LIVE_SESSION_INSTANCE_PREFIX = "live-"
INSTANCES_FOLDER = f"{RUNTIME_ASSETS_FOLDER}/instances"  # compose files and generated files of scoped instances, one folder each
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_UNSAFE_ID_CHARACTERS = re.compile(r"[^a-z0-9_-]+")
_DOCKER_NAME_MAX = 128


def _require_id(kind: str, value: str) -> str:
    if not _ID_PATTERN.match(value):
        raise ValueError(f"Invalid {kind} {value!r}: use lowercase letters, digits, '-' and '_', starting with a letter or digit")
    return value


def safe_id(value: str) -> str:
    """An id usable in a scope from any string, such as a job id: lowercase, other characters replaced by '-'."""
    cleaned = _UNSAFE_ID_CHARACTERS.sub("-", value.lower()).strip("-_")
    if not cleaned:
        raise ValueError(f"Cannot derive a scope id from {value!r}")
    return cleaned


def live_session_project_prefix(control_node_id: str) -> str:
    """The compose project names of every live session of one control node start with this."""
    return f"{SCOPE_ROOT}-{_require_id('control node id', control_node_id)}-{LIVE_SESSION_WORKER_NODE_ID}-{LIVE_SESSION_INSTANCE_PREFIX}"


def worker_node_topic_scope(control_node_id: str, worker_node_id: str) -> str:
    """The topic subtree a worker node's broker account may use: every instance prefix of the worker node lies under it."""
    return f"{SCOPE_ROOT}/{_require_id('control node id', control_node_id)}/{_require_id('worker node id', worker_node_id)}/"


@dataclass(frozen=True)
class InstanceScope:
    control_node_id: str
    worker_node_id: str
    instance_id: str

    def __post_init__(self) -> None:
        _require_id("control node id", self.control_node_id)
        _require_id("worker node id", self.worker_node_id)
        _require_id("instance id", self.instance_id)
        if len(self.docker_name) > _DOCKER_NAME_MAX:
            raise ValueError(f"Scope name {self.docker_name!r} is longer than {_DOCKER_NAME_MAX} characters")

    @classmethod
    def pooled(cls, control_node_id: str, worker_node_id: str, subsystem: str, index: int = 0) -> "InstanceScope":
        """A long-lived service instance; index tells apart several pools of one subsystem on a worker node."""
        if index < 0:
            raise ValueError(f"Pool index must not be negative: {index}")
        return cls(control_node_id, worker_node_id, f"{_require_id('subsystem', subsystem)}-{index}")

    @classmethod
    def per_job(cls, control_node_id: str, worker_node_id: str, job_id: str) -> "InstanceScope":
        return cls(control_node_id, worker_node_id, f"job-{safe_id(job_id)}")

    @classmethod
    def live_session(cls, control_node_id: str, session_id: str) -> "InstanceScope":
        """One live session of the workbench: its simulation stack, and its topics on the control node's broker."""
        return cls(control_node_id, LIVE_SESSION_WORKER_NODE_ID, f"{LIVE_SESSION_INSTANCE_PREFIX}{safe_id(session_id)}")

    @property
    def topic_prefix(self) -> str:
        return f"{worker_node_topic_scope(self.control_node_id, self.worker_node_id)}{self.instance_id}/"

    @property
    def docker_name(self) -> str:
        return f"{SCOPE_ROOT}-{self.control_node_id}-{self.worker_node_id}-{self.instance_id}"

    @property
    def compose_project(self) -> str:
        return self.docker_name

    def container_name(self, service: str) -> str:
        """Name of one service's container; a single-service instance uses the bare scope name."""
        return f"{self.docker_name}-{safe_id(service)}"

    def network_name(self, key: str) -> str:
        return f"{self.docker_name}-{safe_id(key)}"

    @property
    def folder(self) -> str:
        """Local folder of the instance's compose file and generated files, on the runtime assets volume."""
        return f"{INSTANCES_FOLDER}/{self.docker_name}"
