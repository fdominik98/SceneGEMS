"""Identity of one subsystem instance on a worker node, and every name derived from it.

The worker nodes of a SceneGEMS cluster share one Kubernetes namespace, which scopes the names of the control
node, so an object's name starts with the worker node's name and goes on with the instance's:

    pooled service          <worker node>-scene-generation-subsystem
    run of a job            <worker node>-simulation-subsystem-<job>, with -<attempt> from the second attempt on

<job> is the first characters of the job id (JOB_ID_LENGTH). Every object of an instance carries two labels: the
instance (INSTANCE_LABEL, whose value is the scope's key: the full job id and attempt for a job, which two jobs
never share even when their short names do) and the worker node (WORKER_NODE_LABEL). The daemon finds what an
earlier process of its own left by the two together.

Names in Kubernetes are at most 63 characters (KUBERNETES_NAME_MAX). The bound is set once, on the worker node's
name: at most WORKER_NODE_NAME_MAX characters (28), so that its daemon's Deployment (worker-node-<name>) and the
Deployment of its pool with the longest subsystem name fit whole. The daemon's configuration refuses a longer
name. A name that is still too long (a run's attempt past 9999, an id that did not pass the daemon's check) is
cut and ends in a hash of the whole name (kubernetes_name), so it stays valid and unique.

The Docker names below (compose_project, docker_name, service_key, container_name, network_name) are those of a
run's compose stack (launchers/per_job/job_stack.py); they go when a run becomes a pod.

The ids are lowercase letters, digits, '-' and '_'. MQTT topics do not come from here: a topic names the subsystem
or vessel that publishes and not the worker node it runs on (messaging/topic_layout.py).
"""

import hashlib
import re
from dataclasses import dataclass
from typing import Dict

from scenegems_tool.cluster.worker_node.subsystem import Subsystem
from utils.file_system_utils import RUNTIME_ASSETS_FOLDER

SCOPE_ROOT = "scenegems"
SUBSYSTEM_SUFFIX = "-subsystem"
JOB_ID_LENGTH = 8  # characters of the job id in a job instance's name
INSTANCE_LABEL = "scenegems.instance"  # on every object of an instance; its value is the scope's key
WORKER_NODE_LABEL = "scenegems.worker-node"  # on every object of an instance; its value is the worker node's id
INSTANCES_FOLDER = f"{RUNTIME_ASSETS_FOLDER}/instances"  # generated files of scoped instances, one folder each, on the worker node's runtime folder
DAEMON_DEPLOYMENT_PREFIX = "worker-node-"  # the chart names a worker node's daemon Deployment worker-node-<name> (release roles: ready.deployments)
KUBERNETES_NAME_MAX = 63  # an object name that is a DNS label, and a label value
_HASH_LENGTH = 8
_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_UNSAFE_ID_CHARACTERS = re.compile(r"[^a-z0-9_-]+")


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
    """A part of a name in one spelling: lowercase with hyphens, so kinematic_sim reads kinematic-sim."""
    return safe_id(value).replace("_", "-")


def _bounded(value: str) -> str:
    """value itself up to 63 characters; a longer one cut, ending in a hash of the whole so two long values stay apart."""
    if len(value) <= KUBERNETES_NAME_MAX:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:_HASH_LENGTH]
    return f"{value[: KUBERNETES_NAME_MAX - _HASH_LENGTH - 1].rstrip('-_')}-{digest}"


def kubernetes_name(value: str) -> str:
    """value as a Kubernetes object name (a DNS label): lowercase, '_' and other characters become '-', at most 63 characters."""
    return _bounded(docker_word(value))


def label_value(value: str) -> str:
    """A scope id or key as a Kubernetes label value: as it is (its characters are valid there), at most 63 characters."""
    return _bounded(value)


def subsystem_name(subsystem: str) -> str:
    """The name a subsystem's instances carry in Kubernetes and on MQTT: scene_generation is scene-generation-subsystem."""
    return f"{docker_word(_require_id('subsystem', subsystem))}{SUBSYSTEM_SUFFIX}"


# The longest worker node name with which the Deployment of every pool fits in a Kubernetes name whole
WORKER_NODE_NAME_MAX = KUBERNETES_NAME_MAX - 1 - max(len(subsystem_name(subsystem.value)) for subsystem in Subsystem)


def daemon_deployment_name(worker_node_id: str) -> str:
    """The Deployment of a worker node's daemon, which owns the worker node's pools."""
    return f"{DAEMON_DEPLOYMENT_PREFIX}{worker_node_id}"


def pooled_service_name(subsystem: str, instance_number: int) -> str:
    """The name of a worker node's pooled service on MQTT, unique in the cluster: the control node numbers its worker nodes."""
    if instance_number < 1:
        raise ValueError(f"An instance number is at least 1: {instance_number}")
    return f"{subsystem_name(subsystem)}-{instance_number}"


def short_job_id(job_id: str) -> str:
    """The start of a job id that names the job's instance, long enough to recognise the job by."""
    return docker_word(job_id)[:JOB_ID_LENGTH].rstrip("-")


def worker_node_selector_labels(worker_node_id: str) -> Dict[str, str]:
    """The label every object of the worker node's instances carries; with INSTANCE_LABEL present it selects them."""
    return {WORKER_NODE_LABEL: label_value(worker_node_id)}


def is_instance_folder(folder_name: str, worker_node_id: str) -> bool:
    """Whether a folder on the runtime folder is one of this worker node's instances: <worker node>-<subsystem name>..."""
    prefix = f"{kubernetes_name(worker_node_id)}-"
    if not folder_name.startswith(prefix):
        return False
    rest = folder_name[len(prefix) :]
    return any(rest == name or rest.startswith(f"{name}-") for name in (subsystem_name(subsystem.value) for subsystem in Subsystem))


def worker_node_project(control_node_id: str, worker_node_id: str) -> str:
    """The compose project of a worker node's run stacks (launchers/per_job/job_stack.py)."""
    return f"{SCOPE_ROOT}-{_require_id('control node id', control_node_id)}-{_require_id('worker node id', worker_node_id)}"


@dataclass(frozen=True)
class InstanceScope:
    control_node_id: str
    worker_node_id: str
    instance_id: str  # the instance's readable name, unique among the worker node's running instances
    key: str = ""  # what the instance's objects are found by (INSTANCE_LABEL); the instance id unless given

    def __post_init__(self) -> None:
        _require_id("control node id", self.control_node_id)
        _require_id("worker node id", self.worker_node_id)
        _require_id("instance id", self.instance_id)
        if not self.key:
            object.__setattr__(self, "key", self.instance_id)

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

    @property
    def name(self) -> str:
        """The instance's object name in the namespace: its Deployment, or its pod."""
        return kubernetes_name(f"{self.worker_node_id}-{self.instance_id}")

    @property
    def labels(self) -> Dict[str, str]:
        """What marks an object as this instance's and as the worker node's."""
        return {INSTANCE_LABEL: label_value(self.key), **worker_node_selector_labels(self.worker_node_id)}

    @property
    def folder(self) -> str:
        """Local folder of the instance's generated files, on the worker node's runtime folder."""
        return f"{INSTANCES_FOLDER}/{self.name}"

    # Docker names of a run's compose stack (launchers/per_job/job_stack.py)

    @property
    def compose_project(self) -> str:
        return worker_node_project(self.control_node_id, self.worker_node_id)

    @property
    def docker_name(self) -> str:
        """The start of every Docker name of the instance, and the whole name of a single container."""
        return f"{self.compose_project}-{self.instance_id}"

    def service_key(self, service: str) -> str:
        """The compose key of one of the instance's services, unique in the worker node's project."""
        return f"{self.instance_id}-{docker_word(service)}"

    def container_name(self, service: str) -> str:
        return f"{self.docker_name}-{docker_word(service)}"

    def network_name(self, key: str) -> str:
        return f"{self.docker_name}-{docker_word(key)}"
