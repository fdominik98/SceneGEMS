import re

from scenegems_tool.cluster.fingerprints.components import COMPONENTS, SIMULATION_IMAGE, component_images
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.release.roles import NAME_PATTERN, POSTGRES_IMAGE, WORKER_NODE_IMAGE, component_item_images, role_images, scenegems_roles, slot_item_images
from tests.scenegems_tool.cluster.stack_images import GAZEBO_IMAGE, SITL_IMAGE

FIELDS = {"description", "count", "stack", "project", "images", "env", "parameters", "secrets", "setup", "outputs", "ready"}
PLACEHOLDERS = {"cluster", "name", "machine.vpn_ip", "machine.name", "release.revision", "dependent.name"}
# {<role>.vpn_ip} and {<role>.<parameter>}: the machine of another role of the cluster
CONTROL_NODE_PLACEHOLDERS = {"control-node.vpn_ip"} | {f"control-node.{key}" for key in scenegems_roles()["control-node"]["parameters"]}


def _texts(role):
    yield role["project"]
    yield from role["env"].values()
    yield from (parameter["default"] for parameter in role["parameters"].values())
    for command in role["setup"]:
        yield from command
    for output in role["outputs"].values():
        yield from output["command"]


def test_every_role_has_the_contract_fields():
    for name, role in scenegems_roles().items():
        assert FIELDS <= set(role), name
        assert role["count"] in ("one", "many")


def test_placeholders_are_the_documented_ones():
    for role in scenegems_roles().values():
        for text in _texts(role):
            assert set(re.findall(r"\{([^{}]+)\}", text)) <= PLACEHOLDERS | CONTROL_NODE_PLACEHOLDERS, text


def test_secrets_parameters_and_fixed_values_do_not_overlap():
    for role in scenegems_roles().values():
        env, parameters, secrets = set(role["env"]), set(role["parameters"]), set(role["secrets"])
        required = set(role.get("requires", {}).get("keys", []))
        groups = [env, parameters, secrets, required]
        assert sum(len(group) for group in groups) == len(set().union(*groups))


def test_the_worker_node_needs_nothing_from_a_deployed_control_node():
    roles = scenegems_roles()
    assert "requires" not in roles["worker-node"] and roles["control-node"]["outputs"] == {} and roles["control-node"]["setup"] == []
    assert roles["control-node"]["count"] == "one"  # {control-node.*} names the one control node of the cluster
    env = roles["worker-node"]["env"]
    assert env["SCENEGEMS_CONTROL_NODE_ID"] == "{cluster}"
    assert env["SCENEGEMS_CONTROL_NODE_URL"] == "http://{control-node.vpn_ip}:{control-node.SCENEGEMS_API_PORT}"
    assert env["SCENEGEMS_BROKER_PORT"] == "{control-node.SCENEGEMS_BROKER_PORT}"


def test_there_are_no_secrets_but_the_database_password():
    assert scenegems_roles()["control-node"]["secrets"] == ["POSTGRES_PASSWORD"] and scenegems_roles()["worker-node"]["secrets"] == []


def test_component_items_are_the_catalog_with_its_images():
    images = component_item_images()
    assert list(images) == list(COMPONENTS)
    assert all(images[component] == list(component_images()[component]) for component in COMPONENTS)
    assert images["control_layer/ardupilot"] == [SITL_IMAGE]
    assert images["simulation_layer/gazebo"] == sorted([SIMULATION_IMAGE, GAZEBO_IMAGE])
    assert images["asv_system/replay"] == images["control_layer/custom"] == [SIMULATION_IMAGE], "their containers start from the simulation subsystem image"
    assert images["asv_system/usv_navigation"] == ["scenegems-usv-navigation:latest"], "a worker node that offers USV Navigation gets its image"
    assert images["control_layer/none"] == []


def test_slot_items_are_the_job_types_without_images_of_their_own():
    assert slot_item_images() == {job_type.value: [] for job_type in JobType}
    assert set(slot_item_images()) == {"design_space_exploration", "scene_generation", "trajectory_generation", "simulation", "monitoring.post_hoc", "calibration.deviation"}


def test_the_worker_node_parameters_are_components_without_an_amount_and_slots_with_one():
    parameters = scenegems_roles()["worker-node"]["parameters"]
    assert "SCENEGEMS_WORKER_NODE_CAPABILITIES" not in parameters
    components, slots = parameters["SCENEGEMS_WORKER_NODE_COMPONENTS"]["items"], parameters["SCENEGEMS_WORKER_NODE_SLOTS"]["items"]
    assert components["separator"] == "," and "key_separator" not in components and components["images"] == component_item_images()
    assert (slots["separator"], slots["key_separator"], slots["images"]) == (",", ":", slot_item_images())


def test_role_images_include_every_image_a_role_may_need():
    images = role_images(scenegems_roles())
    assert WORKER_NODE_IMAGE in images and POSTGRES_IMAGE in images and GAZEBO_IMAGE in images
    assert images == sorted(set(images))


def test_the_defaults_are_a_kinematic_worker_node_the_worker_node_configuration_accepts():
    from scenegems_tool.cluster.worker_node.daemon.configuration.worker_node_configuration import parse_components, parse_slots, slots_without_components

    parameters = scenegems_roles()["worker-node"]["parameters"]
    components = parameters["SCENEGEMS_WORKER_NODE_COMPONENTS"]["default"].split(",")
    slots = [item.split(":")[0] for item in parameters["SCENEGEMS_WORKER_NODE_SLOTS"]["default"].split(",")]
    assert set(components) <= set(parameters["SCENEGEMS_WORKER_NODE_COMPONENTS"]["items"]["images"])
    assert set(slots) <= set(parameters["SCENEGEMS_WORKER_NODE_SLOTS"]["items"]["images"])
    assert "simulation_layer/kinematic" in components and not {"control_layer/ardupilot", "simulation_layer/gazebo"} & set(components)
    parsed = parse_slots(parameters["SCENEGEMS_WORKER_NODE_SLOTS"]["default"])
    assert slots_without_components(parsed, parse_components(parameters["SCENEGEMS_WORKER_NODE_COMPONENTS"]["default"])) == []


def test_cluster_ids_and_names_are_single_scope_names():
    pattern = re.compile(NAME_PATTERN)
    assert pattern.fullmatch("control-node-1") and pattern.fullmatch("worker-2")
    assert not pattern.fullmatch("ControlNode_1") and not pattern.fullmatch("a/b")


def test_the_worker_node_reports_its_machine_from_the_machine_name():
    from scenegems_tool.cluster.worker_node.daemon.configuration.worker_node_configuration import WorkerNodeConfiguration

    worker_node = scenegems_roles()["worker-node"]
    assert worker_node["env"]["SCENEGEMS_WORKER_NODE_MACHINE"] == "{machine.name}"
    values = {"SCENEGEMS_CONTROL_NODE_URL": "http://10.88.0.2:8443", "SCENEGEMS_CONTROL_NODE_ID": "lab"}
    values.update({"SCENEGEMS_WORKER_NODE_NAME": "worker-1", "SCENEGEMS_WORKER_NODE_STATE_DIR": "/state"})
    values.update({key: worker_node["parameters"][key]["default"] for key in ("SCENEGEMS_WORKER_NODE_SLOTS", "SCENEGEMS_WORKER_NODE_COMPONENTS")})
    values["SCENEGEMS_WORKER_NODE_MACHINE"] = worker_node["env"]["SCENEGEMS_WORKER_NODE_MACHINE"].replace("{machine.name}", "lab-pc-3")
    assert WorkerNodeConfiguration.from_values(values).machine == "lab-pc-3"


def test_the_allowed_origins_are_a_control_node_parameter_with_the_code_s_defaults():
    from scenegems_tool.cluster.control_node.settings import DEFAULT_OPERATOR_ALLOWED_ORIGINS, parse_allowed_origins

    parameter = scenegems_roles()["control-node"]["parameters"]["SCENEGEMS_OPERATOR_ALLOWED_ORIGINS"]
    assert parse_allowed_origins(parameter["default"]) == DEFAULT_OPERATOR_ALLOWED_ORIGINS
    assert "items" not in parameter and parameter["description"]


def test_the_artifact_settings_are_parameters_with_the_code_s_defaults():
    from scenegems_tool.cluster.control_node.settings import ArtifactSettings
    from scenegems_tool.cluster.worker_node.daemon.configuration.worker_node_configuration import DEFAULT_ARTIFACT_CACHE_MAX_BYTES

    roles = scenegems_roles()
    control_node, worker_node = roles["control-node"]["parameters"], roles["worker-node"]["parameters"]
    assert int(control_node["SCENEGEMS_ARTIFACT_MAX_BYTES"]["default"]) == ArtifactSettings.max_bytes
    assert float(control_node["SCENEGEMS_ARTIFACT_SWEEP_INTERVAL_S"]["default"]) == ArtifactSettings.sweep_interval_s
    assert float(control_node["SCENEGEMS_ARTIFACT_SWEEP_GRACE_S"]["default"]) == ArtifactSettings.sweep_grace_s
    assert int(worker_node["SCENEGEMS_WORKER_NODE_ARTIFACT_CACHE_MAX_BYTES"]["default"]) == DEFAULT_ARTIFACT_CACHE_MAX_BYTES


def test_a_release_s_images_carry_its_tag_and_the_pulled_one_keeps_its_own():
    from scenegems_tool.cluster.release.roles import release_image_tag

    assert release_image_tag("abc", False) == "abc" and release_image_tag("abc", True) == "abc-dirty"
    roles = scenegems_roles("abc")
    images = role_images(roles)
    assert POSTGRES_IMAGE in images and all(image.endswith(":abc") for image in images if image != POSTGRES_IMAGE)
    assert roles["control-node"]["env"]["SCENEGEMS_IMAGE_TAG"] == roles["worker-node"]["env"]["SCENEGEMS_IMAGE_TAG"] == "abc"
    assert all(image.endswith(":abc") for images in roles["worker-node"]["parameters"]["SCENEGEMS_WORKER_NODE_COMPONENTS"]["items"]["images"].values() for image in images)
    assert scenegems_roles()["worker-node"]["images"] == [WORKER_NODE_IMAGE] and WORKER_NODE_IMAGE.endswith(":latest")


def test_the_control_node_reads_its_compose_files_from_a_parameter():
    control_node = scenegems_roles()["control-node"]
    assert control_node["parameters"]["COMPOSE_FILE"]["default"] == "docker-compose.yml:docker-compose.live-sessions.yml"
    assert control_node["env"]["COMPOSE_PATH_SEPARATOR"] == ":"
