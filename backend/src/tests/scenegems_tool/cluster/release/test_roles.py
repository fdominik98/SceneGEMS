import re

from scenegems_tool.cluster.fingerprints.job_images import SCENARIO_EXECUTION_IMAGE, job_type_images
from scenegems_tool.cluster.protocol.jobs import JobType
from scenegems_tool.cluster.release.roles import NAME_PATTERN, NODE_IMAGE, POSTGRES_IMAGE, capability_item_images, role_images, scenegems_roles
from tests.scenegems_tool.cluster.stack_images import GAZEBO_IMAGE, SITL_IMAGE

FIELDS = {"description", "count", "stack", "project", "images", "env", "parameters", "secrets", "setup", "outputs", "ready"}
PLACEHOLDERS = {"cluster", "name", "machine.vpn_ip", "machine.name", "release.revision", "dependent.name"}
# {<role>.vpn_ip} and {<role>.<parameter>}: the machine of another role of the cluster
MASTER_PLACEHOLDERS = {"master.vpn_ip"} | {f"master.{key}" for key in scenegems_roles()["master"]["parameters"]}


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
            assert set(re.findall(r"\{([^{}]+)\}", text)) <= PLACEHOLDERS | MASTER_PLACEHOLDERS, text


def test_secrets_parameters_and_fixed_values_do_not_overlap():
    for role in scenegems_roles().values():
        env, parameters, secrets = set(role["env"]), set(role["parameters"]), set(role["secrets"])
        required = set(role.get("requires", {}).get("keys", []))
        groups = [env, parameters, secrets, required]
        assert sum(len(group) for group in groups) == len(set().union(*groups))


def test_the_node_needs_nothing_from_a_deployed_master():
    roles = scenegems_roles()
    assert "requires" not in roles["node"] and roles["master"]["outputs"] == {} and roles["master"]["setup"] == []
    assert roles["master"]["count"] == "one"  # {master.*} names the one master machine of the cluster
    env = roles["node"]["env"]
    assert env["SCENEGEMS_MASTER_ID"] == "{cluster}"
    assert env["SCENEGEMS_MASTER_URL"] == "http://{master.vpn_ip}:{master.SCENEGEMS_API_PORT}"
    assert env["SCENEGEMS_BROKER_PORT"] == "{master.SCENEGEMS_BROKER_PORT}"


def test_there_are_no_secrets_but_the_database_password():
    assert scenegems_roles()["master"]["secrets"] == ["POSTGRES_PASSWORD"] and scenegems_roles()["node"]["secrets"] == []


def test_capability_items_are_the_job_types_with_their_images_from_the_vessel_stack_matrix():
    images = capability_item_images()
    assert set(images) == {job_type.value for job_type in JobType}
    for job_type in JobType:
        assert images[job_type.value] == list(job_type_images()[job_type])
    assert images["simulation.ardupilot_sim"] == [SCENARIO_EXECUTION_IMAGE, SITL_IMAGE]
    assert images["simulation.gazebo"] == [SCENARIO_EXECUTION_IMAGE, SITL_IMAGE, GAZEBO_IMAGE]
    assert "simulation.ardupilot" not in images


def test_role_images_include_every_image_a_role_may_need():
    images = role_images(scenegems_roles())
    assert NODE_IMAGE in images and POSTGRES_IMAGE in images and GAZEBO_IMAGE in images
    assert images == sorted(set(images))


def test_the_default_capabilities_name_known_job_types():
    capabilities = scenegems_roles()["node"]["parameters"]["SCENEGEMS_NODE_CAPABILITIES"]
    items = [item.split(":")[0] for item in capabilities["default"].split(",")]
    assert set(items) <= set(capabilities["items"]["images"])


def test_cluster_ids_and_names_are_single_scope_names():
    pattern = re.compile(NAME_PATTERN)
    assert pattern.fullmatch("master-1") and pattern.fullmatch("worker-2")
    assert not pattern.fullmatch("Master_1") and not pattern.fullmatch("a/b")


def test_the_node_reports_its_machine_from_the_machine_name():
    from scenegems_tool.cluster.node.daemon.configuration.node_configuration import NodeConfiguration

    node = scenegems_roles()["node"]
    assert node["env"]["SCENEGEMS_NODE_MACHINE"] == "{machine.name}"
    values = {"SCENEGEMS_MASTER_URL": "http://10.88.0.2:8443", "SCENEGEMS_MASTER_ID": "lab"}
    values.update({"SCENEGEMS_NODE_NAME": "worker-1", "SCENEGEMS_NODE_CAPABILITIES": node["parameters"]["SCENEGEMS_NODE_CAPABILITIES"]["default"], "SCENEGEMS_NODE_STATE_DIR": "/state"})
    values["SCENEGEMS_NODE_MACHINE"] = node["env"]["SCENEGEMS_NODE_MACHINE"].replace("{machine.name}", "lab-pc-3")
    assert NodeConfiguration.from_values(values).machine == "lab-pc-3"


def test_the_allowed_origins_are_a_master_parameter_with_the_code_s_defaults():
    from scenegems_tool.cluster.master.settings import DEFAULT_OPERATOR_ALLOWED_ORIGINS, parse_allowed_origins

    parameter = scenegems_roles()["master"]["parameters"]["SCENEGEMS_OPERATOR_ALLOWED_ORIGINS"]
    assert parse_allowed_origins(parameter["default"]) == DEFAULT_OPERATOR_ALLOWED_ORIGINS
    assert "items" not in parameter and parameter["description"]


def test_the_artifact_settings_are_parameters_with_the_code_s_defaults():
    from scenegems_tool.cluster.master.settings import ArtifactSettings
    from scenegems_tool.cluster.node.daemon.configuration.node_configuration import DEFAULT_ARTIFACT_CACHE_MAX_BYTES

    roles = scenegems_roles()
    master, node = roles["master"]["parameters"], roles["node"]["parameters"]
    assert int(master["SCENEGEMS_ARTIFACT_MAX_BYTES"]["default"]) == ArtifactSettings.max_bytes
    assert float(master["SCENEGEMS_ARTIFACT_SWEEP_INTERVAL_S"]["default"]) == ArtifactSettings.sweep_interval_s
    assert float(master["SCENEGEMS_ARTIFACT_SWEEP_GRACE_S"]["default"]) == ArtifactSettings.sweep_grace_s
    assert int(node["SCENEGEMS_NODE_ARTIFACT_CACHE_MAX_BYTES"]["default"]) == DEFAULT_ARTIFACT_CACHE_MAX_BYTES
