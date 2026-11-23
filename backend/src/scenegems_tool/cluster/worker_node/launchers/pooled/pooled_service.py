"""A pooled service: one long-lived subsystem that serves many requests over MQTT, run by a Deployment of its own.

The subsystem runs its MQTT service with a pool of worker processes, sized by the worker node's slots for the kind
of work (WORKER_COUNT). Its Deployment has one replica, pinned to the worker node's Kubernetes node and owned by
the daemon's Deployment, so Kubernetes starts its pod again when it dies and removes it when the worker node is
removed. The launcher applies the Deployment on a background thread, so the caller never waits on the cluster API,
and callers talk to the service on `service_topic` under its `service_name`, which tells it from the same service of
every other worker node on the broker.

The Deployment carries the instance's labels (instance_scope.py), by which a later daemon process finds it again.
"""

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from scenegems_tool.cluster.worker_node.instance_scope import InstanceScope
from scenegems_tool.cluster.worker_node.launchers.container_environment import subsystem_environment
from scenegems_tool.cluster.worker_node.launchers.kubernetes_api import ClusterPlace, KubernetesApi
from scenegems_tool.cluster.worker_node.subsystem import Subsystem, subsystem_image
from scenegems_tool.messaging.mqtt_client import SERVICE_NAME_VARIABLE, MQttConnectionInfo, service_topic
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

_logger = logging.getLogger(__name__)
SERVICE_CPUS = 1  # the MQTT service process next to the workers
STARTUP_JOIN_TIMEOUT_S = 120.0
NODE_SELECTOR_LABEL = "kubernetes.io/hostname"  # every node carries its own name in it
# Docker's cpus was a limit and reserved nothing; a request as large as the limit would keep a pool off a node that is only full on paper
CPU_REQUEST = "100m"
IMAGE_PULL_POLICY = "IfNotPresent"  # an image named by digest or by a release's tag never changes; a test cluster imports its images


@dataclass(frozen=True)
class PoolNames:
    deployment: str  # the Deployment's name in the namespace
    container: str  # the subsystem's container in the pod: the subsystem's name
    labels: Mapping[str, str]  # the instance and the worker node, on the Deployment and its pods

    @classmethod
    def for_scope(cls, scope: InstanceScope) -> "PoolNames":
        return cls(deployment=scope.name, container=scope.instance_id, labels=dict(scope.labels))


def environment_list(environment: Mapping[str, str]) -> List[Dict[str, str]]:
    """A container's environment as Kubernetes takes it."""
    return [{"name": name, "value": str(value)} for name, value in environment.items()]


class PooledService:
    subsystem: Subsystem
    default_service_name = ""  # the service's MQTT name on its own; a subclass that is addressed by name sets it

    def __init__(
        self,
        names: PoolNames,
        mqtt_connection: MQttConnectionInfo,
        reference_geofence: Geofence,
        *,
        cpus: float,
        cluster: ClusterPlace,
        api: KubernetesApi,
        workers: Optional[int] = None,
        service_name: Optional[str] = None,
    ):
        self.names = names
        # Every client of this instance, inside the pod and outside, uses the same connection, name and topic.
        self.mqtt_connection = mqtt_connection
        self.service_name = service_name or self.default_service_name
        self.service_topic = service_topic(self.mqtt_connection.topic_root, self.service_name) if self.service_name else ""
        self.reference_geofence = reference_geofence
        self.cpus = cpus
        self.workers = workers
        self.cluster = cluster
        self.api = api
        self._shutdown = threading.Event()
        deployment = self.build_deployment()
        self._lifecycle_thread: Optional[threading.Thread] = threading.Thread(target=self._start_deployment, args=(deployment,), name=f"{names.deployment}-start", daemon=True)
        self._lifecycle_thread.start()

    def environment(self) -> Dict[str, str]:
        """The subsystem's environment: broker, reference area, pool size and its name on the broker."""
        return {**subsystem_environment(self.mqtt_connection, self.reference_geofence, self.workers), **self.service_name_environment()}

    def service_name_environment(self) -> Dict[str, str]:
        """The variable that tells the service its name, when the launcher chose one."""
        return {SERVICE_NAME_VARIABLE: self.service_name} if self.service_name else {}

    def pod_spec(self) -> Dict[str, Any]:
        """The pod of the Deployment: the subsystem's container on the worker node's node, with no access to the cluster API."""
        container = {
            "name": self.names.container,
            "image": subsystem_image(self.subsystem),
            "imagePullPolicy": IMAGE_PULL_POLICY,
            "env": environment_list(self.environment()),
            "resources": {"limits": {"cpu": f"{self.cpus:g}"}, "requests": {"cpu": CPU_REQUEST}},
        }
        return {"nodeSelector": {NODE_SELECTOR_LABEL: self.cluster.node}, "automountServiceAccountToken": False, "containers": [container]}

    def build_deployment(self) -> Dict[str, Any]:
        labels = dict(self.names.labels)
        metadata: Dict[str, Any] = {"name": self.names.deployment, "namespace": self.cluster.namespace, "labels": labels}
        if self.cluster.owner is not None:
            metadata["ownerReferences"] = [self.cluster.owner.to_manifest()]
        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": metadata,
            "spec": {
                "replicas": 1,
                "strategy": {"type": "Recreate"},  # never two pods of one pool under one name on the broker
                "selector": {"matchLabels": labels},
                "template": {"metadata": {"labels": labels}, "spec": self.pod_spec()},
            },
        }

    def _start_deployment(self, deployment: Dict[str, Any]) -> None:
        try:
            if self._shutdown.is_set():
                return
            self.api.apply_deployment(deployment)
        except BaseException:
            _logger.exception("%s could not apply its Deployment %s", type(self).__name__, self.names.deployment)

    def is_running(self) -> bool:
        """Whether the pool is there: its Deployment exists, or its start is still under way.

        Kubernetes starts a pod that died again, so only a Deployment that is gone needs the launcher. A pod that is
        not ready yet (an image being pulled, a restart) still counts as there, and so does a cluster API that cannot
        be read just now: starting the pool again would not help either.
        """
        thread = self._lifecycle_thread
        if thread is not None and thread.is_alive():
            return True
        try:
            return self.api.read_deployment(self.names.deployment) is not None
        except Exception as error:
            _logger.warning("Cannot read the Deployment %s: %s", self.names.deployment, error)
            return True

    def is_available(self) -> bool:
        """Whether the pool's pod runs and is ready."""
        return self.api.deployment_available(self.names.deployment)

    def destroy(self) -> None:
        self._shutdown.set()
        if self._lifecycle_thread is not None:
            self._lifecycle_thread.join(timeout=STARTUP_JOIN_TIMEOUT_S)
            self._lifecycle_thread = None
        try:
            self.api.delete_deployment(self.names.deployment)
        except Exception as error:  # a later daemon process removes it as a leftover
            _logger.warning("Cannot delete the Deployment %s: %s", self.names.deployment, error)
