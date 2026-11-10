"""Roles of a vessel stack and the implementations each role can have.

A vessel stack is a triple: the ASV system decides where the vessel goes, the control
layer turns that decision into actuation, and the simulation layer moves the vessel. The
enum values are the ids used in configuration, in the registry and in run records.

One integration may cover several roles, joined by built-in adapters (AdapterSpec.built_in):
ArduPilot is a control layer and, through SITL, a simulation layer; a real vessel is its own
control layer and simulation layer, and may bring its own ASV system (on_board).
"""

from dataclasses import dataclass
from enum import Enum
from typing import Union


class Role(str, Enum):
    ASV_SYSTEM = "asv_system"
    CONTROL_LAYER = "control_layer"
    SIMULATION_LAYER = "simulation_layer"


class AsvSystemId(str, Enum):
    REPLAY = "replay"  # follows the generated trajectory
    USV_NAVIGATION = "usv_navigation"
    MISSION_PLANNER = "mission_planner"  # an operator or external software on a MAVLink port
    ON_BOARD = "on_board"  # the vessel's own software, brought by the layer below (LayerSpec.on_board_asv_system)


class ControlLayerId(str, Enum):
    ARDUPILOT = "ardupilot"
    CUSTOM = "custom"
    NONE = "none"  # the simulation layer integrates control itself
    REAL_VESSEL = "real_vessel"  # the physical vessel's own autopilot


class SimulationLayerId(str, Enum):
    KINEMATIC = "kinematic"
    GAZEBO = "gazebo"
    ARDUPILOT_SIM = "ardupilot_sim"
    REAL_VESSEL = "real_vessel"  # the physical vessel in the water, outside the simulation instance


LayerImplementationId = Union[AsvSystemId, ControlLayerId, SimulationLayerId]

_ROLE_BY_IMPLEMENTATION_TYPE = {
    AsvSystemId: Role.ASV_SYSTEM,
    ControlLayerId: Role.CONTROL_LAYER,
    SimulationLayerId: Role.SIMULATION_LAYER,
}

STACK_ROLE_ORDER = (Role.ASV_SYSTEM, Role.CONTROL_LAYER, Role.SIMULATION_LAYER)


@dataclass(frozen=True)
class LayerRef:
    """One implementation of one role, a node of the adapter graph."""

    role: Role
    impl: str

    @classmethod
    def of(cls, implementation: LayerImplementationId) -> "LayerRef":
        return cls(_ROLE_BY_IMPLEMENTATION_TYPE[type(implementation)], implementation.value)

    def __str__(self) -> str:
        return f"{self.role.value}/{self.impl}"
