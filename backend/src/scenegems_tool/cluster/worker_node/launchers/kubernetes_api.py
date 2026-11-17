"""The one module that talks to the Kubernetes API: the worker node daemon creates its pools through it, and the simulation subsystem the pods of its runs.

A client works in one namespace, the SceneGEMS cluster's. It connects with the pod's service account when it runs
in a pod and no kubeconfig is named, and with a kubeconfig otherwise (tests, tools): one given by path, or the one
KUBECONFIG names. There is no fallback to a default address: kubectl without a kubeconfig talks to 127.0.0.1:8080,
which can be any other program on the machine.

Manifests are plain dictionaries as the API takes them (camelCase keys); what is read back are the client's models
(snake_case attributes). Deletes ask for background propagation, so a Deployment is gone at once and Kubernetes
removes its replica sets and pods after it.

What is here:
    Deployments   apply (create, or replace the one of that name), read, whether one is available, delete, an owner reference to one
    pods          create, read, delete, an owner reference to one, following a container's log
    services      apply, delete, the node port of a port
    by label      the names of the Deployments, pods or services that carry labels, and deleting them
    reading       the state of a pod's container (container_state, container_states), and whether an error is the API's (api_error)

The simulation subsystem waits for a run's runner by reading the run's pod at an interval of its own, so it needs no
watch. Nothing else in the code base talks to the cluster API.
"""

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional

KUBECONFIG_VARIABLE = "KUBECONFIG"
IN_CLUSTER_VARIABLE = "KUBERNETES_SERVICE_HOST"  # set by the kubelet in every pod
_BACKGROUND = "Background"
_NOT_FOUND = 404
_CONFLICT = 409
_LOG_CHUNK_BYTES = 64 * 1024


class Kind(str, Enum):
    DEPLOYMENT = "Deployment"
    POD = "Pod"
    SERVICE = "Service"


class KubernetesUnavailable(RuntimeError):
    """No way to reach a cluster: not in a pod, and no kubeconfig named."""


@dataclass(frozen=True)
class OwnerReference:
    """An object that owns others: when it is deleted, Kubernetes deletes what it owns."""

    api_version: str
    kind: str
    name: str
    uid: str

    def to_manifest(self) -> Dict[str, Any]:
        # Not the controller, and blocking nothing: setting blockOwnerDeletion would need the right to update the owner's finalizers
        return {"apiVersion": self.api_version, "kind": self.kind, "name": self.name, "uid": self.uid}


@dataclass(frozen=True)
class ClusterPlace:
    """Where a worker node's pools and runs go: its namespace, its Kubernetes node, the node's folder for its runtime files and the object that owns them."""

    namespace: str
    node: str  # the node the worker node's daemon is pinned to; its pools and runs are pinned there too
    runtime_host_path: str  # the worker node's runtime folder on that node (mounted in the simulation subsystem and in a run's pod)
    # What the objects started from here belong to: for the daemon its Deployment (removing the worker node removes its pools),
    # for the simulation subsystem its own pod (a pool that goes takes its runs with it)
    owner: Optional[OwnerReference] = None


@dataclass(frozen=True)
class ContainerState:
    """One container of a pod as the pod's status has it: waiting (with the reason, such as ContainerCreating or ImagePullBackOff), running, or terminated (with the exit code)."""

    WAITING = "waiting"
    RUNNING = "running"
    TERMINATED = "terminated"

    state: str  # WAITING, RUNNING or TERMINATED
    reason: str = ""
    message: str = ""
    exit_code: Optional[int] = None
    restarts: int = 0

    @property
    def started(self) -> bool:
        """It runs or has run, so it has a log."""
        return self.state in (self.RUNNING, self.TERMINATED)


def container_state(pod: Any, container: str) -> Optional[ContainerState]:
    """The state of a container of a pod as read (a regular one, or an init container such as a sidecar); None while the pod's status names none."""
    return container_states(pod).get(container)


def container_states(pod: Any) -> Dict[str, ContainerState]:
    """The state of every container the status of a pod as read names, by container name."""
    status = getattr(pod, "status", None)
    states: Dict[str, ContainerState] = {}
    for entry in [*(getattr(status, "init_container_statuses", None) or []), *(getattr(status, "container_statuses", None) or [])]:
        if entry.state is None:
            continue
        restarts = int(entry.restart_count or 0)
        if entry.state.terminated is not None:
            ended = entry.state.terminated
            states[entry.name] = ContainerState(ContainerState.TERMINATED, ended.reason or "", ended.message or "", int(ended.exit_code), restarts)
        elif entry.state.running is not None:
            states[entry.name] = ContainerState(ContainerState.RUNNING, restarts=restarts)
        else:
            waiting = entry.state.waiting
            states[entry.name] = ContainerState(ContainerState.WAITING, getattr(waiting, "reason", None) or "", getattr(waiting, "message", None) or "", restarts=restarts)
    return states


def api_error(error: BaseException) -> Optional[str]:
    """What the cluster API answered, for an error that is its answer (it has an HTTP status); None for any other error."""
    status = _status(error)
    if status is None:
        return None
    return f"{status} {getattr(error, 'reason', '') or ''}".strip()


def label_selector(equal: Optional[Mapping[str, str]] = None, present: Iterable[str] = ()) -> str:
    """A label selector: every key of equal with its value, and every key of present with any value."""
    parts = [f"{key}={value}" for key, value in sorted((equal or {}).items())]
    parts.extend(sorted(present))
    return ",".join(parts)


def _status(error: BaseException) -> Optional[int]:
    return getattr(error, "status", None)


class KubernetesApi:
    """The cluster API in one namespace. Tests hand in fakes of the client's AppsV1Api and CoreV1Api."""

    def __init__(self, namespace: str, apps: Any, core: Any):
        self.namespace = namespace
        self._apps = apps
        self._core = core

    @classmethod
    def connect(cls, namespace: str, kubeconfig: Optional[str] = None, context: Optional[str] = None, environ: Optional[Mapping[str, str]] = None) -> "KubernetesApi":
        """A client of the pod's service account in a pod, else of the kubeconfig given or named by KUBECONFIG."""
        from kubernetes import client, config

        environ = os.environ if environ is None else environ
        path = kubeconfig or environ.get(KUBECONFIG_VARIABLE, "").strip() or None
        if path is not None:
            api_client = config.new_client_from_config(config_file=path, context=context)
        elif environ.get(IN_CLUSTER_VARIABLE, "").strip():
            configuration = client.Configuration()
            config.load_incluster_config(client_configuration=configuration)
            api_client = client.ApiClient(configuration)
        else:
            raise KubernetesUnavailable(f"Not in a pod, and no kubeconfig given or named by {KUBECONFIG_VARIABLE}: no cluster to talk to")
        return cls.from_api_client(namespace, api_client)

    @classmethod
    def from_api_client(cls, namespace: str, api_client: Any) -> "KubernetesApi":
        from kubernetes import client

        return cls(namespace, client.AppsV1Api(api_client), client.CoreV1Api(api_client))

    # Deployments

    def apply_deployment(self, manifest: Mapping[str, Any]) -> None:
        """Create the Deployment, or replace the one of its name."""
        try:
            self._apps.create_namespaced_deployment(self.namespace, manifest)
        except Exception as error:
            if _status(error) != _CONFLICT:
                raise
            name = manifest["metadata"]["name"]
            current = self._apps.read_namespaced_deployment(name, self.namespace)
            replacement = {**manifest, "metadata": {**manifest["metadata"], "resourceVersion": current.metadata.resource_version}}
            self._apps.replace_namespaced_deployment(name, self.namespace, replacement)

    def read_deployment(self, name: str) -> Optional[Any]:
        """The Deployment, or None when there is none of that name."""
        try:
            return self._apps.read_namespaced_deployment(name, self.namespace)
        except Exception as error:
            if _status(error) == _NOT_FOUND:
                return None
            raise

    def deployment_available(self, name: str) -> bool:
        """Whether the Deployment has an available replica: its pod runs and is ready."""
        deployment = self.read_deployment(name)
        return deployment is not None and bool(deployment.status and deployment.status.available_replicas)

    def delete_deployment(self, name: str) -> bool:
        """Delete the Deployment; its pods go after it. False when there was none."""
        return self._delete(self._apps.delete_namespaced_deployment, name)

    def owner_reference(self, deployment_name: str) -> OwnerReference:
        """A reference to the Deployment, for objects it is to own. LookupError when there is none of that name."""
        deployment = self.read_deployment(deployment_name)
        if deployment is None:
            raise LookupError(f"There is no Deployment {deployment_name} in namespace {self.namespace}")
        return OwnerReference("apps/v1", Kind.DEPLOYMENT.value, deployment_name, deployment.metadata.uid)

    # Pods

    def create_pod(self, manifest: Mapping[str, Any]) -> Any:
        """Create the pod; returns it as created, with its uid."""
        return self._core.create_namespaced_pod(self.namespace, manifest)

    def read_pod(self, name: str) -> Optional[Any]:
        """The pod with its status, or None when there is none of that name."""
        try:
            return self._core.read_namespaced_pod(name, self.namespace)
        except Exception as error:
            if _status(error) == _NOT_FOUND:
                return None
            raise

    def pod_owner_reference(self, pod_name: str) -> OwnerReference:
        """A reference to the pod, for objects it is to own. LookupError when there is none of that name."""
        pod = self.read_pod(pod_name)
        if pod is None:
            raise LookupError(f"There is no pod {pod_name} in namespace {self.namespace}")
        return OwnerReference("v1", Kind.POD.value, pod_name, pod.metadata.uid)

    def follow_log(self, name: str, container: str, *, timestamps: bool = False, since_seconds: Optional[int] = None) -> Iterator[str]:
        """The lines of a container's log, without their line end, followed until the container stops or the connection ends.

        The API gives stdout and stderr as one log. The container has to have started (ContainerState.started): the API
        refuses the log of one that waits. timestamps: each line starts with the time the kubelet took it (RFC 3339 with
        nanoseconds) and a space. since_seconds: only the lines of the last seconds.
        """
        options: Dict[str, Any] = {"container": container, "follow": True, "timestamps": timestamps, "_preload_content": False}
        if since_seconds is not None:
            options["since_seconds"] = int(since_seconds)
        response = self._core.read_namespaced_pod_log(name, self.namespace, **options)
        try:
            pending = b""
            for chunk in response.stream(_LOG_CHUNK_BYTES):
                pending += chunk
                *lines, pending = pending.split(b"\n")
                for line in lines:
                    yield line.decode("utf-8", errors="replace").rstrip("\r")
            if pending:
                yield pending.decode("utf-8", errors="replace").rstrip("\r")
        finally:
            response.release_conn()

    def delete_pod(self, name: str, grace_period_s: Optional[int] = None) -> bool:
        """Delete the pod, giving its containers grace_period_s to stop (the pod's own when None). False when there was none."""
        options = {} if grace_period_s is None else {"grace_period_seconds": grace_period_s}
        return self._delete(self._core.delete_namespaced_pod, name, **options)

    # Services

    def apply_service(self, manifest: Mapping[str, Any]) -> None:
        """Create the service, or replace the one of its name; a replacement keeps the cluster IP, which cannot change."""
        try:
            self._core.create_namespaced_service(self.namespace, manifest)
        except Exception as error:
            if _status(error) != _CONFLICT:
                raise
            name = manifest["metadata"]["name"]
            current = self._core.read_namespaced_service(name, self.namespace)
            spec = {**manifest.get("spec", {}), "clusterIP": current.spec.cluster_ip}
            replacement = {**manifest, "metadata": {**manifest["metadata"], "resourceVersion": current.metadata.resource_version}, "spec": spec}
            self._core.replace_namespaced_service(name, self.namespace, replacement)

    def delete_service(self, name: str) -> bool:
        return self._delete(self._core.delete_namespaced_service, name)

    def node_port(self, service_name: str, port: int) -> Optional[int]:
        """The node port Kubernetes gave the service's port, or None when the service or the port has none."""
        try:
            service = self._core.read_namespaced_service(service_name, self.namespace)
        except Exception as error:
            if _status(error) == _NOT_FOUND:
                return None
            raise
        for entry in service.spec.ports or []:
            if entry.port == port:
                return entry.node_port
        return None

    # By label

    def names(self, kind: Kind, selector: str) -> List[str]:
        """The names of the objects of a kind that match the label selector, sorted."""
        listing = self._list_function(kind)(self.namespace, label_selector=selector)
        return sorted(item.metadata.name for item in listing.items)

    def delete_labelled(self, kind: Kind, selector: str) -> List[str]:
        """Delete every object of a kind that matches the label selector; returns the names of those that were there."""
        deleted = []
        for name in self.names(kind, selector):
            if self._delete(self._delete_function(kind), name):
                deleted.append(name)
        return deleted

    # Internals

    def _list_function(self, kind: Kind):
        return {Kind.DEPLOYMENT: self._apps.list_namespaced_deployment, Kind.POD: self._core.list_namespaced_pod, Kind.SERVICE: self._core.list_namespaced_service}[kind]

    def _delete_function(self, kind: Kind):
        return {Kind.DEPLOYMENT: self._apps.delete_namespaced_deployment, Kind.POD: self._core.delete_namespaced_pod, Kind.SERVICE: self._core.delete_namespaced_service}[kind]

    def _delete(self, delete, name: str, **options) -> bool:
        try:
            delete(name, self.namespace, propagation_policy=_BACKGROUND, **options)
        except Exception as error:
            if _status(error) == _NOT_FOUND:
                return False
            raise
        return True
