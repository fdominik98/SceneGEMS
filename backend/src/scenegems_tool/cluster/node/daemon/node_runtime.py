"""The job runtime the daemon hands to run_job: a NodeContext built from the configuration.

The broker is the master's cluster broker, plain and anonymous on the VPN, on the master's
host. This process and the job containers dial the same address. Artifacts travel over the
master's node API, naming the node in the node id header, through a cache in the state volume.
"""

import logging
import shutil
from pathlib import Path
from typing import List

from scenegems_tool.cluster.node.artifacts.artifact_cache import ArtifactCache
from scenegems_tool.cluster.node.artifacts.artifact_client import ArtifactClient
from scenegems_tool.cluster.node.artifacts.node_artifacts import NodeArtifacts
from scenegems_tool.cluster.node.daemon.configuration.node_configuration import NodeConfiguration
from scenegems_tool.cluster.node.instance_scope import INSTANCES_FOLDER, SCOPE_ROOT
from scenegems_tool.cluster.node.launchers.compose_project import ComposeProject
from scenegems_tool.cluster.node.node_context import NodeContext
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

_logger = logging.getLogger(__name__)


def broker_connection(configuration: NodeConfiguration) -> MQttConnectionInfo:
    return MQttConnectionInfo(
        user="",
        password="",
        agent_broker=configuration.broker_host,  # containers and this process dial the same cluster broker
        client_broker=configuration.broker_host,
        port=configuration.broker_port,
        tls_connection=False,
        allow_certificates=False,
    )


def build_node_context(configuration: NodeConfiguration) -> NodeContext:
    latitude, longitude, radius = configuration.reference_geofence
    return NodeContext(
        master_id=configuration.master_id,
        node_id=configuration.node_id,
        mqtt_connection=broker_connection(configuration),
        reference_geofence=Geofence(latitude, longitude, radius),
        slots=dict(configuration.slots),
        components=frozenset(configuration.components),
        broker_network=configuration.docker_network,
        artifacts=node_artifacts(configuration),
    )


def node_artifacts(configuration: NodeConfiguration) -> NodeArtifacts:
    client = ArtifactClient(configuration.master_url, configuration.node_id)
    cache = ArtifactCache(configuration.artifact_cache_folder, configuration.artifact_cache_max_bytes) if configuration.artifact_cache_max_bytes > 0 else None
    return NodeArtifacts(client, cache)


def instance_prefix(master_id: str, node_id: str) -> str:
    """The start of every compose project name of this node's instances (instance_scope.py)."""
    return f"{SCOPE_ROOT}-{master_id}-{node_id}-"


def remove_leftover_instances(master_id: str, node_id: str, instances_folder: str = INSTANCES_FOLDER) -> List[str]:
    """Remove the instances an earlier daemon process left behind; a new process holds no lease.

    Every instance keeps its compose file in a folder named after its compose project and
    removes it when it stops, so a folder that is still there names a leftover. Only names
    with this node's prefix are touched, in case the folder is shared with other nodes."""
    root = Path(instances_folder)
    if not root.is_dir():
        return []
    prefix = instance_prefix(master_id, node_id)
    leftovers = sorted(folder.name for folder in root.iterdir() if folder.is_dir() and folder.name.startswith(prefix))
    for project in leftovers:
        _logger.info("Removing leftover instance %s", project)
        ComposeProject(project, str(root / project / "docker-compose.yml")).force_remove(networks=True)
        shutil.rmtree(root / project, ignore_errors=True)
    return leftovers
