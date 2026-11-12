"""Maps the workbench wire vocabulary to vessel stack triples and back.

The browser sends one simulatorType for the instance and, per agent, its ASV system
(asvSystem) and control layer (controlLayer). Older clients send only a controlMode per
agent, which names the ASV system (autonomous is replay, external is mission_planner); the
control layer then defaults to the one the simulator's ArduPilot-era stacks used (none on the
kinematic layer, ardupilot otherwise).

A real vessel (context real) is its own control and simulation layer: its stack is
(asvSystem, real_vessel, real_vessel), whatever simulator the instance runs, and its ASV
system is replay, mission_planner or on_board (its own software steers it).

Adapters: an instance with a real vessel runs through ArduAgent, which reaches real and
simulated vessels alike over the MQTT broker, so its simulated replay and Mission Planner
vessels select the ArduAgent adapters. An instance of simulated vessels uses the registry's
defaults (the lockstep MAVLink link, the custom controller's adapters, the Mission Planner
ground station port), which the attended simulation job drives with the lockstep runners.

The labels sent back (simulation_models) are the ones the browser offers, so the round
trip is unchanged.
"""

from typing import Dict, Optional, Tuple

from scenegems_tool.vessel_stack.asv_system.mission_planner.mission_planner_specs import MISSION_PLANNER_MAVLINK_PORT
from scenegems_tool.vessel_stack.asv_system.replay.replay_specs import REPLAY_ARDUAGENT_FOLLOWER
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import VesselStackConfig

_SIMULATOR_TYPE_LABELS: Dict[SimulationLayerId, str] = {
    SimulationLayerId.GAZEBO: "Gazebo",
    SimulationLayerId.ARDUPILOT_SIM: "ArduPilot Sim",
    SimulationLayerId.KINEMATIC: "Kinematic",
    SimulationLayerId.REAL_VESSEL: "Real vessel",  # the layer of a real agent, never the instance's simulator
}
# The simulators an instance can run on; a real vessel joins one of them.
INSTANCE_SIMULATION_LAYERS: Tuple[SimulationLayerId, ...] = tuple(layer for layer in SimulationLayerId if layer != SimulationLayerId.REAL_VESSEL)
_CONTROL_MODE_LABELS: Dict[AsvSystemId, str] = {
    AsvSystemId.REPLAY: "autonomous",
    AsvSystemId.MISSION_PLANNER: "external",
}
# The adapters ArduAgent drives a vessel through, for instances with a real vessel.
_ARDUAGENT_ADAPTER_IDS: Dict[AsvSystemId, Tuple[str, ...]] = {
    AsvSystemId.REPLAY: (REPLAY_ARDUAGENT_FOLLOWER.id,),
    AsvSystemId.MISSION_PLANNER: (MISSION_PLANNER_MAVLINK_PORT.id,),
}


def simulation_layer_from_simulator_type(simulator_type: str) -> SimulationLayerId:
    """simulatorType is compared case-insensitively, as before the adapter framework."""
    for layer, label in _SIMULATOR_TYPE_LABELS.items():
        if simulator_type.strip().lower() == label.lower():
            return layer
    raise ValueError(f"Unknown simulatorType '{simulator_type}'; expected one of {', '.join(label for layer, label in _SIMULATOR_TYPE_LABELS.items() if layer in INSTANCE_SIMULATION_LAYERS)}.")


def simulator_type_label(layer: SimulationLayerId) -> str:
    if layer not in _SIMULATOR_TYPE_LABELS:
        raise ValueError(f"Simulation layer {layer.value} has no workbench simulatorType.")
    return _SIMULATOR_TYPE_LABELS[layer]


def asv_system_from_control_mode(control_mode: str) -> AsvSystemId:
    for asv_system, label in _CONTROL_MODE_LABELS.items():
        if control_mode == label:
            return asv_system
    raise ValueError(f"Unknown controlMode '{control_mode}'; expected one of {', '.join(_CONTROL_MODE_LABELS.values())}.")


def control_mode_label(asv_system: AsvSystemId) -> Optional[str]:
    """The controlMode of an ASV system, None for one ArduAgent has no mode for (USV Navigation)."""
    return _CONTROL_MODE_LABELS.get(asv_system)


def default_control_layer(simulation_layer: SimulationLayerId) -> ControlLayerId:
    """The control layer of an agent that names none: the kinematic layer integrates control itself."""
    return ControlLayerId.NONE if simulation_layer == SimulationLayerId.KINEMATIC else ControlLayerId.ARDUPILOT


def _parse_role(enum, value: str, field: str):
    try:
        return enum(value)
    except ValueError:
        raise ValueError(f"Unknown {field} '{value}'; expected one of {', '.join(member.value for member in enum)}.") from None


def workbench_stack(simulator_type: str, asv_system: Optional[str], control_layer: Optional[str], control_mode: Optional[str] = None, real_vessel: bool = False) -> VesselStackConfig:
    """The triple of one agent: asvSystem (or, from older clients, controlMode) and controlLayer (or the simulator's default).

    A real vessel's control and simulation layers are its own (real_vessel); a controlLayer sent for it must say so or be left out.
    """
    simulation_layer = simulation_layer_from_simulator_type(simulator_type)
    if asv_system:
        software = _parse_role(AsvSystemId, asv_system, "asvSystem")
    elif control_mode:
        software = asv_system_from_control_mode(control_mode)
    else:
        raise ValueError("An agent needs an asvSystem (or a controlMode).")
    if real_vessel:
        if control_layer and control_layer != ControlLayerId.REAL_VESSEL.value:
            raise ValueError(f"A real vessel's control layer is its own autopilot ({ControlLayerId.REAL_VESSEL.value}), not '{control_layer}'.")
        return VesselStackConfig(asv_system=software, control_layer=ControlLayerId.REAL_VESSEL, simulation_layer=SimulationLayerId.REAL_VESSEL)
    control = _parse_role(ControlLayerId, control_layer, "controlLayer") if control_layer else default_control_layer(simulation_layer)
    return VesselStackConfig(asv_system=software, control_layer=control, simulation_layer=simulation_layer)


def workbench_adapter_ids(stack: VesselStackConfig, instance_has_real_vessel: bool) -> Tuple[str, ...]:
    """ArduAgent's adapters for the simulated vessels of an instance with a real vessel, else the registry's defaults (none named).

    A real vessel has one adapter per connection, every one of them through ArduAgent, so it names none.
    """
    if not instance_has_real_vessel or stack.simulation_layer == SimulationLayerId.REAL_VESSEL:
        return ()
    return _ARDUAGENT_ADAPTER_IDS.get(stack.asv_system, ())
