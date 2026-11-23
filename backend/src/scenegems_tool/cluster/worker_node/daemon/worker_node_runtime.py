"""The job runtime the daemon hands to run_job: a WorkerNodeContext built from the configuration.

The broker is the cluster broker, plain and anonymous: the broker's service in the cluster (SCENEGEMS_BROKER_HOST)
or the control node's host. This process and the pools dial the same address, and its topics start with scenegems.
The pools go into the worker node's place in the cluster (namespace, node, runtime folder on the node), owned by the
daemon's Deployment. Artifacts travel over the control node's worker node API, naming the worker node in the worker
node id header, through a cache in the state volume.
"""

import logging
import shutil
from pathlib import Path
from typing import List, Optional

from scenegems_tool.cluster.worker_node.artifacts.artifact_cache import ArtifactCache
from scenegems_tool.cluster.worker_node.artifacts.artifact_client import ArtifactClient
from scenegems_tool.cluster.worker_node.artifacts.worker_node_artifacts import WorkerNodeArtifacts
from scenegems_tool.cluster.worker_node.daemon.configuration.worker_node_configuration import WorkerNodeConfiguration
from scenegems_tool.cluster.worker_node.instance_scope import INSTANCE_LABEL, INSTANCES_FOLDER, daemon_deployment_name, is_instance_folder, worker_node_selector_labels
from scenegems_tool.cluster.worker_node.launchers.kubernetes_api import ClusterPlace, Kind, KubernetesApi, label_selector
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.messaging.mqtt_client import CLUSTER_TOPIC_ROOT, MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

_logger = logging.getLogger(__name__)
LEFTOVER_KINDS = (Kind.DEPLOYMENT, Kind.POD, Kind.SERVICE)  # pools are Deployments; a run is a pod with its services


def broker_connection(configuration: WorkerNodeConfiguration) -> MQttConnectionInfo:
    return MQttConnectionInfo(
        user="",
        password="",
        agent_broker=configuration.broker_host,  # the pools and this process dial the same cluster broker
        client_broker=configuration.broker_host,
        port=configuration.broker_port,
        tls_connection=False,
        allow_certificates=False,
        topic_root=CLUSTER_TOPIC_ROOT,
    )


def cluster_place(configuration: WorkerNodeConfiguration, api: KubernetesApi) -> ClusterPlace:
    """The worker node's place in the cluster, owned by its daemon's Deployment, which the chart names worker-node-<name>."""
    owner_name = daemon_deployment_name(configuration.worker_node_id)
    try:
        owner = api.owner_reference(owner_name)
    except LookupError as error:
        raise RuntimeError(f"{error}: the worker node daemon runs as the pod of its Deployment {owner_name}, which owns its pools") from error
    return ClusterPlace(configuration.kubernetes_namespace, configuration.kubernetes_node, configuration.runtime_host_path, owner)


def build_worker_node_context(configuration: WorkerNodeConfiguration, api: Optional[KubernetesApi] = None) -> WorkerNodeContext:
    """The worker node's context; api is the cluster API of the daemon's pod (its service account) unless given."""
    api = api or KubernetesApi.connect(configuration.kubernetes_namespace)
    latitude, longitude, radius = configuration.reference_geofence
    return WorkerNodeContext(
        control_node_id=configuration.control_node_id,
        worker_node_id=configuration.worker_node_id,
        mqtt_connection=broker_connection(configuration),
        reference_geofence=Geofence(latitude, longitude, radius),
        slots=dict(configuration.slots),
        components=frozenset(configuration.components),
        cluster=cluster_place(configuration, api),
        kubernetes=api,
        artifacts=worker_node_artifacts(configuration),
    )


def worker_node_artifacts(configuration: WorkerNodeConfiguration) -> WorkerNodeArtifacts:
    client = ArtifactClient(configuration.control_node_url, configuration.worker_node_id)
    cache = ArtifactCache(configuration.artifact_cache_folder, configuration.artifact_cache_max_bytes) if configuration.artifact_cache_max_bytes > 0 else None
    return WorkerNodeArtifacts(client, cache)


def leftover_selector(worker_node_id: str) -> str:
    """The objects of the worker node's instances: its label, and an instance label of any value. The daemon's own pod carries no instance label."""
    return label_selector(worker_node_selector_labels(worker_node_id), present=[INSTANCE_LABEL])


def remove_leftover_instances(api: KubernetesApi, worker_node_id: str, instances_folder: str = INSTANCES_FOLDER) -> List[str]:
    """Remove the instances an earlier daemon process left behind; a new process holds no lease.

    Every Deployment, pod and service of an instance carries the worker node's label and an instance label, so
    whatever carries both in the namespace is a leftover. A run also keeps its files in a folder named after it
    on the runtime folder and removes it when it ends, so a folder of this worker node's instances that is still
    there is a leftover too. Returns what was removed, as "<kind> <name>"."""
    removed: List[str] = []
    selector = leftover_selector(worker_node_id)
    for kind in LEFTOVER_KINDS:
        for name in api.delete_labelled(kind, selector):
            _logger.info("Removed leftover %s %s", kind.value, name)
            removed.append(f"{kind.value} {name}")
    root = Path(instances_folder)
    if root.is_dir():
        for folder in sorted(entry for entry in root.iterdir() if entry.is_dir() and is_instance_folder(entry.name, worker_node_id)):
            _logger.info("Removing leftover instance folder %s", folder.name)
            shutil.rmtree(folder, ignore_errors=True)
            removed.append(f"folder {folder.name}")
    return removed
