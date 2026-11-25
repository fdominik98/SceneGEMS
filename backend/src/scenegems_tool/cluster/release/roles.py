"""The roles of a SceneGEMS cluster, written into release.json for the deployment tool.

A cluster is one control node and any number of worker nodes. Control node and worker nodes trust their network:
there is no pairing, certificate or credential, so a worker node needs nothing from a deployed control node and
starts, and retries its connection, before or after the control node. A role is the contract with the tool: the tool
installs the release's chart (release.json `chart`: folder, helm_release, namespace and values) into a Kubernetes
cluster with one values file built from the cluster's members. A member is a role on a Kubernetes node, with an
instance name and the operator's parameter values.

    description      shown to the operator
    count            "one" (one member per cluster) or "many"
    images           images the role always needs, named with the release's image tag
    parameters       values the operator may change per member, as text with defaults; a parameter
                     with `items` is a list (components, or job types with slots), and
                     `items.images` names the extra images each item needs; an item has an
                     amount after `items.key_separator` when the parameter names one
    name_pattern     optional: a regular expression its instance names must match, tighter than the
                     release's `name_pattern` (the worker node: at most 28 characters, since the names of
                     its objects in the Kubernetes cluster start with it); the tool checks both
    values           {"path", "entry"}: the chart values a member gives; the entry is a template (below).
                     Count "one": the entry is merged into the object at `path`. Count "many": `path` is a
                     list of the entries of every member, ordered by member name, [] without members
    image_values     image tag of the release to the dotted values path that takes that image, for
                     every image of the role and of its parameters' items
    ready            `deployments` and `stateful_sets`: the names (with placeholders) of the workloads
                     that must be available after the install
    forwards         ports the operator may forward to their PC: name, description, service, port
                     (the service's) and local_port (the one the web console expects)

Building the values file, as the tool does it (tests/scenegems_tool/cluster/release/chart_values_builder.py is
the executable reference):

1. Start from the chart's values, their text rendered with {cluster} and {release.revision}.
2. For each member: its parameter values are its own or the defaults, their text rendered like an entry's.
   The role's entry is rendered: a text gets its placeholders replaced; a number, boolean or null stays; a list
   is rendered item by item; an object with the key "$parameter" becomes the member's value of that parameter,
   converted (below); any other object is rendered key by key. The result goes to `values.path` by the count.
3. The images the cluster needs (each member's role images and the item images its list parameters name) are
   pushed, and each one's `image_values` path is set to the pushed reference
   registry/repository@sha256:<digest>. An image no member needs is not pushed and its value is not written,
   so the chart's default stays.
4. The parts are merged: objects key by key; a path two parts set must get equal values, else the deploy fails.

A "$parameter" object is {"$parameter": key, "type": "text" | "integer" | "number", "split": separator,
"pair": separator}, all but "$parameter" optional (type text). Without "split" the value is converted to the
type: integer is an optional sign and digits, number an integer or a decimal fraction. With "split" the value
is split at that separator into parts, each trimmed and empty ones dropped, and becomes a list of parts of the
type. With "pair" as well, each part is split at the first "pair" into a key and a value, both trimmed, and the
parameter becomes an object of key to value of the type. A part without the pair separator, a key listed twice
or a value not of the type fails the deploy, naming the member and the parameter. A list parameter's "split"
and "pair" are its `items.separator` and `items.key_separator`.

Placeholders in an entry, in a parameter value and in `ready` names: {cluster} (the cluster id, which is the
control node id), {name} (the member's instance name), {node} (its Kubernetes node), {machine.name} (the
machine of that node as the operator knows it) and {release.revision}. Values paths are dot-separated keys, and
no key of the chart's values holds a dot. No secret is a value: the chart generates the Postgres password in the
cluster and keeps it over upgrades, so nothing secret passes through the tool or the release.

Cluster ids and instance names follow `name_pattern`, because they become MQTT topic levels and Kubernetes names,
and an instance name also its role's `name_pattern` when it has one.

Every image SceneGEMS builds is named with the release's image tag (release_image_tag): the
revision, with -dirty when built from uncommitted changes. The chart gets it as its value imageTag and gives it to
every daemon as SCENEGEMS_IMAGE_TAG, which the worker node names its pools' and runs' images with when the values
name no image (utils/image_names.py). Without a release the tag is latest, the tag ./build.sh builds.
"""

import re
from typing import Any, Dict, List, Optional

from scenegems_tool.cluster.fingerprints.components import SIMULATION_IMAGE, SUBSYSTEM_IMAGES, check_runner_stacks, component_images
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.release.manifest import ReleaseChart
from scenegems_tool.cluster.scope_names import SCOPE_NAME_PATTERN, WORKER_NODE_NAME_PATTERN
from scenegems_tool.cluster.worker_node.subsystem import IMAGE_ENVIRONMENT_VARIABLES, Subsystem
from utils.image_names import DEFAULT_IMAGE_TAG, image_repository, tagged, with_tag

CONTROL_NODE_API_REPOSITORY = "scenegems-control-node-api"
BROKER_REPOSITORY = "scenegems-mqtt-broker"
WORKER_NODE_REPOSITORY = "scenegems-worker-node"
BROKER_IMAGE = tagged(BROKER_REPOSITORY, DEFAULT_IMAGE_TAG)
WORKER_NODE_IMAGE = tagged(WORKER_NODE_REPOSITORY, DEFAULT_IMAGE_TAG)
POSTGRES_IMAGE = "postgres:16.10-alpine"
# Images the release pulls instead of building; they keep their own tag
PULLED_IMAGES = (POSTGRES_IMAGE,)

# Where the web UI is served from (cluster/control_node/settings.py)
DEFAULT_OPERATOR_ALLOWED_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
# A kinematic worker node: replay and USV Navigation on the kinematic layer, design space exploration, scene and trajectory generation, post-hoc monitoring
DEFAULT_WORKER_NODE_COMPONENTS = (
    "asv_system/replay,asv_system/usv_navigation,control_layer/none,simulation_layer/kinematic,design_space_exploration,scene_generation,trajectory_generation,monitoring,calibration"
)
DEFAULT_WORKER_NODE_SLOTS = "simulation:2,design_space_exploration:1,scene_generation:1,trajectory_generation:1,monitoring.post_hoc:1,calibration.deviation:1"
# The artifact store on the control node and the artifact cache on a worker node (cluster/control_node/settings.py, worker_node_configuration.py)
DEFAULT_ARTIFACT_MAX_BYTES = str(256 * 1024 * 1024)
DEFAULT_ARTIFACT_SWEEP_INTERVAL_S = "600"
DEFAULT_ARTIFACT_SWEEP_GRACE_S = "3600"
DEFAULT_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES = str(2 * 1024 * 1024 * 1024)

# The chart (deploy/kubernetes/chart, the folder `chart` of a bundle). The placeholders of the values a member gives
# and of the chart's own values; deploy/kubernetes/chart/values.yaml holds every value a role names, with its default.
VALUES_PLACEHOLDERS = ("cluster", "name", "node", "machine.name", "release.revision")
CHART_VALUES_PLACEHOLDERS = ("cluster", "release.revision")
PARAMETER_KEY = "$parameter"  # an object of a values entry that stands for the member's value of a parameter
VALUE_TYPES = ("text", "integer", "number")
CONTROL_NODE_VALUES_PATH = "controlNode"
WORKER_NODES_VALUES_PATH = "workerNodes"
WORKER_NODE_IMAGES_VALUES_PATH = "workerNodeImages"  # every image a worker node can run, by its environment variable
# The workloads and the service the chart names (its templates follow these names): the control node's, a worker node's daemon
CONTROL_NODE_API_SERVICE = "control-node-api"
CONTROL_NODE_DEPLOYMENTS = ("control-node-api", "cluster-broker")
CONTROL_NODE_STATEFUL_SETS = ("postgres",)
WORKER_NODE_DEPLOYMENT = "worker-node-{name}"
# The operator API and workbench gateway (cluster/control_node/settings.py); the web console reaches it on this port
OPERATOR_API_PORT = 5174
# A compose image reference ${VARIABLE:-repository:tag} (vessel_stack/contracts/adapter_spec.py image_reference)
_IMAGE_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*):-([^}]+)\}")


def release_image_tag(revision: str, dirty: bool) -> str:
    """The tag of a release's images: the revision, with -dirty when the checkout had uncommitted changes."""
    return f"{revision}-dirty" if dirty else revision


def release_image(image: str, image_tag: str) -> str:
    """The name of an image in a release of that tag; a pulled image keeps its own."""
    return image if image in PULLED_IMAGES else with_tag(image, image_tag)


def component_item_images(image_tag: str = DEFAULT_IMAGE_TAG) -> Dict[str, List[str]]:
    """The images a worker node needs for each component it offers (cluster/fingerprints/components.py); fails when a simulation runner names a stack the vessel stack matrix does not offer."""
    check_runner_stacks()
    return {component: [release_image(image, image_tag) for image in images] for component, images in component_images().items()}


def slot_item_images() -> Dict[str, List[str]]:
    """The job types a worker node may give slots, each with no image of its own: the components bring the images."""
    return {job_type.value: [] for job_type in JobType}


def worker_node_image_variables() -> Dict[str, str]:
    """Repository to environment variable, for every image a worker node can run: the variables the code reads each image from.

    The subsystem pools' images come from cluster/worker_node/subsystem.py, the images of a run's containers from the
    image references of the vessel stack's ContainerSpecs. Fails when a component's image has no variable or a
    repository has two.
    """
    from scenegems_tool.vessel_stack.registry.catalog import default_registry

    subsystems = {subsystem.value for subsystem in Subsystem}
    pairs = [(image_repository(SIMULATION_IMAGE), IMAGE_ENVIRONMENT_VARIABLES[Subsystem.SIMULATION])]
    pairs += [(image_repository(images[0]), IMAGE_ENVIRONMENT_VARIABLES[Subsystem(component)]) for component, images in SUBSYSTEM_IMAGES.items() if component in subsystems]
    registry = default_registry()
    containers = [container for layer in registry.layers for container in layer.containers] + [container for adapter in registry.adapters for container in adapter.containers]
    for container in containers:
        match = _IMAGE_REFERENCE.fullmatch(container.image)
        if match:
            pairs.append((image_repository(match.group(2)), match.group(1)))
    variables: Dict[str, str] = {}
    for repository, variable in pairs:
        if variables.setdefault(repository, variable) != variable:
            raise ValueError(f"image {repository} is named by both {variables[repository]} and {variable}")
    missing = sorted({image_repository(image) for images in component_images().values() for image in images} - set(variables))
    if missing:
        raise ValueError(f"no environment variable names these images of worker node components: {', '.join(missing)}")
    return dict(sorted(variables.items(), key=lambda pair: pair[1]))


def parameter_value(key: str, value_type: str = "text", split: Optional[str] = None, pair: Optional[str] = None) -> Dict[str, Any]:
    """A values entry's stand-in for the member's value of a parameter, converted as the module docstring says."""
    value: Dict[str, Any] = {PARAMETER_KEY: key}
    if value_type != "text":
        value["type"] = value_type
    if split is not None:
        value["split"] = split
    if pair is not None:
        value["pair"] = pair
    return value


def list_parameter_value(parameters: Dict[str, Any], key: str, value_type: str = "text") -> Dict[str, Any]:
    """The stand-in for a list parameter: split at its items' separator, and paired at their key separator when it has one."""
    items = parameters[key]["items"]
    return parameter_value(key, value_type, split=items["separator"], pair=items.get("key_separator"))


def chart_values(image_tag: str = DEFAULT_IMAGE_TAG) -> Dict[str, Any]:
    """The chart values every cluster of a release gets: its control node id, the revision and the images' tag."""
    return {"controlNodeId": "{cluster}", "revision": "{release.revision}", "imageTag": image_tag}


def scenegems_chart(image_tag: Optional[str] = None) -> ReleaseChart:
    """The chart of a release whose images carry image_tag (release_image_tag), by default latest."""
    return ReleaseChart(values=chart_values(image_tag or DEFAULT_IMAGE_TAG))


def control_node_role(image_tag: str = DEFAULT_IMAGE_TAG) -> Dict[str, Any]:
    return {
        "description": "Control node: worker node API, scheduler, Postgres and the cluster broker",
        "count": "one",
        "images": [tagged(CONTROL_NODE_API_REPOSITORY, image_tag), tagged(BROKER_REPOSITORY, image_tag), POSTGRES_IMAGE],
        "parameters": {
            "SCENEGEMS_OPERATOR_ALLOWED_ORIGINS": {
                "default": DEFAULT_OPERATOR_ALLOWED_ORIGINS,
                "description": "browser origins the operator API allows (CORS), comma separated: where the web UI is served from",
            },
            "SCENEGEMS_ARTIFACT_MAX_BYTES": {"default": DEFAULT_ARTIFACT_MAX_BYTES, "description": "largest artifact a worker node may upload, uncompressed, in bytes"},
            "SCENEGEMS_ARTIFACT_SWEEP_INTERVAL_S": {"default": DEFAULT_ARTIFACT_SWEEP_INTERVAL_S, "description": "seconds between sweeps of unreferenced artifacts; 0 turns the sweep off"},
            "SCENEGEMS_ARTIFACT_SWEEP_GRACE_S": {"default": DEFAULT_ARTIFACT_SWEEP_GRACE_S, "description": "seconds an unreferenced artifact is kept after its last use"},
        },
        "ready": {
            "deployments": list(CONTROL_NODE_DEPLOYMENTS),
            "stateful_sets": list(CONTROL_NODE_STATEFUL_SETS),
        },
        "values": {
            "path": CONTROL_NODE_VALUES_PATH,
            "entry": {
                "enabled": True,
                "node": "{node}",
                "operatorAllowedOrigins": parameter_value("SCENEGEMS_OPERATOR_ALLOWED_ORIGINS"),
                "artifactMaxBytes": parameter_value("SCENEGEMS_ARTIFACT_MAX_BYTES", "integer"),
                "artifactSweepIntervalS": parameter_value("SCENEGEMS_ARTIFACT_SWEEP_INTERVAL_S", "number"),
                "artifactSweepGraceS": parameter_value("SCENEGEMS_ARTIFACT_SWEEP_GRACE_S", "number"),
            },
        },
        "image_values": {
            tagged(CONTROL_NODE_API_REPOSITORY, image_tag): "images.controlNodeApi",
            tagged(BROKER_REPOSITORY, image_tag): "images.broker",
            POSTGRES_IMAGE: "images.postgres",
        },
        "forwards": [
            {
                "name": "operator-api",
                "description": "operator API and workbench gateway, which the web console reaches on this PC",
                "service": CONTROL_NODE_API_SERVICE,
                "port": OPERATOR_API_PORT,
                "local_port": OPERATOR_API_PORT,
            }
        ],
    }


def worker_node_image_values(image_tag: str = DEFAULT_IMAGE_TAG) -> Dict[str, str]:
    """The values path of every image of the worker node's components, named as in a release of that tag."""
    variables = worker_node_image_variables()
    images = {image for images in component_item_images(image_tag).values() for image in images}
    return {image: f"{WORKER_NODE_IMAGES_VALUES_PATH}.{variables[image_repository(image)]}" for image in sorted(images)}


def worker_node_role(image_tag: str = DEFAULT_IMAGE_TAG) -> Dict[str, Any]:
    role: Dict[str, Any] = {
        "description": "Worker node: the worker node daemon, which leases jobs from its control node and runs them in subsystem pools on its Kubernetes node; it needs no deployed control node",
        "count": "many",
        "name_pattern": WORKER_NODE_NAME_PATTERN.pattern,  # the daemon and the control node refuse a longer name
        "images": [tagged(WORKER_NODE_REPOSITORY, image_tag)],
        "parameters": {
            "SCENEGEMS_WORKER_NODE_COMPONENTS": {
                "default": DEFAULT_WORKER_NODE_COMPONENTS,
                "description": "what the worker node runs: vessel stack layers and subsystems separated by commas; their images are installed",
                "items": {"separator": ",", "images": component_item_images(image_tag)},
            },
            "SCENEGEMS_WORKER_NODE_SLOTS": {
                "default": DEFAULT_WORKER_NODE_SLOTS,
                "description": "job types and how many of each run at once, as type:slots separated by commas",
                "items": {"separator": ",", "key_separator": ":", "images": slot_item_images()},
            },
            "SCENEGEMS_WORKER_NODE_LABELS": {"default": "", "description": "optional labels jobs can require, as key=value separated by commas"},
            "SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES": {
                "default": DEFAULT_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES,
                "description": "bound of the worker node's artifact cache in bytes; 0 turns it off",
            },
        },
        "ready": {"deployments": [WORKER_NODE_DEPLOYMENT]},
        "image_values": {tagged(WORKER_NODE_REPOSITORY, image_tag): "images.workerNode", **worker_node_image_values(image_tag)},
        "forwards": [],
    }
    parameters = role["parameters"]
    role["values"] = {
        "path": WORKER_NODES_VALUES_PATH,
        "entry": {
            "name": "{name}",
            "node": "{node}",
            "machine": "{machine.name}",
            "components": list_parameter_value(parameters, "SCENEGEMS_WORKER_NODE_COMPONENTS"),
            "slots": list_parameter_value(parameters, "SCENEGEMS_WORKER_NODE_SLOTS", "integer"),
            "labels": parameter_value("SCENEGEMS_WORKER_NODE_LABELS", split=",", pair="="),
            "artifactCacheMaxBytes": parameter_value("SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES", "integer"),
        },
    }
    return role


def scenegems_roles(image_tag: Optional[str] = None) -> Dict[str, Any]:
    """The roles of a release whose images carry image_tag (release_image_tag), by default latest."""
    image_tag = image_tag or DEFAULT_IMAGE_TAG
    return {"control-node": control_node_role(image_tag), "worker-node": worker_node_role(image_tag)}


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
