"""The roles of a SceneGEMS cluster, written into release.json for the deployment tool.

A cluster is one master and any number of nodes; one machine may hold several roles of
several clusters. Master and nodes trust the VPN: there is no pairing, certificate or
credential, so a node needs nothing from a deployed master and starts, and retries its
connection, before or after the master. For each role the tool installs `stacks/<stack>/` plus release.json into
a folder on the machine, writes its `.env`, runs the setup commands and starts the compose
project. The fields are the contract with the tool:

    description      shown to the operator
    count            "one" (one machine per cluster) or "many"
    stack            folder under stacks/ with the compose file
    project          compose project name
    images           images the role always needs
    env              values the tool writes into .env
    parameters       values the operator may change per machine, with defaults; a parameter
                     with `items` is a list (components, or job types with slots), and
                     `items.images` names the extra images each item needs; an item has an
                     amount after `items.key_separator` when the parameter names one
    secrets          .env keys generated once on the machine (random) and kept afterwards
    requires         another role whose output's KEY=VALUE lines go into this role's .env,
                     kept afterwards like secrets (unused by this release: no role needs one)
    outputs          commands run in the role's folder whose stdout is secret KEY=VALUE lines
    setup            commands run in the role's folder before the project starts (idempotent)
    ready            services that must be running, or healthy, after the start

Text in env, parameters, commands and project may use {cluster} (the cluster id, which is
the master id), {name} (the role's instance name on that machine), {machine.vpn_ip},
{machine.name}, {release.revision}, {master.vpn_ip} and {master.<parameter>} (the VPN
address and a parameter value, default included, of the machine that holds the cluster's
master, deployed or not) and, in outputs, {dependent.name} (the instance name of the role
that requires the output). Cluster ids and instance names follow `name_pattern`,
because they become MQTT topic levels and Docker names.
"""

from typing import Any, Dict, List

from scenegems_tool.cluster.fingerprints.components import check_runner_stacks, component_images
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.scope_names import SCOPE_NAME_PATTERN

BACKEND_IMAGE = "scenegems-backend:latest"
BROKER_IMAGE = "scenegems-mqtt-broker:latest"
POSTGRES_IMAGE = "postgres:16.10-alpine"
NODE_IMAGE = "scenegems-node:latest"

# Where the web UI is served from (cluster/master/settings.py)
DEFAULT_OPERATOR_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
# A kinematic node: replay and USV Navigation on the kinematic layer, scene and trajectory generation, post-hoc monitoring
DEFAULT_NODE_COMPONENTS = "asv_software/replay,asv_software/usv_navigation,control_layer/none,simulation_layer/kinematic,scene_generation,trajectory_generation,monitoring"
DEFAULT_NODE_SLOTS = "simulation:2,scene_generation:1,trajectory_generation:1,monitoring.post_hoc:1"
# The artifact store on the master and the artifact cache on a node (cluster/master/settings.py, node_configuration.py)
DEFAULT_ARTIFACT_MAX_BYTES = str(256 * 1024 * 1024)
DEFAULT_ARTIFACT_SWEEP_INTERVAL_S = "600"
DEFAULT_ARTIFACT_SWEEP_GRACE_S = "3600"
DEFAULT_NODE_ARTIFACT_CACHE_MAX_BYTES = str(2 * 1024 * 1024 * 1024)


def component_item_images() -> Dict[str, List[str]]:
    """The images a node needs for each component it offers (cluster/fingerprints/components.py); fails when a simulation runner names a stack the vessel stack matrix does not offer."""
    check_runner_stacks()
    return {component: list(images) for component, images in component_images().items()}


def slot_item_images() -> Dict[str, List[str]]:
    """The job types a node may give slots, each with no image of its own: the components bring the images."""
    return {job_type.value: [] for job_type in JobType}


def master_role() -> Dict[str, Any]:
    return {
        "description": "Master: node API, scheduler, Postgres and the cluster broker",
        "count": "one",
        "stack": "master",
        "project": "scenegems-{cluster}",
        "images": [BACKEND_IMAGE, BROKER_IMAGE, POSTGRES_IMAGE],
        "env": {
            "COMPOSE_PROJECT_NAME": "scenegems-{cluster}",
            "SCENEGEMS_MASTER_ID": "{cluster}",
            "POSTGRES_DB": "scenegems",
            "POSTGRES_USER": "scenegems",
        },
        "parameters": {
            "SCENEGEMS_API_PORT": {"default": "8443", "description": "HTTP port of the node API"},
            "SCENEGEMS_BROKER_PORT": {"default": "1883", "description": "MQTT port of the cluster broker"},
            "SCENEGEMS_OPERATOR_PORT": {"default": "5174", "description": "operator API and workbench gateway, published on 127.0.0.1 only"},
            "SCENEGEMS_OPERATOR_ALLOWED_ORIGINS": {
                "default": DEFAULT_OPERATOR_ALLOWED_ORIGINS,
                "description": "browser origins the operator API allows (CORS), comma separated: where the web UI is served from",
            },
            "POSTGRES_HOST_PORT": {"default": "5432", "description": "Postgres, published on 127.0.0.1 only"},
            "SCENEGEMS_API_BIND_ADDRESS": {"default": "0.0.0.0", "description": "host address the node API is published on"},
            "SCENEGEMS_BROKER_BIND_ADDRESS": {"default": "0.0.0.0", "description": "host address the cluster broker is published on"},
            "SCENEGEMS_ARTIFACT_MAX_BYTES": {"default": DEFAULT_ARTIFACT_MAX_BYTES, "description": "largest artifact a node may upload, uncompressed, in bytes"},
            "SCENEGEMS_ARTIFACT_SWEEP_INTERVAL_S": {"default": DEFAULT_ARTIFACT_SWEEP_INTERVAL_S, "description": "seconds between sweeps of unreferenced artifacts; 0 turns the sweep off"},
            "SCENEGEMS_ARTIFACT_SWEEP_GRACE_S": {"default": DEFAULT_ARTIFACT_SWEEP_GRACE_S, "description": "seconds an unreferenced artifact is kept after its last use"},
        },
        "secrets": ["POSTGRES_PASSWORD"],
        "setup": [],
        "outputs": {},
        "ready": {"healthy": ["master-api"], "running": ["postgres", "cluster-broker"]},
    }


def node_role() -> Dict[str, Any]:
    return {
        "description": "Node: the node daemon, which leases jobs from its master and runs them in subsystem containers; it needs no deployed master",
        "count": "many",
        "stack": "node",
        "project": "scenegems-node-{cluster}-{name}",
        "images": [NODE_IMAGE],
        "env": {
            "SCENEGEMS_MASTER_ID": "{cluster}",
            "SCENEGEMS_MASTER_URL": "http://{master.vpn_ip}:{master.SCENEGEMS_API_PORT}",
            "SCENEGEMS_BROKER_PORT": "{master.SCENEGEMS_BROKER_PORT}",
            "SCENEGEMS_NODE_NAME": "{name}",
            "SCENEGEMS_NODE_MACHINE": "{machine.name}",
            "SCENEGEMS_SOFTWARE_REVISION": "{release.revision}",
        },
        "parameters": {
            "SCENEGEMS_NODE_COMPONENTS": {
                "default": DEFAULT_NODE_COMPONENTS,
                "description": "what the node runs: vessel stack layers and subsystems separated by commas; their images are installed",
                "items": {"separator": ",", "images": component_item_images()},
            },
            "SCENEGEMS_NODE_SLOTS": {
                "default": DEFAULT_NODE_SLOTS,
                "description": "job types and how many of each run at once, as type:slots separated by commas",
                "items": {"separator": ",", "key_separator": ":", "images": slot_item_images()},
            },
            "SCENEGEMS_NODE_LABELS": {"default": "", "description": "optional labels jobs can require, as key=value separated by commas"},
            "SCENEGEMS_NODE_ARTIFACT_CACHE_MAX_BYTES": {"default": DEFAULT_NODE_ARTIFACT_CACHE_MAX_BYTES, "description": "bound of the node's artifact cache in bytes; 0 turns it off"},
        },
        "secrets": [],
        "setup": [],
        "outputs": {},
        "ready": {"running": ["node"]},
    }


def scenegems_roles() -> Dict[str, Any]:
    return {"master": master_role(), "node": node_role()}


def role_images(roles: Dict[str, Any]) -> List[str]:
    """Every image any role may need, sorted."""
    images = set()
    for role in roles.values():
        images.update(role["images"])
        for parameter in role["parameters"].values():
            for item_images in parameter.get("items", {}).get("images", {}).values():
                images.update(item_images)
    return sorted(images)


NAME_PATTERN = SCOPE_NAME_PATTERN.pattern
