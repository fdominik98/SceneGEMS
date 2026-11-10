"""The availability matrix: all 64 (ASV system, control layer, simulation layer) triples against design section 3.3.

The 27 triples of the three simulators and the three ASV system SceneGEMS runs are the design's table. The
real vessel (its own control and simulation layer) and on_board ASV system add the rest: only the real
vessel's own stacks exist, every other row names why not.
"""

from typing import Dict, List, Tuple

import pytest

from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec, SpecStatus
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, LayerRef, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig
from scenegems_tool.vessel_stack.registry.catalog import build_registry, default_resolver
from scenegems_tool.vessel_stack.registry.resolver import StackResolver

AVAILABLE = "available"
PLANNED = "planned (phase 2)"
UNAVAILABLE = "unavailable"

RULED_OUT = {
    "mission_planner_none": "control layer none has no MAVLink endpoint",
    "mission_planner_custom": "the custom controller has no MAVLink",
    "none_gazebo": "Gazebo needs actuator commands",
    "none_ardupilot_sim": "ardupilot_sim is the physics inside ArduPilot SITL",
    "custom_ardupilot_sim": "SITL physics only accepts ArduPilot control",
    "kinematic": "the kinematic sim integrates control internally",
    "usv_navigation_real_vessel": "has no command for USV Navigation's heading and speed references",
    "on_board": "this control layer brings no ASV system of its own",
    "real_vessel_control": "a real vessel's autopilot drives only its own hull",
    "real_vessel_simulation": "a real vessel is moved only by its own autopilot",
}

SIMULATORS = ("kinematic", "gazebo", "ardupilot_sim")
SCENEGEMS_CONTROL_LAYERS = ("ardupilot", "custom", "none")

# (asv, control, simulation): (design status of section 3.3, status now, text every reason must contain)
# Design status "yes" rows are available since Phase 2; the "no" rows are unavailable
# with the design's reason. none with ardupilot_sim is a "no" added in Phase 1 (design doc 11.2).
EXPECTED: Dict[Tuple[str, str, str], Tuple[str, str, List[str]]] = {
    ("replay", "none", "kinematic"): ("yes", AVAILABLE, []),
    ("replay", "ardupilot", "kinematic"): ("no", UNAVAILABLE, [RULED_OUT["kinematic"]]),
    ("replay", "custom", "kinematic"): ("no", UNAVAILABLE, [RULED_OUT["kinematic"]]),
    ("replay", "ardupilot", "ardupilot_sim"): ("yes", AVAILABLE, []),
    ("replay", "none", "ardupilot_sim"): ("no", UNAVAILABLE, [RULED_OUT["none_ardupilot_sim"]]),
    ("replay", "custom", "ardupilot_sim"): ("no", UNAVAILABLE, [RULED_OUT["custom_ardupilot_sim"]]),
    ("replay", "ardupilot", "gazebo"): ("yes", AVAILABLE, []),
    ("replay", "custom", "gazebo"): ("yes", AVAILABLE, []),
    ("replay", "none", "gazebo"): ("no", UNAVAILABLE, [RULED_OUT["none_gazebo"]]),
    ("usv_navigation", "none", "kinematic"): ("yes", AVAILABLE, []),
    ("usv_navigation", "ardupilot", "kinematic"): ("no", UNAVAILABLE, [RULED_OUT["kinematic"]]),
    ("usv_navigation", "custom", "kinematic"): ("no", UNAVAILABLE, [RULED_OUT["kinematic"]]),
    ("usv_navigation", "ardupilot", "ardupilot_sim"): ("yes", AVAILABLE, []),
    ("usv_navigation", "none", "ardupilot_sim"): ("no", UNAVAILABLE, [RULED_OUT["none_ardupilot_sim"]]),
    ("usv_navigation", "custom", "ardupilot_sim"): ("no", UNAVAILABLE, [RULED_OUT["custom_ardupilot_sim"]]),
    ("usv_navigation", "ardupilot", "gazebo"): ("yes", AVAILABLE, []),
    ("usv_navigation", "custom", "gazebo"): ("yes", AVAILABLE, []),
    ("usv_navigation", "none", "gazebo"): ("no", UNAVAILABLE, [RULED_OUT["none_gazebo"]]),
    ("mission_planner", "none", "kinematic"): ("no", UNAVAILABLE, [RULED_OUT["mission_planner_none"]]),
    ("mission_planner", "ardupilot", "kinematic"): ("no", UNAVAILABLE, [RULED_OUT["kinematic"]]),
    ("mission_planner", "custom", "kinematic"): ("no", UNAVAILABLE, [RULED_OUT["mission_planner_custom"], RULED_OUT["kinematic"]]),
    ("mission_planner", "ardupilot", "ardupilot_sim"): ("yes, interactive only", AVAILABLE, []),
    ("mission_planner", "none", "ardupilot_sim"): ("no", UNAVAILABLE, [RULED_OUT["mission_planner_none"], RULED_OUT["none_ardupilot_sim"]]),
    ("mission_planner", "custom", "ardupilot_sim"): ("no", UNAVAILABLE, [RULED_OUT["mission_planner_custom"], RULED_OUT["custom_ardupilot_sim"]]),
    ("mission_planner", "ardupilot", "gazebo"): ("yes, interactive only", AVAILABLE, []),
    ("mission_planner", "custom", "gazebo"): ("no", UNAVAILABLE, [RULED_OUT["mission_planner_custom"]]),
    ("mission_planner", "none", "gazebo"): ("no", UNAVAILABLE, [RULED_OUT["mission_planner_none"], RULED_OUT["none_gazebo"]]),
    # A real vessel: its own autopilot and hull, reached through ArduAgent.
    ("replay", "real_vessel", "real_vessel"): ("yes, interactive only", AVAILABLE, []),
    ("mission_planner", "real_vessel", "real_vessel"): ("yes, interactive only", AVAILABLE, []),
    ("on_board", "real_vessel", "real_vessel"): ("yes, interactive only", AVAILABLE, []),
    ("usv_navigation", "real_vessel", "real_vessel"): ("no", UNAVAILABLE, [RULED_OUT["usv_navigation_real_vessel"]]),
}


def _ruled_out_by_the_new_layers(asv: str, control: str, simulation: str) -> List[str]:
    """Every other row with a new layer: on_board needs a layer that brings ASV system, the real
    vessel's autopilot moves only its own hull, and only that autopilot moves it."""
    reasons = []
    if asv == "on_board" and control != "real_vessel":
        reasons.append(RULED_OUT["on_board"])
    if control == "real_vessel" and simulation != "real_vessel":
        reasons.append(RULED_OUT["real_vessel_control"])
    if control != "real_vessel" and simulation == "real_vessel":
        reasons.append(RULED_OUT["real_vessel_simulation"])
    if asv == "usv_navigation" and control == "real_vessel":
        reasons.append(RULED_OUT["usv_navigation_real_vessel"])
    return reasons


for _asv in ("replay", "usv_navigation", "mission_planner", "on_board"):
    for _control in (*SCENEGEMS_CONTROL_LAYERS, "real_vessel"):
        for _simulation in (*SIMULATORS, "real_vessel"):
            EXPECTED.setdefault((_asv, _control, _simulation), ("no", UNAVAILABLE, _ruled_out_by_the_new_layers(_asv, _control, _simulation)))


def triple(chain) -> Tuple[str, str, str]:
    return (chain.stack.asv_system.value, chain.stack.control_layer.value, chain.stack.simulation_layer.value)


@pytest.fixture(scope="module")
def matrix():
    return {triple(chain): chain for chain in default_resolver().availability_matrix()}


def test_expected_table_covers_every_role_combination():
    every_triple = {(asv.value, control.value, simulation.value) for asv in AsvSystemId for control in ControlLayerId for simulation in SimulationLayerId}
    assert len(every_triple) == 64
    assert set(EXPECTED) == every_triple


def test_availability_matrix_lists_each_triple_once():
    chains = default_resolver().availability_matrix()
    assert len(chains) == 64
    assert len({triple(chain) for chain in chains}) == 64


def test_availability_matrix_orders_by_asv_then_simulation_then_control():
    chains = default_resolver().availability_matrix()
    assert [triple(chain) for chain in chains[:3]] == [("replay", "ardupilot", "kinematic"), ("replay", "custom", "kinematic"), ("replay", "none", "kinematic")]
    assert [chain.stack.simulation_layer for chain in chains[:16]].count(SimulationLayerId.KINEMATIC) == 4


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_triple_matches_design_table(matrix, key):
    design_status, status, reason_parts = EXPECTED[key]
    chain = matrix[key]
    assert chain.design_status == design_status
    assert chain.status == status
    assert chain.available == (status == AVAILABLE)
    for part in reason_parts:
        assert part in chain.reason
    if status == AVAILABLE:
        assert chain.reasons == ()


def test_matrix_counts_are_thirteen_available_none_planned_fifty_one_unavailable(matrix):
    statuses = [chain.status for chain in matrix.values()]
    assert statuses.count(AVAILABLE) == 13
    assert statuses.count(PLANNED) == 0
    assert statuses.count(UNAVAILABLE) == 51


def test_design_yes_rows_are_exactly_the_complete_chains(matrix):
    for chain in matrix.values():
        assert chain.complete == (chain.design_status != "no")


def test_unavailable_chain_has_no_capabilities(matrix):
    chain = matrix[("replay", "none", "gazebo")]
    assert chain.capabilities is None
    assert not chain.complete


def test_every_unavailable_row_names_a_reason(matrix):
    for chain in matrix.values():
        if not chain.available:
            assert chain.reason
            assert chain.reasons


def test_available_replay_on_ardupilot_defaults_to_the_lockstep_link(matrix):
    for simulation in ("ardupilot_sim", "gazebo"):
        chain = matrix[("replay", "ardupilot", simulation)]
        assert chain.asv_adapter is not None
        assert chain.asv_adapter.id == "replay_mavlink_lockstep"


def test_mission_planner_rows_are_interactive_only(matrix):
    for simulation in ("ardupilot_sim", "gazebo"):
        capabilities = matrix[("mission_planner", "ardupilot", simulation)].capabilities
        assert capabilities.interactive_only
        assert not capabilities.lockstep


def test_real_vessel_rows_are_workbench_only_and_real_time(matrix):
    for software in ("replay", "mission_planner", "on_board"):
        chain = matrix[(software, "real_vessel", "real_vessel")]
        capabilities = chain.capabilities
        assert capabilities.interactive_only
        assert not capabilities.lockstep
        assert not capabilities.faster_than_real_time
        assert capabilities.speedup_limit == 1.0
        assert capabilities.repeatability_tier.value == "none"
        assert chain.asv_adapter.id == f"{software}_arduagent_real_vessel"
        assert [adapter.id for adapter in chain.adapters][-1] == "real_vessel_autopilot"


def test_built_in_adapters_join_the_layers_of_one_integration():
    built_in = {adapter.id for adapter in build_registry({}).adapters if adapter.built_in}
    assert built_in == {"sitl_internal_physics", "real_vessel_autopilot"}


def test_only_the_real_vessel_brings_on_board_asv_system():
    assert [layer.id for layer in build_registry({}).layers if layer.on_board_asv_system] == ["control_layer/real_vessel"]


def test_planned_chain_lists_the_planned_specs():
    """No catalog spec is planned since Phase 2, so a planned alternative is registered here to see the resolver report it."""
    registry = build_registry({})
    registry.register_adapter(
        AdapterSpec(
            id="planned_probe",
            source=LayerRef.of(AsvSystemId.USV_NAVIGATION),
            target=LayerRef.of(ControlLayerId.ARDUPILOT),
            description="A planned adapter for this test.",
            status=SpecStatus.PLANNED,
            planned_phase=3,
        ),
        default=True,
    )
    chain = StackResolver(registry).resolve(VesselStackConfig(AsvSystemId.USV_NAVIGATION, ControlLayerId.ARDUPILOT, SimulationLayerId.GAZEBO))
    assert chain.status == "planned (phase 3)"
    assert {spec.id for spec in chain.planned_specs} == {"planned_probe"}


def test_usv_navigation_on_ardupilot_runs_through_the_lockstep_mavlink_link(matrix):
    for simulation in ("ardupilot_sim", "gazebo"):
        chain = matrix[("usv_navigation", "ardupilot", simulation)]
        assert chain.asv_adapter.id == "usv_navigation_mavlink_lockstep"
        assert chain.capabilities.lockstep


def test_usv_navigation_on_the_custom_controller_runs_through_its_heading_speed_input_and_the_gz_actuator(matrix):
    chain = matrix[("usv_navigation", "custom", "gazebo")]
    assert [adapter.id for adapter in chain.adapters] == ["custom_controller_heading_speed_input", "gz_transport_actuator"]


def test_replay_on_the_custom_controller_runs_through_the_waypoint_follower_and_the_gz_actuator(matrix):
    chain = matrix[("replay", "custom", "gazebo")]
    assert [adapter.id for adapter in chain.adapters] == ["custom_controller_waypoint_follower", "gz_transport_actuator"]


def test_resolving_with_an_adapter_alternative_changes_the_asv_adapter():
    stack = VesselStackConfig(AsvSystemId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM)
    chain = default_resolver().resolve(stack, ["replay_arduagent_follower"])
    assert chain.available
    assert chain.asv_adapter.id == "replay_arduagent_follower"
    assert chain.capabilities.lockstep is False
    assert chain.capabilities.exact_up_to_speedup == 1


def test_unknown_adapter_id_is_a_reason():
    stack = VesselStackConfig(AsvSystemId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM)
    chain = default_resolver().resolve(stack, ["no_such_adapter"])
    assert not chain.available
    assert "adapter no_such_adapter is not registered" in chain.reason


def test_adapter_of_another_connection_is_a_reason():
    stack = VesselStackConfig(AsvSystemId.REPLAY, ControlLayerId.ARDUPILOT, SimulationLayerId.ARDUPILOT_SIM)
    chain = default_resolver().resolve(stack, ["kinematic_command_input"])
    assert not chain.available
    assert "kinematic_command_input connects control_layer/none to simulation_layer/kinematic, which is not part of" in chain.reason
