"""The worker node daemon's configuration, from its environment and its `.env` file.

Variables (deploy/worker_node/.env.example is the template):

    SCENEGEMS_CONTROL_NODE_URL          http://<host>[:<port>] of the control node's cluster API; the worker node dials it and keeps
                                  retrying while the control node is not up. Control node and worker nodes trust the VPN: no TLS, no pairing.
    SCENEGEMS_CONTROL_NODE_ID           the control node's id; names the worker node's compose project and is checked against the control node's Welcome
    SCENEGEMS_BROKER_PORT         optional, the port of the control node's cluster broker on the control node's host (1883)
    SCENEGEMS_WORKER_NODE_NAME           this worker node's name and worker node id on the control node and in Docker names
    SCENEGEMS_WORKER_NODE_SLOTS          job types with slots, for example simulation:4,scene_generation:1
    SCENEGEMS_WORKER_NODE_COMPONENTS     what the worker node runs, comma separated (cluster/fingerprints/components.py), for example
                                  asv_system/replay,control_layer/none,simulation_layer/kinematic,scene_generation
    SCENEGEMS_WORKER_NODE_LABELS         optional key=value pairs, for example gpu=true,site=lab
    SCENEGEMS_WORKER_NODE_MACHINE        optional, the name of the machine the worker node runs on (the deployment tool writes it); shown in the UI
    SCENEGEMS_WORKER_NODE_STATE_DIR      folder on the worker node's volume for the artifact cache
    SCENEGEMS_DOCKER_NETWORK      optional, the Docker network pooled services join
    SCENEGEMS_WORKER_NODE_REFERENCE_GEOFENCE  optional, latitude,longitude,radius of the pools' local frame
    SCENEGEMS_SOFTWARE_REVISION   optional, the revision the worker node reports (its release's revision)
    SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_DIR        optional, the cache of downloaded artifacts (<state>/artifacts)
    SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES  optional, the cache's bound in bytes (2 GiB)

A job type with slots needs a component that serves it (a simulation layer for simulation,
monitoring for monitoring.post_hoc, ...). SCENEGEMS_WORKER_NODE_CAPABILITIES of releases before protocol 6
is refused with a message naming the two variables that replace it.

Process variables win over the file; an empty process variable counts as unset, since
Compose passes unset optional variables as empty strings. Every problem is reported at
once, so a start fails with one message that lists all of them.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from scenegems_tool.cluster.fingerprints.components import COMPONENTS, JOB_TYPE_COMPONENTS, SIMULATION_LAYER_PREFIX, STACK_COMPONENTS, is_component
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.scope_names import is_scope_name
from scenegems_tool.cluster.worker_node.daemon.configuration.env_file import EnvFileError, read_env_file

ENV_FILE_VARIABLE = "SCENEGEMS_ENV_FILE"  # read from the process environment only
DEFAULT_ENV_FILE = ".env"
# The workbench's default reference geofence (frontend referenceGeofence.ts).
DEFAULT_REFERENCE_GEOFENCE = (57.76080082972655, 16.680965995056, 20.0)
DEFAULT_ARTIFACT_CACHE_MAX_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_BROKER_PORT = 1883  # the cluster broker's plain MQTT port (deploy/control_node/nanomq.conf)
ARTIFACT_CACHE_FOLDER = "artifacts"  # under the state folder
MAX_MACHINE_LENGTH = 256  # the registry column

_LABEL_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_JOB_TYPES = {job_type.value: job_type for job_type in JobType}
# Job types of earlier releases and what replaced them, named in the error
_REPLACED_JOB_TYPES = {name: JobType.SIMULATION for name in ("simulation.kinematic", "simulation.ardupilot", "simulation.ardupilot_sim", "simulation.gazebo")}
REPLACED_CAPABILITIES_VARIABLE = "SCENEGEMS_WORKER_NODE_CAPABILITIES"  # before protocol 6


class ConfigurationError(ValueError):
    def __init__(self, problems: List[str]):
        self.problems = problems
        super().__init__("Invalid worker node configuration:\n" + "\n".join(f"  - {problem}" for problem in problems))


@dataclass(frozen=True)
class WorkerNodeConfiguration:
    control_node_url: str  # http://host[:port], without a trailing slash
    control_node_id: str
    worker_node_name: str
    slots: Dict[JobType, int]  # job type to slots
    components: FrozenSet[str]  # what the worker node runs its jobs with
    state_dir: Path
    broker_port: int = DEFAULT_BROKER_PORT  # on the control node's host
    labels: Dict[str, str] = field(default_factory=dict)
    docker_network: Optional[str] = None
    reference_geofence: Tuple[float, float, float] = DEFAULT_REFERENCE_GEOFENCE
    software_revision: Optional[str] = None
    machine: Optional[str] = None  # reported in the Hello
    artifact_cache_dir: Optional[Path] = None  # <state_dir>/artifacts when None
    artifact_cache_max_bytes: int = DEFAULT_ARTIFACT_CACHE_MAX_BYTES

    @property
    def artifact_cache_folder(self) -> Path:
        return self.artifact_cache_dir or Path(self.state_dir) / ARTIFACT_CACHE_FOLDER

    @property
    def worker_node_id(self) -> str:
        """The worker node's id on the control node: its name, which the operator keeps unique among the worker nodes of a control node."""
        return self.worker_node_name

    @property
    def broker_host(self) -> str:
        """The control node's host: the cluster broker runs next to the control node API."""
        return urlsplit(self.control_node_url).hostname or ""

    @property
    def docker_name(self) -> str:
        """The worker node's compose project on this machine, one per control node and worker node name: the daemon and every container it starts."""
        return f"scenegems-{self.control_node_id}-{self.worker_node_name}"

    @classmethod
    def load(cls, environ: Optional[Mapping[str, str]] = None, env_file: Optional[Path] = None) -> "WorkerNodeConfiguration":
        """The configuration from the process environment over the `.env` file (SCENEGEMS_ENV_FILE, or ./.env when present)."""
        environ = os.environ if environ is None else environ
        explicit = env_file is not None or bool(environ.get(ENV_FILE_VARIABLE, "").strip())
        path = Path(env_file) if env_file is not None else Path(environ.get(ENV_FILE_VARIABLE, "").strip() or DEFAULT_ENV_FILE)
        values: Dict[str, str] = {}
        if path.is_file():
            try:
                values.update(read_env_file(path))
            except EnvFileError as error:
                raise ConfigurationError([str(error)]) from error
        elif explicit:
            raise ConfigurationError([f"{ENV_FILE_VARIABLE}: no file at {path}"])
        values.update({key: value for key, value in environ.items() if value.strip()})
        return cls.from_values(values)

    @classmethod
    def from_values(cls, values: Mapping[str, str]) -> "WorkerNodeConfiguration":
        problems: List[str] = []

        def get(name: str) -> str:
            return values.get(name, "").strip()

        def required(name: str) -> str:
            value = get(name)
            if not value:
                problems.append(f"{name} is not set")
            return value

        def parsed(name: str, parse, value: str, default=None):
            try:
                return parse(value)
            except ValueError as error:
                problems.append(f"{name}: {error}")
                return default

        control_node_url = required("SCENEGEMS_CONTROL_NODE_URL")
        control_node_url = parsed("SCENEGEMS_CONTROL_NODE_URL", parse_control_node_url, control_node_url) if control_node_url else ""
        control_node_id = required("SCENEGEMS_CONTROL_NODE_ID")
        if control_node_id and not is_scope_name(control_node_id):
            problems.append(f"SCENEGEMS_CONTROL_NODE_ID: {control_node_id!r} is not a control node id (1 to 63 lowercase letters, digits and hyphens)")
        worker_node_name = required("SCENEGEMS_WORKER_NODE_NAME")
        if worker_node_name and not is_scope_name(worker_node_name):
            problems.append(f"SCENEGEMS_WORKER_NODE_NAME: {worker_node_name!r} must be 1 to 63 lowercase letters, digits and hyphens, since it names Docker objects")
        slots, components = _slots_and_components(get, required, parsed, problems)
        labels = parsed("SCENEGEMS_WORKER_NODE_LABELS", parse_labels, get("SCENEGEMS_WORKER_NODE_LABELS"), {})
        state_text = required("SCENEGEMS_WORKER_NODE_STATE_DIR")
        broker_port_text = get("SCENEGEMS_BROKER_PORT")
        broker_port = parsed("SCENEGEMS_BROKER_PORT", parse_port, broker_port_text, DEFAULT_BROKER_PORT) if broker_port_text else DEFAULT_BROKER_PORT
        geofence_text = get("SCENEGEMS_WORKER_NODE_REFERENCE_GEOFENCE")
        geofence = parsed("SCENEGEMS_WORKER_NODE_REFERENCE_GEOFENCE", parse_geofence, geofence_text, DEFAULT_REFERENCE_GEOFENCE) if geofence_text else DEFAULT_REFERENCE_GEOFENCE
        machine = parsed("SCENEGEMS_WORKER_NODE_MACHINE", parse_machine, get("SCENEGEMS_WORKER_NODE_MACHINE"))
        cache_text = get("SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES")
        cache_max_bytes = parsed("SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES", parse_byte_count, cache_text, DEFAULT_ARTIFACT_CACHE_MAX_BYTES) if cache_text else DEFAULT_ARTIFACT_CACHE_MAX_BYTES
        if problems:
            raise ConfigurationError(problems)

        return cls(
            control_node_url=control_node_url,
            control_node_id=control_node_id,
            worker_node_name=worker_node_name,
            slots=slots,
            components=components,
            state_dir=Path(state_text),
            broker_port=broker_port,
            labels=labels,
            docker_network=get("SCENEGEMS_DOCKER_NETWORK") or None,
            reference_geofence=geofence,
            software_revision=get("SCENEGEMS_SOFTWARE_REVISION") or None,
            machine=machine or None,
            artifact_cache_dir=Path(get("SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_DIR")) if get("SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_DIR") else None,
            artifact_cache_max_bytes=cache_max_bytes,
        )


def _slots_and_components(get, required, parsed, problems: List[str]) -> Tuple[Optional[Dict[JobType, int]], Optional[FrozenSet[str]]]:
    """SCENEGEMS_WORKER_NODE_SLOTS and SCENEGEMS_WORKER_NODE_COMPONENTS, each slotted job type checked against the components; the variable they replace is refused."""
    if get(REPLACED_CAPABILITIES_VARIABLE):
        problems.append(
            f"{REPLACED_CAPABILITIES_VARIABLE} is replaced by SCENEGEMS_WORKER_NODE_SLOTS (job types with slots, for example simulation:2,scene_generation:1) "
            "and SCENEGEMS_WORKER_NODE_COMPONENTS (what the worker node runs them with, for example asv_system/replay,control_layer/none,simulation_layer/kinematic,scene_generation)"
        )
    slots_text = required("SCENEGEMS_WORKER_NODE_SLOTS")
    slots = parsed("SCENEGEMS_WORKER_NODE_SLOTS", parse_slots, slots_text, None) if slots_text else None
    components_text = required("SCENEGEMS_WORKER_NODE_COMPONENTS")
    components = parsed("SCENEGEMS_WORKER_NODE_COMPONENTS", parse_components, components_text, None) if components_text else None
    if slots is not None and components is not None:
        problems.extend(f"SCENEGEMS_WORKER_NODE_SLOTS: {problem}" for problem in slots_without_components(slots, components))
    return slots, components


def parse_control_node_url(text: str) -> str:
    parts = urlsplit(text.strip())
    if parts.scheme != "http":
        raise ValueError(f"{text!r} must start with http://; the worker node and its control node trust the VPN and use no TLS")
    if not parts.hostname:
        raise ValueError(f"{text!r} names no host")
    if parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
        raise ValueError(f"{text!r} must be http://<host>[:<port>] without a path, query or user")
    try:
        port = parts.port
    except ValueError as error:
        raise ValueError(f"{text!r} has an invalid port") from error
    host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"http://{host}" + (f":{port}" if port is not None else "")


def parse_machine(text: str) -> str:
    if len(text) > MAX_MACHINE_LENGTH:
        raise ValueError(f"at most {MAX_MACHINE_LENGTH} characters")
    return text


def parse_port(text: str) -> int:
    try:
        port = int(text.strip())
    except ValueError:
        raise ValueError(f"{text!r} must be a port number") from None
    if not 1 <= port <= 65535:
        raise ValueError(f"{text!r} is not a port (1 to 65535)")
    return port


def _job_type_named(name: str) -> JobType:
    if name in _REPLACED_JOB_TYPES:
        raise ValueError(f"{name} is replaced by {_REPLACED_JOB_TYPES[name].value}; give it slots here and list its layers in SCENEGEMS_WORKER_NODE_COMPONENTS")
    job_type = _JOB_TYPES.get(name)
    if job_type is None:
        raise ValueError(f"unknown job type {name!r}; known: {', '.join(sorted(_JOB_TYPES))}")
    return job_type


def parse_slots(text: str) -> Dict[JobType, int]:
    slots: Dict[JobType, int] = {}
    for item in (part.strip() for part in text.split(",")):
        if not item:
            continue
        name, separator, slots_text = item.rpartition(":")
        name = name.strip()
        if not separator or not name:
            raise ValueError(f"{item!r} must read <job type>:<slots>")
        job_type = _job_type_named(name)
        if job_type in slots:
            raise ValueError(f"{name} is listed twice")
        try:
            count = int(slots_text.strip())
        except ValueError:
            raise ValueError(f"{item!r}: slots must be a whole number") from None
        if count < 1:
            raise ValueError(f"{item!r}: slots must be at least 1")
        slots[job_type] = count
    if not slots:
        raise ValueError("lists no job type")
    return slots


def parse_components(text: str) -> FrozenSet[str]:
    components = set()
    for name in (part.strip() for part in text.split(",")):
        if not name:
            continue
        if not is_component(name):
            raise ValueError(f"unknown component {name!r}; known: {', '.join(COMPONENTS)}")
        if name in components:
            raise ValueError(f"{name} is listed twice")
        components.add(name)
    if not components:
        raise ValueError("lists no component")
    return frozenset(components)


def slots_without_components(slots: Mapping[JobType, int], components: FrozenSet[str]) -> List[str]:
    """The job types with slots that no listed component serves, each as a problem."""
    problems = []
    for job_type in slots:
        if job_type == JobType.SIMULATION:
            if not any(component.startswith(SIMULATION_LAYER_PREFIX) for component in components):
                problems.append(f"{job_type.value} needs a simulation layer among SCENEGEMS_WORKER_NODE_COMPONENTS ({', '.join(c for c in STACK_COMPONENTS if c.startswith(SIMULATION_LAYER_PREFIX))})")
        elif JOB_TYPE_COMPONENTS[job_type] not in components:
            problems.append(f"{job_type.value} needs the component {JOB_TYPE_COMPONENTS[job_type]} among SCENEGEMS_WORKER_NODE_COMPONENTS")
    return problems


def parse_labels(text: str) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    for item in (part.strip() for part in text.split(",")):
        if not item:
            continue
        key, separator, value = item.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not _LABEL_KEY.match(key) or not value:
            raise ValueError(f"{item!r} must read <key>=<value>, the key of letters, digits, '_', '.' and '-'")
        if key in labels:
            raise ValueError(f"label {key!r} is set twice")
        labels[key] = value
    return labels


def parse_byte_count(text: str) -> int:
    try:
        value = int(text.strip())
    except ValueError:
        raise ValueError(f"{text!r} must be a whole number of bytes") from None
    if value < 0:
        raise ValueError(f"{text!r} must not be negative")
    return value


def parse_geofence(text: str) -> Tuple[float, float, float]:
    parts = [part.strip() for part in text.split(",")]
    try:
        latitude, longitude, radius = (float(part) for part in parts)
    except ValueError:
        raise ValueError(f"{text!r} must read <latitude>,<longitude>,<radius in meters>") from None
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0 or radius <= 0.0:
        raise ValueError(f"{text!r} is out of range")
    return latitude, longitude, radius
