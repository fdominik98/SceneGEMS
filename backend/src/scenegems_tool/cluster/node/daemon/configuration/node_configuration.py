"""The node daemon's configuration, from its environment and its `.env` file.

Variables (deploy/node/.env.example is the template):

    SCENEGEMS_MASTER_URL          http://<host>[:<port>] of the master's cluster API; the node dials it and keeps
                                  retrying while the master is not up. Master and nodes trust the VPN: no TLS, no pairing.
    SCENEGEMS_MASTER_ID           the master's id; names the node's compose project and is checked against the master's Welcome
    SCENEGEMS_BROKER_PORT         optional, the port of the master's cluster broker on the master's host (1883)
    SCENEGEMS_NODE_NAME           this node's name and node id on the master and in Docker names
    SCENEGEMS_NODE_CAPABILITIES   job types with slots, for example simulation.kinematic:4,scene_generation:1
    SCENEGEMS_NODE_LABELS         optional key=value pairs, for example gpu=true,site=lab
    SCENEGEMS_NODE_MACHINE        optional, the name of the machine the node runs on (the deployment tool writes it); shown in the UI
    SCENEGEMS_NODE_STATE_DIR      folder on the node's volume for the artifact cache
    SCENEGEMS_DOCKER_NETWORK      optional, the Docker network pooled services join
    SCENEGEMS_NODE_REFERENCE_GEOFENCE  optional, latitude,longitude,radius of the pools' local frame
    SCENEGEMS_SOFTWARE_REVISION   optional, the revision the node reports (its release's revision)
    SCENEGEMS_NODE_ARTIFACT_CACHE_DIR        optional, the cache of downloaded artifacts (<state>/artifacts)
    SCENEGEMS_NODE_ARTIFACT_CACHE_MAX_BYTES  optional, the cache's bound in bytes (2 GiB)

Process variables win over the file; an empty process variable counts as unset, since
Compose passes unset optional variables as empty strings. Every problem is reported at
once, so a start fails with one message that lists all of them.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple
from urllib.parse import urlsplit

from scenegems_tool.cluster.node.daemon.configuration.env_file import EnvFileError, read_env_file
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.scope_names import is_scope_name

ENV_FILE_VARIABLE = "SCENEGEMS_ENV_FILE"  # read from the process environment only
DEFAULT_ENV_FILE = ".env"
# The workbench's default reference geofence (frontend referenceGeofence.ts).
DEFAULT_REFERENCE_GEOFENCE = (57.76080082972655, 16.680965995056, 20.0)
DEFAULT_ARTIFACT_CACHE_MAX_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_BROKER_PORT = 1883  # the cluster broker's plain MQTT port (deploy/master/nanomq.conf)
ARTIFACT_CACHE_FOLDER = "artifacts"  # under the state folder
MAX_MACHINE_LENGTH = 256  # the registry column

_LABEL_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_JOB_TYPES = {job_type.value: job_type for job_type in JobType}
# Job types of earlier releases and what replaced them, named in the error
_REPLACED_JOB_TYPES = {"simulation.ardupilot": (JobType.SIMULATION_ARDUPILOT_SIM, JobType.SIMULATION_GAZEBO)}


class ConfigurationError(ValueError):
    def __init__(self, problems: List[str]):
        self.problems = problems
        super().__init__("Invalid node configuration:\n" + "\n".join(f"  - {problem}" for problem in problems))


@dataclass(frozen=True)
class NodeConfiguration:
    master_url: str  # http://host[:port], without a trailing slash
    master_id: str
    node_name: str
    capabilities: Dict[JobType, int]  # job type to slots
    state_dir: Path
    broker_port: int = DEFAULT_BROKER_PORT  # on the master's host
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
    def node_id(self) -> str:
        """The node's id on the master: its name, which the operator keeps unique among the nodes of a master."""
        return self.node_name

    @property
    def broker_host(self) -> str:
        """The master's host: the cluster broker runs next to the master API."""
        return urlsplit(self.master_url).hostname or ""

    @property
    def docker_name(self) -> str:
        """The node's compose project and container name on this machine: one per master and node name."""
        return f"scenegems-node-{self.master_id}-{self.node_name}"

    @classmethod
    def load(cls, environ: Optional[Mapping[str, str]] = None, env_file: Optional[Path] = None) -> "NodeConfiguration":
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
    def from_values(cls, values: Mapping[str, str]) -> "NodeConfiguration":
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

        master_url = required("SCENEGEMS_MASTER_URL")
        master_url = parsed("SCENEGEMS_MASTER_URL", parse_master_url, master_url) if master_url else ""
        master_id = required("SCENEGEMS_MASTER_ID")
        if master_id and not is_scope_name(master_id):
            problems.append(f"SCENEGEMS_MASTER_ID: {master_id!r} is not a master id (1 to 63 lowercase letters, digits and hyphens)")
        node_name = required("SCENEGEMS_NODE_NAME")
        if node_name and not is_scope_name(node_name):
            problems.append(f"SCENEGEMS_NODE_NAME: {node_name!r} must be 1 to 63 lowercase letters, digits and hyphens, since it names Docker objects")
        capabilities_text = required("SCENEGEMS_NODE_CAPABILITIES")
        capabilities = parsed("SCENEGEMS_NODE_CAPABILITIES", parse_capabilities, capabilities_text, {}) if capabilities_text else {}
        labels = parsed("SCENEGEMS_NODE_LABELS", parse_labels, get("SCENEGEMS_NODE_LABELS"), {})
        state_text = required("SCENEGEMS_NODE_STATE_DIR")
        broker_port_text = get("SCENEGEMS_BROKER_PORT")
        broker_port = parsed("SCENEGEMS_BROKER_PORT", parse_port, broker_port_text, DEFAULT_BROKER_PORT) if broker_port_text else DEFAULT_BROKER_PORT
        geofence_text = get("SCENEGEMS_NODE_REFERENCE_GEOFENCE")
        geofence = parsed("SCENEGEMS_NODE_REFERENCE_GEOFENCE", parse_geofence, geofence_text, DEFAULT_REFERENCE_GEOFENCE) if geofence_text else DEFAULT_REFERENCE_GEOFENCE
        machine = parsed("SCENEGEMS_NODE_MACHINE", parse_machine, get("SCENEGEMS_NODE_MACHINE"))
        cache_text = get("SCENEGEMS_NODE_ARTIFACT_CACHE_MAX_BYTES")
        cache_max_bytes = parsed("SCENEGEMS_NODE_ARTIFACT_CACHE_MAX_BYTES", parse_byte_count, cache_text, DEFAULT_ARTIFACT_CACHE_MAX_BYTES) if cache_text else DEFAULT_ARTIFACT_CACHE_MAX_BYTES
        if problems:
            raise ConfigurationError(problems)

        return cls(
            master_url=master_url,
            master_id=master_id,
            node_name=node_name,
            capabilities=capabilities,
            state_dir=Path(state_text),
            broker_port=broker_port,
            labels=labels,
            docker_network=get("SCENEGEMS_DOCKER_NETWORK") or None,
            reference_geofence=geofence,
            software_revision=get("SCENEGEMS_SOFTWARE_REVISION") or None,
            machine=machine or None,
            artifact_cache_dir=Path(get("SCENEGEMS_NODE_ARTIFACT_CACHE_DIR")) if get("SCENEGEMS_NODE_ARTIFACT_CACHE_DIR") else None,
            artifact_cache_max_bytes=cache_max_bytes,
        )


def parse_master_url(text: str) -> str:
    parts = urlsplit(text.strip())
    if parts.scheme != "http":
        raise ValueError(f"{text!r} must start with http://; the node and its master trust the VPN and use no TLS")
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
        replacements = " and ".join(replacement.value for replacement in _REPLACED_JOB_TYPES[name])
        raise ValueError(f"{name} is split into {replacements}; list the ones this node runs")
    job_type = _JOB_TYPES.get(name)
    if job_type is None:
        raise ValueError(f"unknown job type {name!r}; known: {', '.join(sorted(_JOB_TYPES))}")
    return job_type


def parse_capabilities(text: str) -> Dict[JobType, int]:
    capabilities: Dict[JobType, int] = {}
    for item in (part.strip() for part in text.split(",")):
        if not item:
            continue
        name, separator, slots_text = item.rpartition(":")
        name = name.strip()
        if not separator or not name:
            raise ValueError(f"{item!r} must read <job type>:<slots>")
        job_type = _job_type_named(name)
        if job_type in capabilities:
            raise ValueError(f"{name} is listed twice")
        try:
            slots = int(slots_text.strip())
        except ValueError:
            raise ValueError(f"{item!r}: slots must be a whole number") from None
        if slots < 1:
            raise ValueError(f"{item!r}: slots must be at least 1")
        capabilities[job_type] = slots
    if not capabilities:
        raise ValueError("lists no job type")
    return capabilities


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
