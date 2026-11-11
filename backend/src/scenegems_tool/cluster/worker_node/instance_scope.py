"""Identity of one subsystem instance on a worker node, and every Docker name derived from it.

A worker node is one compose project, scenegems-<control_node_id>-<worker_node_id>: the daemon, the
pooled services and the containers of every job carry it, so Docker lists them as one group. Inside
the project an instance is named after its subsystem:

    pooled service          scene-generation-subsystem
    single-container job    monitoring-subsystem-<job>
    container of a stack    simulation-subsystem-<job>-<part>, such as -runner or -kinematic-sim

<job> is the first characters of the job id (JOB_ID_LENGTH), with the attempt after it on a retry.
The full container name starts with the project name.

Compose tells the containers of a project apart by their service key, so the key of a service is
unique in the project too (`service_key`), and an instance is found again by its label
(INSTANCE_LABEL), whose value is the instance's `key`: the full job id and attempt for a job, which
two jobs never share even when their short names do.

The ids are lowercase letters, digits, '-' and '_', so every derived name is valid as a Docker
container name and a compose project name. MQTT topics do not come from here: a topic names the
subsystem or vessel that publishes and not the worker node it runs on (messaging/mqtt_client.py).

A live session of the workbench still runs on the control node as a compose project of its own with
a topic prefix (LiveSessionScope); it goes away with the control node's live sessions.
"""

import re
from dataclasses import dataclass
from typing import Dict

from utils.file_system_utils import RUNTIME_ASSETS_FOLDER

SCOPE_ROOT = "scenegems"
SUBSYSTEM_SUFFIX = "-subsystem"
JOB_ID_LENGTH = 8  # characters of the job id in a job instance's name
INSTANCE_LABEL = "scenegems.instance"  # on every container and network of an instance; its value is the scope's key
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


def docker_word(value: str) -> str:
    """A part of a Docker name in one spelling: lowercase with hyphens, so kinematic_sim reads kinematic-sim."""
    return safe_id(value).replace("_", "-")


def subsystem_name(subsystem: str) -> str:
    """The name a subsystem's instances carry in Docker and on MQTT: scene_generation is scene-generation-subsystem."""
    return f"{docker_word(_require_id('subsystem', subsystem))}{SUBSYSTEM_SUFFIX}"


def pooled_service_name(subsystem: str, instance_number: int) -> str:
    """The name of a worker node's pooled service on MQTT, unique in the cluster: the control node numbers its worker nodes."""
    if instance_number < 1:
        raise ValueError(f"An instance number is at least 1: {instance_number}")
    return f"{subsystem_name(subsystem)}-{instance_number}"


def short_job_id(job_id: str) -> str:
    """The start of a job id that names the job's instance, long enough to recognise the job by."""
    return docker_word(job_id)[:JOB_ID_LENGTH].rstrip("-")


def worker_node_project(control_node_id: str, worker_node_id: str) -> str:
    """The compose project of a worker node: its daemon and every container the daemon starts."""
    return f"{SCOPE_ROOT}-{_require_id('control node id', control_node_id)}-{_require_id('worker node id', worker_node_id)}"


def live_session_project_prefix(control_node_id: str) -> str:
    """The compose project names of every live session of one control node start with this."""
    return f"{SCOPE_ROOT}-{_require_id('control node id', control_node_id)}-{LIVE_SESSION_WORKER_NODE_ID}-{LIVE_SESSION_INSTANCE_PREFIX}"


@dataclass(frozen=True)
class InstanceScope:
    control_node_id: str
    worker_node_id: str
    instance_id: str  # the instance's readable name, unique among the worker node's running instances
    key: str = ""  # what the instance's containers are found by (INSTANCE_LABEL); the instance id unless given

    def __post_init__(self) -> None:
        _require_id("control node id", self.control_node_id)
        _require_id("worker node id", self.worker_node_id)
        _require_id("instance id", self.instance_id)
        if not self.key:
            object.__setattr__(self, "key", self.instance_id)
        if len(self.docker_name) > _DOCKER_NAME_MAX:
            raise ValueError(f"Scope name {self.docker_name!r} is longer than {_DOCKER_NAME_MAX} characters")

    @classmethod
    def pooled(cls, control_node_id: str, worker_node_id: str, subsystem: str) -> "InstanceScope":
        """The long-lived service of a subsystem; a worker node runs one of each."""
        return cls(control_node_id, worker_node_id, subsystem_name(subsystem))

    @classmethod
    def per_job(cls, control_node_id: str, worker_node_id: str, subsystem: str, job_id: str, attempt: int = 1) -> "InstanceScope":
        """One attempt of a job: named after its subsystem and the start of the job id, found by the whole job id and attempt."""
        if attempt < 1:
            raise ValueError(f"An attempt is at least 1: {attempt}")
        retry = f"-{attempt}" if attempt > 1 else ""
        return cls(control_node_id, worker_node_id, f"{subsystem_name(subsystem)}-{short_job_id(job_id)}{retry}", key=f"{safe_id(job_id)}-{attempt}")

    @classmethod
    def live_session(cls, control_node_id: str, session_id: str) -> "LiveSessionScope":
        """One live session of the workbench: its simulation stack, and its topics on the control node's broker."""
        return LiveSessionScope(control_node_id, LIVE_SESSION_WORKER_NODE_ID, f"{LIVE_SESSION_INSTANCE_PREFIX}{safe_id(session_id)}")

    @property
    def compose_project(self) -> str:
        return worker_node_project(self.control_node_id, self.worker_node_id)

    @property
    def docker_name(self) -> str:
        """The start of every Docker name of the instance, and the whole name of a single container."""
        return f"{self.compose_project}-{self.instance_id}"

    @property
    def labels(self) -> Dict[str, str]:
        """What marks a container or network as this instance's."""
        return {INSTANCE_LABEL: self.key}

    def service_key(self, service: str) -> str:
        """The compose key of one of the instance's services, unique in the worker node's project."""
        return f"{self.instance_id}-{docker_word(service)}"

    def container_name(self, service: str) -> str:
        """Name of one service's container; a single-service instance uses the bare scope name."""
        return f"{self.docker_name}-{docker_word(service)}"

    def network_name(self, key: str) -> str:
        return f"{self.docker_name}-{docker_word(key)}"

    @property
    def folder(self) -> str:
        """Local folder of the instance's compose file and generated files, on the runtime assets volume."""
        return f"{INSTANCES_FOLDER}/{self.docker_name}"


@dataclass(frozen=True)
class LiveSessionScope(InstanceScope):
    """A live session on the control node: a compose project of its own, and a topic prefix on the control node's broker.

    Other brokers carry unscoped WARA-PS topics, so the prefix is used only there (gateway/socket_session.py).
    """

    @property
    def compose_project(self) -> str:
        return f"{SCOPE_ROOT}-{self.control_node_id}-{self.worker_node_id}-{self.instance_id}"

    @property
    def docker_name(self) -> str:
        return self.compose_project

    @property
    def topic_prefix(self) -> str:
        return f"{SCOPE_ROOT}/{self.control_node_id}/{self.worker_node_id}/{self.instance_id}/"

    def service_key(self, service: str) -> str:
        return service

    def container_name(self, service: str) -> str:
        return f"{self.docker_name}-{safe_id(service)}"

    def network_name(self, key: str) -> str:
        return f"{self.docker_name}-{safe_id(key)}"
