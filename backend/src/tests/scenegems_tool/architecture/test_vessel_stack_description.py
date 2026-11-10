"""The vessel stack document is read from the registry: nodes are layers, edges adapters, rows the resolver's matrix."""

import pytest

from scenegems_tool.architecture.vessel_stack_description import CLUSTER_JOB_FACT, META_ASV_TO_CONTROL, META_CONTROL_TO_SIMULATION, vessel_stack_document
from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, LayerSpec, SpecStatus
from scenegems_tool.vessel_stack.contracts.capabilities import Capabilities, RepeatabilityTier
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId, LayerRef, Role
from scenegems_tool.vessel_stack.registry.adapter_registry import AdapterRegistry
from scenegems_tool.vessel_stack.registry.catalog import UNSUPPORTED_CONNECTIONS, default_registry, default_resolver
from scenegems_tool.vessel_stack.registry.measured_capabilities import parse_capability_measurement


@pytest.fixture(scope="module")
def document():
    return vessel_stack_document()


def fact(owner, key):
    return next(item for item in owner.facts if item.key == key)


def test_every_registered_layer_and_adapter_is_a_node_or_an_edge(document):
    registry = default_registry()
    assert {node.id for node in document.nodes} == {spec.id for spec in registry.layers}
    assert {edge.id for edge in document.edges} == {spec.id for spec in registry.adapters}
    assert {node.lane for node in document.nodes} == {"asv_software", "control_layer", "simulation_layer"}


def test_the_rows_are_the_resolvers_matrix(document):
    matrix = default_resolver().availability_matrix()
    assert len(document.combinations) == len(matrix) == 64
    expected = {
        (f"asv_software/{chain.stack.asv_software.value}", f"control_layer/{chain.stack.control_layer.value}", f"simulation_layer/{chain.stack.simulation_layer.value}")
        for chain in matrix
        if chain.available
    }
    assert {combination.path for combination in document.combinations if combination.status == "available"} == expected
    ruled_out = next(combination for combination in document.combinations if combination.path == ("asv_software/replay", "control_layer/custom", "simulation_layer/kinematic"))
    assert ruled_out.status == "unavailable" and "no adapter" in ruled_out.reasons[0]


def test_the_ruled_out_connections_come_with_their_reasons(document):
    assert len(document.unsupported) == len(UNSUPPORTED_CONNECTIONS)
    reasons = {(link.source, link.target): link.reason for link in document.unsupported}
    assert "Gazebo needs actuator commands" in reasons[("control_layer/none", "simulation_layer/gazebo")]


def test_edges_know_their_metamodel_edge_and_whether_they_are_the_default(document):
    edges = {edge.id: edge for edge in document.edges}
    assert edges["kinematic_command_input"].implements == META_CONTROL_TO_SIMULATION
    assert edges["replay_state_follower"].implements == META_ASV_TO_CONTROL
    assert edges["replay_mavlink_lockstep"].default and not edges["replay_arduagent_follower"].default
    assert "alternative" in edges["replay_arduagent_follower"].tags


def test_measured_values_are_marked_and_carry_their_evidence(document):
    gazebo = {node.id: node for node in document.nodes}["simulation_layer/gazebo"]
    assert fact(gazebo, "wind").measured and fact(gazebo, "wind").value == "supported"
    assert not fact(gazebo, "lockstep").measured
    assert gazebo.evidence
    plugin = {edge.id: edge for edge in document.edges}["ardupilot_gazebo_plugin"]
    assert fact(plugin, "repeatability_tier").measured and fact(plugin, "repeatability_tier").value == "bounded"
    assert any(item.key == "deviation_bounds_m" and item.measured for item in plugin.facts)
    assert any(item.key.startswith("max_speedup_on_") for item in plugin.facts)


def test_a_speedup_that_is_not_measured_says_so(document):
    plugin = {edge.id: edge for edge in document.edges}["ardupilot_gazebo_plugin"]
    assert fact(plugin, "max_speedup").value is None and fact(plugin, "max_speedup").note == "not measured"


def test_the_metamodel_comes_from_the_contracts(document):
    nodes = {node.id.split("/", 1)[1]: node for node in document.metamodel_nodes}
    roles = {node.lane for node in document.metamodel_nodes if node.kind == "role"}
    assert roles == {"asv_software", "control_layer", "simulation_layer"}
    assert any("DockerSimulationLayer.finish(artifacts, request)" in member for member in nodes["runtime/docker_simulation_layer"].members)
    assert any("on_step(request, observation)" in member for member in nodes["runtime/lockstep_participant"].members)
    assert any(member.startswith("LayerSpec(layer, description, capabilities") for member in nodes["layer/asv_software"].members)
    edges = {edge.id for edge in document.metamodel_edges}
    assert {META_ASV_TO_CONTROL, META_CONTROL_TO_SIMULATION} <= edges
    assert any("vessel_state:" in note and "heading_speed_cmd:" in note for note in document.notes)


def test_a_new_simulator_and_adapter_show_up_without_a_change_in_the_description():
    new_sim = LayerRef(Role.SIMULATION_LAYER, "new_sim")
    custom = LayerRef.of(ControlLayerId.CUSTOM)
    registry = AdapterRegistry({"simulation_layer/new_sim": parse_capability_measurement("simulation_layer/new_sim", {"wind": "supported", "evidence": "measured today"})})
    registry.register_layer(LayerSpec(layer=custom, description="custom"))
    registry.register_layer(
        LayerSpec(layer=new_sim, description="a new simulator", capabilities=Capabilities(repeatability_tier=RepeatabilityTier.BOUNDED), status=SpecStatus.PLANNED, planned_phase=9)
    )
    registry.register_adapter(AdapterSpec(id="custom_to_new_sim", source=custom, target=new_sim, description="actuators"))
    result = vessel_stack_document(registry=registry, unsupported=())
    assert [node.id for node in result.nodes] == ["control_layer/custom", "simulation_layer/new_sim"]
    assert result.nodes[1].status == "planned" and fact(result.nodes[1], "wind").measured and result.nodes[1].evidence == "measured today"
    assert [(edge.id, edge.source, edge.target) for edge in result.edges] == [("custom_to_new_sim", "control_layer/custom", "simulation_layer/new_sim")]
    assert result.combinations == ()  # the matrix runs over the role enums, and this registry has not every layer of a row


def test_built_in_adapters_and_on_board_layers_are_marked(document):
    edges = {edge.id: edge for edge in document.edges}
    assert "built-in" in edges["real_vessel_autopilot"].tags
    assert "built-in" in edges["sitl_internal_physics"].tags
    assert "built-in" not in edges["replay_arduagent_real_vessel"].tags
    nodes = {node.id: node for node in document.nodes}
    assert any(fact.key == "on_board_asv_software" for fact in nodes["control_layer/real_vessel"].facts)
    assert not any(fact.key == "on_board_asv_software" for fact in nodes["control_layer/ardupilot"].facts)


def _combination(document, asv_software, control_layer, simulation_layer):
    path = (f"asv_software/{asv_software}", f"control_layer/{control_layer}", f"simulation_layer/{simulation_layer}")
    return next(combination for combination in document.combinations if combination.path == path)


def test_an_available_stack_names_the_cluster_job_that_runs_it(document):
    assert fact(_combination(document, "replay", "ardupilot", "gazebo"), CLUSTER_JOB_FACT).value == "simulation, runner ardupilot"
    assert fact(_combination(document, "usv_navigation", "none", "kinematic"), CLUSTER_JOB_FACT).value == "simulation, runner kinematic"
    assert fact(_combination(document, "usv_navigation", "ardupilot", "ardupilot_sim"), CLUSTER_JOB_FACT).value == "simulation, runner ardupilot"
    assert fact(_combination(document, "replay", "custom", "gazebo"), CLUSTER_JOB_FACT).value == "simulation, runner gazebo_custom"
    assert fact(_combination(document, "usv_navigation", "custom", "gazebo"), CLUSTER_JOB_FACT).value == "simulation, runner gazebo_custom"
    workbench_only = fact(_combination(document, "mission_planner", "ardupilot", "gazebo"), CLUSTER_JOB_FACT)
    assert workbench_only.value is None and workbench_only.note.startswith("workbench only")
    assert not any(item.key == CLUSTER_JOB_FACT for item in _combination(document, "replay", "custom", "kinematic").facts), "a stack that is not available names none"
    assert any("only when a runner of the simulation job runs it" in note for note in document.notes)


def test_mavproxy_and_arduagent_sit_on_the_adapters_that_start_them(document):
    def images(owner):
        return {item.value for item in owner.facts if item.key.startswith("container_")}

    nodes, edges = {node.id: node for node in document.nodes}, {edge.id: edge for edge in document.edges}
    assert images(nodes["control_layer/ardupilot"]) == {"${SITL_IMAGE:-scenegems-ardupilot-sitl:latest}"}
    assert (
        images(edges["replay_arduagent_follower"])
        == images(edges["mission_planner_mavlink_port"])
        == {"${MAVPROXY_IMAGE:-scenegems-mavproxy:latest}", "${ARDUAGENT_IMAGE:-scenegems-arduagent:latest}"}
    )
    assert images(edges["mission_planner_gcs_port"]) == {"${MAVPROXY_IMAGE:-scenegems-mavproxy:latest}"}
    replay_container = {"${SCENARIO_EXECUTION_IMAGE:-scenegems-scenario-execution-subsystem:latest}"}
    assert images(edges["replay_mavlink_lockstep"]) == images(edges["replay_state_follower"]) == replay_container, "the vessel's replay container, and no MAVProxy or ArduAgent"
    assert images(nodes["asv_software/usv_navigation"]) == {"${USV_NAVIGATION_IMAGE:-scenegems-usv-navigation:latest}"}
    assert images(nodes["control_layer/custom"]) == images(nodes["simulation_layer/kinematic"]) == replay_container, "they start from the scenario execution image too"
    assert images(nodes["control_layer/none"]) == set(), "no controller, no container"
