"""The job runtime the daemon hands to run_job: a WorkerNodeContext built from the configuration.

The broker is the control node's cluster broker, plain and anonymous on the VPN, on the control node's
host. This process and the job containers dial the same address. Artifacts travel over the
control node's worker node API, naming the worker node in the worker node id header, through a cache in the state volume.
"""

import logging
import shutil
from pathlib import Path
from typing import List

from scenegems_tool.cluster.worker_node.artifacts.artifact_cache import ArtifactCache
from scenegems_tool.cluster.worker_node.artifacts.artifact_client import ArtifactClient
from scenegems_tool.cluster.worker_node.artifacts.worker_node_artifacts import WorkerNodeArtifacts
from scenegems_tool.cluster.worker_node.daemon.configuration.worker_node_configuration import WorkerNodeConfiguration
from scenegems_tool.cluster.worker_node.instance_scope import INSTANCES_FOLDER, SCOPE_ROOT
from scenegems_tool.cluster.worker_node.launchers.compose_project import ComposeProject
from scenegems_tool.cluster.worker_node.worker_node_context import WorkerNodeContext
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

_logger = logging.getLogger(__name__)


def broker_connection(configuration: WorkerNodeConfiguration) -> MQttConnectionInfo:
    return MQttConnectionInfo(
        user="",
        password="",
        agent_broker=configuration.broker_host,  # containers and this process dial the same cluster broker
        client_broker=configuration.broker_host,
        port=configuration.broker_port,
        tls_connection=False,
        allow_certificates=False,
    )


def build_worker_node_context(configuration: WorkerNodeConfiguration) -> WorkerNodeContext:
    latitude, longitude, radius = configuration.reference_geofence
    return WorkerNodeContext(
        control_node_id=configuration.control_node_id,
        worker_node_id=configuration.worker_node_id,
        mqtt_connection=broker_connection(configuration),
        reference_geofence=Geofence(latitude, longitude, radius),
        slots=dict(configuration.slots),
        components=frozenset(configuration.components),
        broker_network=configuration.docker_network,
        artifacts=worker_node_artifacts(configuration),
    )


def worker_node_artifacts(configuration: WorkerNodeConfiguration) -> WorkerNodeArtifacts:
    client = ArtifactClient(configuration.control_node_url, configuration.worker_node_id)
    cache = ArtifactCache(configuration.artifact_cache_folder, configuration.artifact_cache_max_bytes) if configuration.artifact_cache_max_bytes > 0 else None
    return WorkerNodeArtifacts(client, cache)


def instance_prefix(control_node_id: str, worker_node_id: str) -> str:
    """The start of every compose project name of this worker node's instances (instance_scope.py)."""
    return f"{SCOPE_ROOT}-{control_node_id}-{worker_node_id}-"


def remove_leftover_instances(control_node_id: str, worker_node_id: str, instances_folder: str = INSTANCES_FOLDER) -> List[str]:
    """Remove the instances an earlier daemon process left behind; a new process holds no lease.

    Every instance keeps its compose file in a folder named after its compose project and
    removes it when it stops, so a folder that is still there names a leftover. Only names
    with this worker node's prefix are touched, in case the folder is shared with other worker nodes."""
    root = Path(instances_folder)
    if not root.is_dir():
        return []
    prefix = instance_prefix(control_node_id, worker_node_id)
    leftovers = sorted(folder.name for folder in root.iterdir() if folder.is_dir() and folder.name.startswith(prefix))
    for project in leftovers:
        _logger.info("Removing leftover instance %s", project)
        ComposeProject(project, str(root / project / "docker-compose.yml")).force_remove(networks=True)
        shutil.rmtree(root / project, ignore_errors=True)
    return leftovers
