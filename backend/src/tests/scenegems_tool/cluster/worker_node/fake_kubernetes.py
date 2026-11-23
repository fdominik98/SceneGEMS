"""A fake of the cluster API as kubernetes_api.py calls it: the AppsV1Api and CoreV1Api methods it uses, over objects held in memory.

Objects are kept as the manifests that were sent; reads return the client's own models built from them, so code
under test reads them as it reads the real API's answers. Kubernetes' own work is not faked: nothing starts a pod
or fills a Deployment's status unless a test does (FakeCluster.set_available, set_container_state, a hook in
on_create), and deleting a Deployment does not delete its pods. A container's log is what a test scripted
(add_log), streamed in small chunks as the client's preload-free answer is.
"""

import copy
import itertools
import json
from typing import Any, Dict, List, Mapping, Optional, Tuple

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from scenegems_tool.cluster.worker_node.launchers.kubernetes_api import Kind, KubernetesApi

_MODELS = {Kind.DEPLOYMENT: "V1Deployment", Kind.POD: "V1Pod", Kind.SERVICE: "V1Service"}
_LISTS = {Kind.DEPLOYMENT: "V1DeploymentList", Kind.POD: "V1PodList", Kind.SERVICE: "V1ServiceList"}
_DESERIALIZER = client.ApiClient()


class _Response:
    def __init__(self, data: Any):
        self.data = json.dumps(data)


def _model(type_name: str, data: Any) -> Any:
    """The client's model of data, as the client builds it from the API server's answer."""
    return _DESERIALIZER.deserialize(_Response(data), type_name)


def _matches(labels: Mapping[str, str], selector: Optional[str]) -> bool:
    for term in filter(None, (selector or "").split(",")):
        key, equals, value = term.partition("=")
        if equals and labels.get(key) != value:
            return False
        if not equals and key not in labels:
            return False
    return True


class FakeCluster:
    """The objects of every namespace, and a record of the calls (kind, verb, name)."""

    def __init__(self, assign_node_ports: bool = False) -> None:
        self.objects: Dict[Tuple[str, Kind, str], Dict[str, Any]] = {}
        self.calls: List[Tuple[str, str, str]] = []
        self.deletions: List[Dict[str, Any]] = []  # the options of every delete
        self.fail_next: Dict[str, ApiException] = {}  # verb (create, read, delete, log) to the error the next call of it raises
        self.on_create: List[Any] = []  # called with (kind, held manifest) after each create, as the cluster would go on from there
        self.log_responses: Dict[Tuple[str, str], List[Any]] = {}  # (pod, container) to the answers of the next log requests (add_log)
        self.log_calls: List[Dict[str, Any]] = []  # the options of every log request
        self.assign_node_ports = assign_node_ports  # a NodePort service gets its node ports on create, as Kubernetes gives them
        self._node_ports = itertools.count(30500)
        self._uids = itertools.count(1)
        self.apps = _Group(self, {"deployment": Kind.DEPLOYMENT})
        self.core = _Group(self, {"pod": Kind.POD, "service": Kind.SERVICE})

    def api(self, namespace: str = "scenegems") -> KubernetesApi:
        return KubernetesApi(namespace, self.apps, self.core)

    def get(self, kind: Kind, name: str, namespace: str = "scenegems") -> Optional[Dict[str, Any]]:
        return self.objects.get((namespace, kind, name))

    def names(self, kind: Kind, namespace: str = "scenegems") -> List[str]:
        return sorted(name for (space, held_kind, name) in self.objects if space == namespace and held_kind == kind)

    def add(self, kind: Kind, manifest: Mapping[str, Any], namespace: str = "scenegems") -> Dict[str, Any]:
        """Put an object in as if somebody else had created it."""
        held = copy.deepcopy(dict(manifest))
        metadata = held.setdefault("metadata", {})
        metadata.setdefault("namespace", namespace)
        metadata["uid"] = f"uid-{next(self._uids)}"
        metadata["resourceVersion"] = "1"
        self.objects[(namespace, kind, metadata["name"])] = held
        return held

    def set_available(self, name: str, replicas: int = 1, namespace: str = "scenegems") -> None:
        self.objects[(namespace, Kind.DEPLOYMENT, name)]["status"] = {"availableReplicas": replicas, "replicas": replicas}

    def set_node_port(self, name: str, port: int, node_port: int, namespace: str = "scenegems") -> None:
        for entry in self.objects[(namespace, Kind.SERVICE, name)]["spec"]["ports"]:
            if entry["port"] == port:
                entry["nodePort"] = node_port

    # The verbs

    def _raise_if_failing(self, verb: str) -> None:
        error = self.fail_next.pop(verb, None)
        if error is not None:
            raise error

    def create(self, kind: Kind, namespace: str, body: Mapping[str, Any]) -> Any:
        self.calls.append((kind.value, "create", body["metadata"]["name"]))
        self._raise_if_failing("create")
        if (namespace, kind, body["metadata"]["name"]) in self.objects:
            raise ApiException(status=409, reason="AlreadyExists")
        if kind == Kind.SERVICE:
            body = copy.deepcopy(dict(body))
            body.setdefault("spec", {})["clusterIP"] = "10.43.0.10"
            if self.assign_node_ports and body["spec"].get("type") == "NodePort":
                for entry in body["spec"].get("ports", []):
                    entry.setdefault("nodePort", next(self._node_ports))
        held = self.add(kind, body, namespace)
        for hook in list(self.on_create):
            hook(kind, held)
        return _model(_MODELS[kind], held)

    def replace(self, kind: Kind, name: str, namespace: str, body: Mapping[str, Any]) -> Any:
        self.calls.append((kind.value, "replace", name))
        current = self.objects.get((namespace, kind, name))
        if current is None:
            raise ApiException(status=404, reason="NotFound")
        if body["metadata"].get("resourceVersion") != current["metadata"]["resourceVersion"]:
            raise ApiException(status=409, reason="Conflict")
        if kind == Kind.SERVICE and body.get("spec", {}).get("clusterIP") != current["spec"].get("clusterIP"):
            raise ApiException(status=422, reason="Invalid: spec.clusterIP is immutable")
        held = copy.deepcopy(dict(body))
        held["metadata"] = {**held["metadata"], "uid": current["metadata"]["uid"], "resourceVersion": str(int(current["metadata"]["resourceVersion"]) + 1)}
        self.objects[(namespace, kind, name)] = held
        return _model(_MODELS[kind], held)

    def read(self, kind: Kind, name: str, namespace: str) -> Any:
        self.calls.append((kind.value, "read", name))
        self._raise_if_failing("read")
        held = self.objects.get((namespace, kind, name))
        if held is None:
            raise ApiException(status=404, reason="NotFound")
        return _model(_MODELS[kind], held)

    def delete(self, kind: Kind, name: str, namespace: str, **options) -> None:
        self.calls.append((kind.value, "delete", name))
        self.deletions.append({"kind": kind.value, "name": name, **options})
        self._raise_if_failing("delete")
        if self.objects.pop((namespace, kind, name), None) is None:
            raise ApiException(status=404, reason="NotFound")

    def list(self, kind: Kind, namespace: str, label_selector: Optional[str] = None) -> Any:
        self.calls.append((kind.value, "list", label_selector or ""))
        items = [copy.deepcopy(held) for (space, held_kind, _), held in sorted(self.objects.items()) if space == namespace and held_kind == kind]
        matching = [item for item in items if _matches(item["metadata"].get("labels") or {}, label_selector)]
        return _model(_LISTS[kind], {"metadata": {}, "items": matching})

    # A pod's status and log, as the kubelet would give them

    def set_phase(self, pod: str, phase: str, namespace: str = "scenegems", **fields) -> None:
        status = self.objects[(namespace, Kind.POD, pod)].setdefault("status", {})
        status["phase"] = phase
        status.update(fields)

    def set_container_state(self, pod: str, container: str, state: str, namespace: str = "scenegems", restarts: int = 0, **fields) -> None:
        """Put a container of a pod into a state: waiting (reason, message), running, or terminated (exitCode, reason)."""
        held = self.objects[(namespace, Kind.POD, pod)]
        init = container in [entry["name"] for entry in held["spec"].get("initContainers", [])]
        statuses = held.setdefault("status", {}).setdefault("initContainerStatuses" if init else "containerStatuses", [])
        detail = dict(fields)
        if state == "terminated":
            detail.setdefault("exitCode", 0)
        if state == "running":
            detail.setdefault("startedAt", "2026-11-17T10:00:00Z")
        entry = {"name": container, "image": "", "imageID": "", "ready": state == "running", "restartCount": restarts, "state": {state: detail}}
        statuses[:] = [held_entry for held_entry in statuses if held_entry["name"] != container] + [entry]

    def add_log(self, pod: str, container: str, *responses: Any) -> None:
        """What the next calls for the container's log answer, one response per call: a list of lines (sent in chunks of a few
        bytes, so lines cross chunks), or an exception, raised after the lines of the list before it; nothing for a call past the last."""
        self.log_responses.setdefault((pod, container), []).extend(responses)

    def read_log(self, name: str, namespace: str, container: str = "", **options) -> "_LogResponse":
        self.calls.append((Kind.POD.value, "log", name))
        self.log_calls.append({"name": name, "container": container, **options})
        self._raise_if_failing("log")
        if (namespace, Kind.POD, name) not in self.objects:
            raise ApiException(status=404, reason="NotFound")
        responses = self.log_responses.get((name, container), [])
        lines: List[str] = []
        failure: Optional[BaseException] = None
        while responses:
            response = responses.pop(0)
            if isinstance(response, BaseException):
                failure = response
                break
            lines = list(response)
            if responses and isinstance(responses[0], BaseException):
                failure = responses.pop(0)
            break
        return _LogResponse("".join(f"{line}\n" for line in lines).encode("utf-8"), failure)


class _LogResponse:
    """The streamed answer of a log request with _preload_content=False: chunks of bytes, and an error at the end when one was scripted."""

    def __init__(self, data: bytes, failure: Optional[BaseException] = None, chunk: int = 7):
        self._data = data
        self._failure = failure
        self._chunk = chunk
        self.released = False

    def stream(self, amount: int = 0):
        for start in range(0, len(self._data), self._chunk):
            yield self._data[start : start + self._chunk]
        if self._failure is not None:
            raise self._failure

    def release_conn(self) -> None:
        self.released = True


class _Group:
    """The methods of one client API group (AppsV1Api or CoreV1Api) for the kinds it serves, by the client's method names."""

    def __init__(self, cluster: FakeCluster, kinds: Mapping[str, Kind]):
        for word, kind in kinds.items():
            setattr(self, f"create_namespaced_{word}", lambda namespace, body, kind=kind, **_: cluster.create(kind, namespace, body))
            setattr(self, f"replace_namespaced_{word}", lambda name, namespace, body, kind=kind, **_: cluster.replace(kind, name, namespace, body))
            setattr(self, f"read_namespaced_{word}", lambda name, namespace, kind=kind, **_: cluster.read(kind, name, namespace))
            setattr(self, f"delete_namespaced_{word}", lambda name, namespace, kind=kind, **options: cluster.delete(kind, name, namespace, **options))
            setattr(self, f"list_namespaced_{word}", lambda namespace, kind=kind, label_selector=None, **_: cluster.list(kind, namespace, label_selector))
        if Kind.POD in kinds.values():
            self.read_namespaced_pod_log = lambda name, namespace, **options: cluster.read_log(name, namespace, **options)
