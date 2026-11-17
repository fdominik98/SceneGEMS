"""A run as one pod: the runner and the containers of the run's vessel stack, run to completion and removed.

The simulation subsystem's task builds the pod from the stack's service descriptions, which stay compose shaped
(vessel_stack/simulation_docker_stack.py, also run with compose by the calibration tool). The runner, which executes
the run in the simulation subsystem image and owns its clock, is the pod's one regular container. Every other service
(the simulator, and per vessel its ASV system, controller, SITL, MAVProxy, ArduAgent as the stack has them) is a
sidecar: an init container that restarts always, started in the order the stack lists them, a service after the ones
it depends on. Kubernetes starts the runner once every sidecar has started, and the pod ends when the runner exits
(restartPolicy Never). The pod is pinned to the simulation subsystem's node and owned by the subsystem's own pod, so a
pool that goes takes its runs with it.

Inside the pod the containers share one network namespace. hostAliases name every service of the stack at 127.0.0.1,
so the names and ports the runner, MAVProxy and SITL dial stay as they are: every listener has a port of its own per
vessel (contracts/stack_services.py), and every service name is a valid host name.

The translation of a service takes the keys below and refuses any other, so nothing of a description is dropped
without a rule (UntranslatableStack):

    image, command, entrypoint     the container's image, args and command, with compose's ${VARIABLE:-default} taken
                                   from the subsystem's environment as compose takes it from its own
    environment                    a map, or a list of KEY=VALUE
    volumes                        only the runtime volume (RUNTIME_ASSETS_VOLUME): the worker node's runtime folder
                                   on the node, a host path, read only where the service says :ro
    ports                          the container's ports; the ground control ports of an attended run become NodePort
                                   services, whose node ports go into the status detail (STATUS_GROUND_CONTROL)
    tty, stdin_open                tty and stdin
    depends_on                     the order of the sidecars (only the condition service_started, which is all a
                                   sidecar's start says)
    restart                        none needed: a sidecar restarts always, which is the only way it has
    networks                       the stack's own networks, one in a pod; their aliases become hostAliases too
    hostname                       only the service's own name, which the hostAliases already give
    extra_hosts                    an address becomes a hostAlias; host-gateway (Docker's address of its host) has
                                   no counterpart in a pod and is left out: no image of a stack dials it

The run's files are plain files of the run's folder on the runtime folder (scope.folder): the generated files of the
simulators in gen/, and job/ mounted at JOB_FOLDER in the runner, where the subsystem writes job.json before the
start, writes each new observe.json (to a temporary file it then renames), and reads result.json after the end
(job_container_io.py). The runner's status and frame lines are read from its log through the cluster API, as
forward_runner_line takes them. The API gives stdout and stderr as one log, so every line counts as stdout.

The time rules: the job's timeout leaves out the time the run was observed when the runner paces itself to its
observers; an attended run waits for the operator's Start, and its timeout counts from the Start; a cancel ends the
run. The pod, its services and the run's folder are removed either way.
"""

import json
import logging
import math
import os
import re
import shlex
import shutil
import threading
import time
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Mapping, Optional, Tuple

from urllib3.exceptions import HTTPError

from scenegems_tool.cluster.protocol.messages import STATUS_GROUND_CONTROL, LogStream
from scenegems_tool.cluster.worker_node import instance_scope
from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope, kubernetes_name
from scenegems_tool.cluster.worker_node.job_report import JobFailed, JobReport, JobResultData, StatusDetailReport
from scenegems_tool.cluster.worker_node.launchers.kubernetes_api import ClusterPlace, ContainerState, Kind, KubernetesApi, OwnerReference, api_error, container_states, label_selector
from scenegems_tool.cluster.worker_node.launchers.per_job.job_container_io import (
    JOB_CONTAINER_MAIN,
    JOB_DOCUMENT,
    JOB_FOLDER,
    OBSERVE_DOCUMENT,
    RESULT_DOCUMENT,
    ObservationControl,
    parse_frame_line,
    parse_status,
)
from utils.file_system_utils import RUNTIME_ASSETS_VOLUME

if TYPE_CHECKING:
    from scenegems_tool.cluster.worker_node.job_observation import JobObservation

_logger = logging.getLogger(__name__)

RUNNER_SERVICE = "runner"  # the runner's service in the stack, and its container in the pod
RUN_COMPONENT_LABEL = "app.kubernetes.io/component"  # on a run's pod and services beside the instance's labels: what the simulation subsystem removes as leftovers
RUN_COMPONENT = "simulation-run"
RUNTIME_VOLUME = "runtime"  # the pod's volume of the worker node's runtime folder
JOB_SUBFOLDER = "job"  # the run's job folder in its folder, mounted at JOB_FOLDER in the runner
LOOPBACK = "127.0.0.1"
NODE_LABEL = "kubernetes.io/hostname"
TERMINATION_GRACE_S = 3  # the sidecars' time to stop once the pod is deleted (the pod is deleted when the runner ended)
GROUND_CONTROL_PORT_NAME = "ground-control"

SERVICE_KEYS = frozenset({"image", "command", "entrypoint", "environment", "volumes", "ports", "tty", "stdin_open", "depends_on", "restart", "networks", "hostname", "extra_hosts"})
STACK_KEYS = frozenset({"services", "networks", "volumes"})
_NETWORK_KEYS = frozenset({"driver"})
_SERVICE_NETWORK_KEYS = frozenset({"aliases"})
_VOLUME_KEYS = frozenset({"type", "source", "target", "read_only"})
_PORT_KEYS = frozenset({"target", "published", "protocol", "mode", "host_ip", "name"})
_PROTOCOLS = {"tcp": "TCP", "udp": "UDP", "sctp": "SCTP"}
HOST_GATEWAY = "host-gateway"
# A valid container name and host alias in a pod (RFC 1123 label)
_NAME = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
_NAME_MAX = 63
# Compose's interpolation: $$, ${NAME}, ${NAME:-default}, ${NAME-default}, ${NAME:?error}, ${NAME?error}, $NAME
_VARIABLE = re.compile(r"\$(?:(\$)|\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-?])([^}]*))?\}|([A-Za-z_][A-Za-z0-9_]*))")

_WAIT_POLL_S = 0.5  # how often the run's pod is read while the runner runs
_LOG_DRAIN_TIMEOUT_S = 5.0
_START_MARGIN_S = 60.0  # the runner gives up waiting for its Start itself; the subsystem ends it this much later at the latest
_CONTROL_WAIT_S = 0.5  # how often the request writer looks at its stop event, and its pause after a failed write
_API_OUTAGE_S = 30.0  # how long reading the run's pod may fail before the run is given up
_LEFTOVER_GONE_S = 30.0  # how long a leftover pod of the run's name may take to go
_LOG_RECONNECT_S = 1.0  # the pause before the log is followed again after its connection ended while the runner ran
_LOG_SINCE_MARGIN_S = 5  # follows again from this much before the last line read; the lines already read are skipped by their time
# A container that waits for one of these reasons does not start without a change to the pod: the run fails
_FAILED_WAITING_REASONS = frozenset({"ErrImagePull", "ImagePullBackOff", "ErrImageNeverPull", "InvalidImageName", "CreateContainerConfigError", "CreateContainerError"})
_TIMESTAMP = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(\d{1,9}))?(Z|[+-]\d\d:\d\d) ?")


class UntranslatableStack(JobFailed):
    """A service description the pod cannot hold as it is: the key or the value is named, so nothing is dropped silently."""

    def __init__(self, message: str):
        super().__init__(f"The run's stack cannot become a pod: {message}", retryable=False)


def runner_service(image: str, *, environment: Optional[Dict[str, str]] = None) -> dict:
    """The service that runs the job's in-container part. environment replaces the Python job main's own, for a runner that needs more (a simulation's vessel stack)."""
    return {
        "image": image,
        "command": ["python", "-m", JOB_CONTAINER_MAIN],
        "environment": dict(environment) if environment is not None else {"PYTHONUNBUFFERED": "1"},
    }


# Translation of the stack's services


def interpolate(text: str, environ: Mapping[str, str]) -> str:
    """text with compose's variables replaced from environ, as compose replaces them (an unset variable without a default is empty)."""

    def replace(match: "re.Match[str]") -> str:
        if match.group(1):
            return "$"
        name = match.group(2) or match.group(5)
        operator, argument = match.group(3), match.group(4) or ""
        value = environ.get(name)
        if operator == ":-":
            return value if value else argument
        if operator == "-":
            return argument if value is None else value
        if operator in (":?", "?"):
            if value is None or (operator == ":?" and not value):
                raise UntranslatableStack(f"the variable {name} is required: {argument or 'it is not set'}")
            return value
        return value or ""

    return _VARIABLE.sub(replace, text)


def _interpolated(value: Any, environ: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        return interpolate(value, environ)
    if isinstance(value, dict):
        return {key: _interpolated(item, environ) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_interpolated(item, environ) for item in value]
    return value


def _require_name(kind: str, name: str) -> str:
    if not (len(name) <= _NAME_MAX and _NAME.match(name)):
        raise UntranslatableStack(f"{kind} {name!r} is not a valid name in a pod (lowercase letters, digits and '-', starting and ending with a letter or digit, at most {_NAME_MAX})")
    return name


def _words(service: str, key: str, value: Any) -> List[str]:
    """A command or an entrypoint as a list of words: a string is split as compose splits it."""
    if isinstance(value, str):
        return shlex.split(value)
    if isinstance(value, (list, tuple)):
        return [str(word) for word in value]
    raise UntranslatableStack(f"service {service}: {key} must be a list or a string, not {value!r}")


def _environment_value(service: str, name: str, value: Any) -> str:
    if value is None:
        raise UntranslatableStack(f"service {service}: the variable {name} has no value (compose would take it from its own environment)")
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _environment(service: str, environment: Any) -> List[Dict[str, str]]:
    """A compose environment, a map or a list of KEY=VALUE, as the container's env."""
    if isinstance(environment, dict):
        pairs = [(str(name), _environment_value(service, str(name), value)) for name, value in environment.items()]
    elif isinstance(environment, (list, tuple)):
        pairs = []
        for entry in environment:
            name, equals, value = str(entry).partition("=")
            if not equals:
                raise UntranslatableStack(f"service {service}: the variable {name} has no value (compose would take it from its own environment)")
            pairs.append((name, value))
    else:
        raise UntranslatableStack(f"service {service}: environment must be a map or a list, not {environment!r}")
    return [{"name": name, "value": value} for name, value in pairs]


def _dependencies(service: str, depends_on: Any) -> List[str]:
    if isinstance(depends_on, (list, tuple)):
        return [str(name) for name in depends_on]
    if isinstance(depends_on, dict):
        for name, entry in depends_on.items():
            condition = (entry or {}).get("condition", "service_started") if isinstance(entry, dict) else entry
            if condition != "service_started":
                raise UntranslatableStack(f"service {service}: depends_on {name} with condition {condition!r}; a sidecar's start is all the pod waits for (service_started)")
        return [str(name) for name in depends_on]
    raise UntranslatableStack(f"service {service}: depends_on must be a list or a map, not {depends_on!r}")


def start_order(services: Mapping[str, dict]) -> List[str]:
    """The services in the order the stack lists them, each after the services it depends on."""
    dependencies = {name: _dependencies(name, service["depends_on"]) if service.get("depends_on") else [] for name, service in services.items()}
    order: List[str] = []

    def place(name: str, path: Tuple[str, ...]) -> None:
        if name in order:
            return
        if name in path:
            raise UntranslatableStack(f"the services depend on each other in a circle: {' to '.join((*path, name))}")
        for dependency in dependencies[name]:
            if dependency not in services:
                raise UntranslatableStack(f"service {name} depends on {dependency}, which the stack does not have")
            place(dependency, (*path, name))
        order.append(name)

    for name in services:
        place(name, ())
    return order


def _container_port(service: str, entry: Any) -> Dict[str, Any]:
    """The container's side of a compose port: '12200', '5760:5760', '127.0.0.1:80:8080/udp', 12200, or the long form."""
    if isinstance(entry, dict):
        unknown = set(entry) - _PORT_KEYS
        if unknown:
            raise UntranslatableStack(f"service {service}: a port with {sorted(unknown)}")
        port, protocol = str(entry.get("target", "")), str(entry.get("protocol", "tcp"))
    else:
        text, _, protocol = str(entry).partition("/")
        port, protocol = text.rsplit(":", 1)[-1], protocol or "tcp"
    if not port.isdigit():
        raise UntranslatableStack(f"service {service}: the port {entry!r} is not one port")
    if protocol.lower() not in _PROTOCOLS:
        raise UntranslatableStack(f"service {service}: the port {entry!r} has the protocol {protocol!r}")
    return {"containerPort": int(port), "protocol": _PROTOCOLS[protocol.lower()]}


def _runtime_mount(service: str, entry: Any, stack_volumes: Mapping[str, Any]) -> Dict[str, Any]:
    """A volume of a service as a mount of the runtime volume; refused unless it is the runtime volume."""
    if isinstance(entry, dict):
        unknown = set(entry) - _VOLUME_KEYS
        if unknown or entry.get("type", "volume") != "volume":
            raise UntranslatableStack(f"service {service}: the volume {entry!r}")
        source, target, read_only = str(entry.get("source", "")), str(entry.get("target", "")), bool(entry.get("read_only", False))
    else:
        source, _, rest = str(entry).partition(":")
        target, colon, mode = rest.rpartition(":")
        if not colon or not re.fullmatch(r"[A-Za-z,]+", mode):
            target, mode = rest, "rw"  # no mode; a colon in the target is a drive's
        if mode not in ("ro", "rw"):
            raise UntranslatableStack(f"service {service}: the volume {entry!r} has the mode {mode!r}; a pod mounts read only or read and write")
        read_only = mode == "ro"
    definition = stack_volumes.get(source)
    if source != RUNTIME_ASSETS_VOLUME or not (isinstance(definition, dict) and definition.get("external")):
        raise UntranslatableStack(f"service {service}: the volume {source!r}; a run's pod has the worker node's runtime folder ({RUNTIME_ASSETS_VOLUME}) and nothing else")
    if not target:
        raise UntranslatableStack(f"service {service}: the volume {entry!r} has no target")
    mount: Dict[str, Any] = {"name": RUNTIME_VOLUME, "mountPath": target}
    if read_only:
        mount["readOnly"] = True
    return mount


def _network_aliases(service: str, networks: Any, stack_networks: Mapping[str, Any]) -> List[str]:
    """The aliases a service has on the stack's networks; refused for a network that is not the stack's own."""
    entries = dict(networks) if isinstance(networks, dict) else {str(network): None for network in networks}
    aliases: List[str] = []
    for network, entry in entries.items():
        if network not in stack_networks:
            raise UntranslatableStack(f"service {service}: the network {network!r} is not one of the stack's; a pod reaches anything else by its address")
        unknown = set(entry or {}) - _SERVICE_NETWORK_KEYS
        if unknown:
            raise UntranslatableStack(f"service {service}: the network {network} with {sorted(unknown)}")
        aliases.extend(str(alias) for alias in (entry or {}).get("aliases", []))
    return aliases


def _extra_hosts(service: str, extra_hosts: Any) -> Dict[str, List[str]]:
    """By address, the host names a service adds; Docker's host-gateway is left out (module docstring)."""
    entries = list(extra_hosts.items()) if isinstance(extra_hosts, dict) else [tuple(str(entry).split(":", 1)) if ":" in str(entry) else (str(entry), "") for entry in extra_hosts]
    by_address: Dict[str, List[str]] = {}
    for host, address in entries:
        address = str(address).strip()
        if address == HOST_GATEWAY:
            continue
        if not re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", address):
            raise UntranslatableStack(f"service {service}: extra_hosts {host}:{address}; a pod's host alias needs an IPv4 address")
        by_address.setdefault(address, []).append(str(host))
    return by_address


def _check_stack(compose: Mapping[str, Any]) -> None:
    unknown = set(compose) - STACK_KEYS
    if unknown:
        raise UntranslatableStack(f"the stack has {sorted(unknown)}")
    for network, definition in (compose.get("networks") or {}).items():
        definition = definition or {}
        if definition.get("external") or set(definition) - _NETWORK_KEYS or definition.get("driver", "bridge") != "bridge":
            raise UntranslatableStack(f"the network {network} {definition!r}; a pod has one network of its own")


def _container(name: str, service: Mapping[str, Any], stack_volumes: Mapping[str, Any]) -> Dict[str, Any]:
    """The container of one service, without the place of the run; refused for a key or a value the pod cannot hold."""
    _require_name("the service", name)
    unknown = set(service) - SERVICE_KEYS
    if unknown:
        raise UntranslatableStack(f"service {name} has {', '.join(sorted(unknown))}, which the translation into a pod does not know")
    if not service.get("image"):
        raise UntranslatableStack(f"service {name} has no image")
    if service.get("hostname") not in (None, name):
        raise UntranslatableStack(f"service {name} has the hostname {service['hostname']!r}; in a pod it is reached by its service name only")
    container: Dict[str, Any] = {"name": name, "image": str(service["image"]), "imagePullPolicy": "IfNotPresent"}
    if service.get("entrypoint") is not None:
        container["command"] = _words(name, "entrypoint", service["entrypoint"])
    if service.get("command") is not None:
        container["args"] = _words(name, "command", service["command"])
    translations: Dict[str, Callable[[Any], Any]] = {
        "env": lambda value: _environment(name, value),
        "volumeMounts": lambda value: [_runtime_mount(name, entry, stack_volumes) for entry in value],
        "ports": lambda value: [_container_port(name, entry) for entry in value],
    }
    for key, compose_key in (("env", "environment"), ("volumeMounts", "volumes"), ("ports", "ports")):
        if service.get(compose_key):
            container[key] = translations[key](service[compose_key])
    for key, compose_key in (("tty", "tty"), ("stdin", "stdin_open")):
        if service.get(compose_key):
            container[key] = True
    return container


def _host_names(name: str, service: Mapping[str, Any], stack_networks: Mapping[str, Any]) -> Dict[str, List[str]]:
    """By address, the names a service is reached by in the pod: its own and its aliases at 127.0.0.1, and its extra hosts."""
    names = {LOOPBACK: [name, *(_require_name(f"service {name}'s alias", alias) for alias in _network_aliases(name, service.get("networks") or [], stack_networks))]}
    for address, hosts in _extra_hosts(name, service.get("extra_hosts") or []).items():
        names.setdefault(address, []).extend(hosts)
    return names


def translate_stack(compose: Mapping[str, Any], environ: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """The containers of the run's pod and its host aliases, from the stack's compose document.

    Returns {"sidecars": [...], "runner": {...}, "hostAliases": [...]}: what a pod spec takes, without what depends on
    the place of the run (the node, the runtime folder's path on it, the job folder's mount, the owner). Raises
    UntranslatableStack for anything the pod cannot hold.
    """
    environ = os.environ if environ is None else environ
    _check_stack(compose)
    services: Dict[str, dict] = {str(name): _interpolated(dict(service or {}), environ) for name, service in compose["services"].items()}
    if RUNNER_SERVICE not in services:
        raise UntranslatableStack(f"it needs a {RUNNER_SERVICE!r} service")
    containers: Dict[str, Dict[str, Any]] = {}
    aliases: Dict[str, List[str]] = {LOOPBACK: []}
    for name, service in services.items():
        containers[name] = _container(name, service, compose.get("volumes") or {})
        for address, hosts in _host_names(name, service, compose.get("networks") or {}).items():
            aliases.setdefault(address, []).extend(hosts)
    sidecars = [{**containers[name], "restartPolicy": "Always"} for name in start_order(services) if name != RUNNER_SERVICE]
    host_aliases = [{"ip": address, "hostnames": sorted(set(hosts))} for address, hosts in aliases.items() if hosts]
    return {"sidecars": sidecars, "runner": containers[RUNNER_SERVICE], "hostAliases": host_aliases}


def split_timestamp(line: str) -> Tuple[Optional[int], str]:
    """(nanoseconds since the epoch, the line) of a log line the API gave with its time; (None, line) for a line without one."""
    match = _TIMESTAMP.match(line)
    if match is None:
        return None, line
    zone = "+00:00" if match.group(3) == "Z" else match.group(3)
    seconds = int(datetime.fromisoformat(match.group(1) + zone).timestamp())
    return seconds * 1_000_000_000 + int((match.group(2) or "").ljust(9, "0")), line[match.end() :]


def _is_cluster_error(error: BaseException) -> bool:
    """An error of the cluster API or of the connection to it, not of the code."""
    return api_error(error) is not None or isinstance(error, (HTTPError, OSError))


def _retryable(error: BaseException) -> bool:
    """Whether another attempt can succeed: not when the API refused the request as such (a 4xx other than a conflict or too many requests)."""
    status = getattr(error, "status", None)
    return not (isinstance(status, int) and 400 <= status < 500 and status not in (409, 429))


def _write_file(path: str, text: str) -> bool:
    """Write the file through a temporary file in its folder and a rename, so a reader never sees half of it. False when it failed."""
    folder, name = os.path.split(path)
    temporary = os.path.join(folder, f".{name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as file:
            file.write(text)
        os.replace(temporary, path)
        return True
    except OSError:
        try:
            os.remove(temporary)
        except OSError:
            pass
        return False


class RunPod:
    """One run's pod, built from the stack's services, with the place in the cluster it is created in and the client it is created with."""

    def __init__(
        self,
        scope: InstanceScope,
        services: Dict[str, dict],
        *,
        cluster: Optional[ClusterPlace] = None,
        api: Optional[KubernetesApi] = None,
        networks: Optional[dict] = None,
        volumes: Optional[dict] = None,
        environ: Optional[Mapping[str, str]] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.scope = scope
        self.compose: dict = {"services": {name: dict(service) for name, service in services.items()}}
        if networks:
            self.compose["networks"] = dict(networks)
        if volumes:
            self.compose["volumes"] = dict(volumes)
        self.translation = translate_stack(self.compose, environ)  # refuses here, before anything is created
        self.cluster = cluster
        self.api = api
        self.name = scope.name
        self.labels = {**scope.labels, RUN_COMPONENT_LABEL: RUN_COMPONENT}
        self.log_source = f"{self.name}/{RUNNER_SERVICE}"
        self._clock = clock
        self._sleep = sleep
        self._unreadable_since: Optional[float] = None
        self._states: Dict[str, ContainerState] = {}

    @property
    def job_folder(self) -> str:
        """The run's job folder as the subsystem sees it; the runner has it at JOB_FOLDER."""
        return f"{self.scope.folder}/{JOB_SUBFOLDER}"

    def job_sub_path(self) -> str:
        """The job folder's path in the runtime folder, which is the pod's runtime volume."""
        root = os.path.normpath(os.path.dirname(instance_scope.INSTANCES_FOLDER))  # the runtime folder, which holds the instances folder
        folder = os.path.normpath(self.job_folder)
        relative = os.path.relpath(folder, root).replace("\\", "/")
        if relative.startswith("..") or os.path.isabs(relative):
            raise JobFailed(f"The run's folder {folder} is not on the runtime folder {root}, which is what the pod mounts", retryable=False)
        return relative

    def manifest(self) -> Dict[str, Any]:
        """The run's pod."""
        if self.cluster is None:
            raise JobFailed("This simulation subsystem has no place in the cluster, so it cannot create a run's pod", retryable=False)
        runner = dict(self.translation["runner"])
        runner["volumeMounts"] = [*runner.get("volumeMounts", []), {"name": RUNTIME_VOLUME, "mountPath": JOB_FOLDER, "subPath": self.job_sub_path()}]
        metadata: Dict[str, Any] = {"name": self.name, "namespace": self.cluster.namespace, "labels": dict(self.labels)}
        if self.cluster.owner is not None:
            metadata["ownerReferences"] = [self.cluster.owner.to_manifest()]
        spec: Dict[str, Any] = {
            "restartPolicy": "Never",
            "terminationGracePeriodSeconds": TERMINATION_GRACE_S,
            "nodeSelector": {NODE_LABEL: self.cluster.node},
            "automountServiceAccountToken": False,
            "enableServiceLinks": False,  # no variables of the namespace's services: a run's containers see the environment the stack gives them
            "hostAliases": [dict(alias) for alias in self.translation["hostAliases"]],
            "initContainers": [dict(sidecar) for sidecar in self.translation["sidecars"]],
            "containers": [runner],
            "volumes": [{"name": RUNTIME_VOLUME, "hostPath": {"path": self.cluster.runtime_host_path, "type": "Directory"}}],
        }
        if not spec["initContainers"]:
            del spec["initContainers"]
        return {"apiVersion": "v1", "kind": "Pod", "metadata": metadata, "spec": spec}

    def ground_control_service(self, label: str, service: str, port: int, owner: Optional[OwnerReference]) -> Dict[str, Any]:
        """The NodePort service of one ground control port of the run: Kubernetes gives it a port on the node."""
        if service not in self.compose["services"]:
            raise JobFailed(f"The run publishes a port of {service}, which its stack does not have", retryable=False)
        metadata: Dict[str, Any] = {"name": kubernetes_name(f"gcs-{self.name}-{label}"), "namespace": self.cluster.namespace if self.cluster else "", "labels": dict(self.labels)}
        if owner is not None:
            metadata["ownerReferences"] = [owner.to_manifest()]  # the run's pod: the service goes with it
        return {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": metadata,
            "spec": {"type": "NodePort", "selector": dict(self.scope.labels), "ports": [{"name": GROUND_CONTROL_PORT_NAME, "port": port, "targetPort": port, "protocol": "TCP"}]},
        }

    def run(
        self,
        job_document: dict,
        report: JobReport,
        *,
        timeout_s: float,
        cancel: Optional[threading.Event] = None,
        observation: Optional["JobObservation"] = None,
        paced: bool = True,
        start_timeout_s: Optional[float] = None,
        published_ports: Optional[Mapping[str, Tuple[str, int]]] = None,
    ) -> JobResultData:
        """Create the pod, hand the runner its job, wait for it to end and return its result. The pod, its services and the run's folder are removed either way.

        paced: the runner slows down while observed, so the observed time does not count against timeout_s.
        start_timeout_s: the runner waits for the operator's Start, at most this long; timeout_s counts from the Start.
        published_ports: by a label of the caller (an agent id), the service and the container port that gets a port on the
        node, reported in the status detail (STATUS_GROUND_CONTROL).
        """
        if self.cluster is None or self.api is None:
            raise JobFailed("This simulation subsystem has no place in the cluster, so it cannot create a run's pod", retryable=False)
        stop = threading.Event()
        log: Optional[RunnerLog] = None
        try:
            self._remove_leftover()
            self._write_job_document(job_document)
            report.status("creating the run's pod")
            created = self.api.create_pod(self.manifest())
            if published_ports:
                report = StatusDetailReport(report)
                self._publish(published_ports, created, report)
            report.status("running")
            log = RunnerLog(self.api, self.name, RUNNER_SERVICE, report, observation, source=self.log_source)
            log.start()
            if observation is not None:
                threading.Thread(target=self.copy_observation_requests, args=(observation, stop), name=f"{self.name}_observe", daemon=True).start()
            exit_code = self._wait(timeout_s, cancel, observation if paced else None, start=(observation, start_timeout_s) if observation is not None and start_timeout_s is not None else None)
            log.join(_LOG_DRAIN_TIMEOUT_S)
            outcome = self._read_outcome()
        except JobFailed:
            raise
        except Exception as error:
            if not _is_cluster_error(error):
                raise
            raise JobFailed(f"The cluster API failed for run {self.name}: {api_error(error) or error}", retryable=_retryable(error)) from error
        finally:
            stop.set()
            if log is not None:
                log.stop()
            self.remove()
        if exit_code != 0 or "result" not in outcome:
            reason = outcome.get("error") or f"the runner exited with code {exit_code} and no result"
            raise JobFailed(str(reason), retryable=bool(outcome.get("retryable", False)))
        return outcome["result"]

    # Files

    def _write_job_document(self, job_document: dict) -> None:
        shutil.rmtree(self.job_folder, ignore_errors=True)  # what an earlier start of this run left; the generated files stay
        os.makedirs(self.job_folder, exist_ok=True)
        if not _write_file(f"{self.job_folder}/{JOB_DOCUMENT}", json.dumps(job_document)):
            raise JobFailed(f"Could not write the job document into {self.job_folder}", retryable=True)

    def copy_observation_requests(self, observation: "JobObservation", stop: threading.Event) -> None:
        """Writes each new request of the observation into the job folder until stop is set; the latest request wins."""
        applied = 0  # revision 0 is the request nobody made: nothing is written for a job that is never observed
        while not stop.is_set():
            control = observation.wait_for_change(applied, _CONTROL_WAIT_S)
            if control.revision == applied or stop.is_set():
                continue
            if self._write_control(control):
                applied = control.revision
            else:
                stop.wait(_CONTROL_WAIT_S)

    def _write_control(self, control: ObservationControl) -> bool:
        return _write_file(f"{self.job_folder}/{OBSERVE_DOCUMENT}", control.to_document())

    def _read_outcome(self) -> dict:
        try:
            with open(f"{self.job_folder}/{RESULT_DOCUMENT}", encoding="utf-8") as file:
                outcome = json.load(file)
        except (OSError, ValueError):
            return {}
        return outcome if isinstance(outcome, dict) else {}

    # Ground control ports

    def _publish(self, published_ports: Mapping[str, Tuple[str, int]], created: Any, report: StatusDetailReport) -> None:
        """A NodePort service per ground control port, owned by the run's pod; the node ports go into every status detail from now on."""
        uid = getattr(getattr(created, "metadata", None), "uid", None)
        owner = OwnerReference("v1", Kind.POD.value, self.name, uid) if uid else None
        ports: Dict[str, int] = {}
        for label, (service, port) in published_ports.items():
            manifest = self.ground_control_service(label, service, port, owner)
            self.api.apply_service(manifest)
            node_port = self.api.node_port(manifest["metadata"]["name"], port)
            if node_port is None:
                raise JobFailed(f"Kubernetes gave the ground control port {port} of {service} no port on the node", retryable=True)
            ports[label] = node_port
        report.add_detail({STATUS_GROUND_CONTROL: ports})

    # Waiting

    def _wait(self, timeout_s: float, cancel: Optional[threading.Event], observation: Optional["JobObservation"] = None, start: Optional[Tuple["JobObservation", float]] = None) -> int:
        """The runner's exit code, once it ended; JobFailed for a cancel, a timeout, a Start that does not come, or a pod that cannot run."""
        deadline = self._clock() + timeout_s
        waiting_since = self._clock()
        while True:
            runner = self._runner_state()
            if runner is not None and runner.state == ContainerState.TERMINATED:
                return int(runner.exit_code if runner.exit_code is not None else -1)
            if cancel is not None and cancel.is_set():
                raise JobFailed("cancelled", retryable=False)
            if start is not None:
                start_observation, start_timeout_s = start
                if start_observation.started:
                    start = None
                    deadline = self._clock() + timeout_s  # the job's time counts from the operator's Start
                elif self._clock() > waiting_since + start_timeout_s + _START_MARGIN_S:
                    raise JobFailed(f"nobody started the run within {start_timeout_s:g} s", retryable=False)
                self._sleep(_WAIT_POLL_S)
                continue
            observed_s = observation.observed_seconds() if observation is not None else 0.0
            if self._clock() > deadline + observed_s:
                raise JobFailed(f"timed out after {timeout_s:g} s" + (f" (and {observed_s:.0f} s observed)" if observed_s else "") + self._not_running(), retryable=True)
            self._sleep(_WAIT_POLL_S)

    def _runner_state(self) -> Optional[ContainerState]:
        """The runner's state from the pod as read now; None while the pod's status has none or the API cannot be read for a while."""
        try:
            pod = self.api.read_pod(self.name)
        except Exception as error:
            if not _is_cluster_error(error):
                raise
            now = self._clock()
            if self._unreadable_since is None:
                self._unreadable_since = now
            elif now - self._unreadable_since > _API_OUTAGE_S:
                raise JobFailed(f"The run's pod could not be read for {_API_OUTAGE_S:g} s: {api_error(error) or error}", retryable=True) from error
            return None
        self._unreadable_since = None
        if pod is None:
            raise JobFailed(f"The run's pod {self.name} is gone", retryable=True)
        self._states = container_states(pod)
        for name, state in self._states.items():
            if state.state == ContainerState.WAITING and state.reason in _FAILED_WAITING_REASONS:
                raise JobFailed(f"The container {name} of the run cannot start: {state.reason}" + (f": {state.message}" if state.message else ""), retryable=True)
        runner = self._states.get(RUNNER_SERVICE)
        phase = getattr(pod.status, "phase", None) if pod.status is not None else None
        if phase == "Failed" and (runner is None or runner.state != ContainerState.TERMINATED):
            reason = getattr(pod.status, "reason", None) or getattr(pod.status, "message", None) or "no reason given"
            raise JobFailed(f"The run's pod failed before its runner ended: {reason}", retryable=True)
        return runner

    def _not_running(self) -> str:
        """The containers that did not run at the last look, for a timeout's message."""
        waiting = [f"{name}: {state.reason or state.state}" for name, state in self._states.items() if state.state != ContainerState.RUNNING and name != RUNNER_SERVICE]
        if RUNNER_SERVICE not in self._states or self._states[RUNNER_SERVICE].state == ContainerState.WAITING:
            waiting.append(f"{RUNNER_SERVICE}: not started")
        return f"; not running: {', '.join(waiting)}" if waiting else ""

    # Removing

    def _selector(self) -> str:
        return label_selector(self.scope.labels)

    def _remove_leftover(self) -> None:
        """A pod of this run's name that an earlier start left, and its services; waits until the pod is gone, so the name is free."""
        if self.api.read_pod(self.name) is None:
            return
        self.api.delete_pod(self.name, grace_period_s=0)
        self.api.delete_labelled(Kind.SERVICE, self._selector())
        deadline = self._clock() + _LEFTOVER_GONE_S
        while self.api.read_pod(self.name) is not None:
            if self._clock() > deadline:
                raise JobFailed(f"A pod {self.name} of an earlier start did not go within {_LEFTOVER_GONE_S:g} s", retryable=True)
            self._sleep(_WAIT_POLL_S)

    def remove(self) -> None:
        """Delete the pod, its services and the run's folder; what fails is logged, so it never hides why the run ended."""
        if self.api is not None:
            for what, delete in (("pod", lambda: self.api.delete_pod(self.name)), ("services", lambda: self.api.delete_labelled(Kind.SERVICE, self._selector()))):
                try:
                    delete()
                except Exception as error:  # the daemon's and the subsystem's leftover removal find it later by its labels
                    _logger.warning("Could not delete the %s of run %s: %s", what, self.name, error)
        shutil.rmtree(self.scope.folder, ignore_errors=True)


def forward_runner_line(line: str, stream: LogStream, container: str, report: JobReport, observation: Optional["JobObservation"] = None) -> None:
    """One line of the runner's output: a status line as status, a frame line to the observation (never as a log line), the rest as a log line."""
    line = line.rstrip("\r\n")
    if stream == LogStream.STDOUT:
        status = parse_status(line)
        if status is not None:
            message, progress, detail = status
            if detail is None:
                report.status(message, progress)
            else:
                report.status(message, progress, detail)
            return
        frame = parse_frame_line(line)
        if frame is not None:
            if observation is not None:
                observation.add_frames([(frame, len(line))])
            return
    if line:
        report.log(container, line, stream)


class RunnerLog:
    """Follows the runner's log through the cluster API into the report and the observation (forward_runner_line), on a thread of its own.

    The log can only be followed once the runner has started. When the connection ends while the runner still runs
    (the API server or the kubelet let it go), the log is followed again from a little before the last line read, and
    the lines read already are known by their time and skipped. It stops once it read the log of a runner that ended,
    when the pod is gone, or when stopped.
    """

    def __init__(
        self,
        api: KubernetesApi,
        pod: str,
        container: str,
        report: JobReport,
        observation: Optional["JobObservation"] = None,
        *,
        source: Optional[str] = None,
        wall_clock: Callable[[], float] = time.time,
    ):
        self._api = api
        self._pod = pod
        self._container = container
        self._report = report
        self._observation = observation
        self._source = source or f"{pod}/{container}"
        self._wall_clock = wall_clock
        self._stop = threading.Event()
        self.connections = 0  # how often the log was followed
        self._last_ns: Optional[int] = None  # the time of the last line read
        self.thread = threading.Thread(target=self.follow, name=f"{pod}_log", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def join(self, timeout: Optional[float] = None) -> None:
        self.thread.join(timeout)

    def stop(self) -> None:
        self._stop.set()

    def follow(self) -> None:
        self._last_ns = None
        while not self._stop.is_set():
            state = self._started()
            if state is None:
                return
            ended_cleanly = self._read()
            if ended_cleanly and state.state == ContainerState.TERMINATED:
                return  # the runner had ended before: its whole log was read
            after = self._state()
            if after is None:
                return  # the pod is gone
            if ended_cleanly and after.state == ContainerState.TERMINATED:
                return  # the connection ended because the runner did
            self._stop.wait(_WAIT_POLL_S if ended_cleanly else _LOG_RECONNECT_S)

    def _read(self) -> bool:
        """One connection to the log: its lines that were not read before, forwarded. Whether the connection ended without an error."""
        last_ns = self._last_ns
        since = None if last_ns is None else max(1, math.ceil(self._wall_clock() - last_ns / 1e9) + _LOG_SINCE_MARGIN_S)
        self.connections += 1
        try:
            for line in self._api.follow_log(self._pod, self._container, timestamps=True, since_seconds=since):
                stamp, text = split_timestamp(line)
                if stamp is not None and last_ns is not None and stamp <= last_ns:
                    continue  # read on an earlier connection
                if stamp is not None:
                    self._last_ns = stamp
                forward_runner_line(text, LogStream.STDOUT, self._source, self._report, self._observation)
        except Exception as error:
            _logger.info("The log of %s/%s ended: %s", self._pod, self._container, error)
            return False
        return True

    def _state(self) -> Optional[ContainerState]:
        """The runner's state; None when the pod is gone. Unreadable counts as waiting."""
        try:
            pod = self._api.read_pod(self._pod)
        except Exception as error:
            if not _is_cluster_error(error):
                raise
            return ContainerState(ContainerState.WAITING, "unreadable")
        if pod is None:
            return None
        return container_states(pod).get(self._container) or ContainerState(ContainerState.WAITING)

    def _started(self) -> Optional[ContainerState]:
        """Waits until the runner has started and returns its state; None when the pod is gone or the follower is stopped."""
        while not self._stop.is_set():
            state = self._state()
            if state is None:
                return None
            if state.started:
                return state
            self._stop.wait(_WAIT_POLL_S)
        return None


def run_pod_selector(worker_node_id: str) -> str:
    """The run pods and services of a worker node, whichever run: what the simulation subsystem removes as leftovers."""
    return label_selector({**instance_scope.worker_node_selector_labels(worker_node_id), RUN_COMPONENT_LABEL: RUN_COMPONENT})
