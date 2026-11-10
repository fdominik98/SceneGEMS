"""Typed configuration of a simulation instance: environment plus one stack triple per vessel.

All vessels of one instance share one simulation layer instance and one clock, and each
vessel has its own (ASV system, control layer, simulation layer) triple. The registry
resolver validates a configuration before anything is built from it.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple

import numpy as np

from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId


@dataclass(frozen=True)
class VesselStackConfig:
    asv_system: AsvSystemId
    control_layer: ControlLayerId
    simulation_layer: SimulationLayerId

    def __str__(self) -> str:
        return f"{self.asv_system.value}, {self.control_layer.value}, {self.simulation_layer.value}"


@dataclass
class WaveConfig:
    amplitude: float
    period: float
    steepness: float
    direction: np.ndarray

    @property
    def speed(self) -> float:
        return float(np.linalg.norm(self.direction))

    @property
    def length(self) -> float:
        return self.period * self.speed

    @property
    def is_enabled(self) -> bool:
        return self.speed > 0


@dataclass
class EnvironmentConfig:
    wind_vector: np.ndarray  # [east, north, up] in m/s
    wave: WaveConfig
    seed: int = 0  # run seed; per-component seeds derive from it (contracts.clock.derive_seed)

    @property
    def wind_requested(self) -> bool:
        return bool(np.linalg.norm(self.wind_vector) > 0)

    @property
    def waves_requested(self) -> bool:
        return self.wave.is_enabled

    @classmethod
    def calm(cls, seed: int = 0) -> "EnvironmentConfig":
        return cls(
            wind_vector=np.zeros(3),
            wave=WaveConfig(amplitude=0.0, period=0.0, steepness=0.0, direction=np.zeros(2)),
            seed=seed,
        )


class AgentContext(str, Enum):
    SIMULATION = "simulation"  # part of the simulation instance
    REAL = "real"  # a physical vessel joined over MQTT through its ArduAgent; no stack is generated for it


@dataclass
class AgentConnection:
    """How the workbench reaches a vessel's agent over the MQTT broker."""

    agent_name: str
    topic: str
    port: Optional[int]  # ground control station MAVLink port; a real vessel may have none


@dataclass
class VesselConfig:
    agent_id: str
    # A real vessel's stack is (ASV system, real_vessel, real_vessel): its own autopilot and hull,
    # commanded through its ArduAgent by replay or Mission Planner, or left to its on_board software.
    stack: VesselStackConfig
    context: AgentContext = AgentContext.SIMULATION
    connection: Optional[AgentConnection] = None
    gazebo_vessel_model: Optional[str] = None  # SDF override; generated when None
    # Adapter ids chosen in place of the registry default where several adapters connect the
    # same two layers (for example ArduAgent or the lockstep MAVLink link from replay to ardupilot).
    adapter_ids: Tuple[str, ...] = ()

    @property
    def is_simulated(self) -> bool:
        return self.context == AgentContext.SIMULATION

    def require_connection(self) -> AgentConnection:
        if self.connection is None:
            raise ValueError(f"Vessel {self.agent_id} has no agent connection, which the {self.stack.control_layer.value} control layer needs.")
        return self.connection


@dataclass
class SimulationInstanceConfig:
    simulation_layer: SimulationLayerId
    environment: EnvironmentConfig
    vessels: Dict[str, VesselConfig] = field(default_factory=dict)  # by agent id
    speedup: int = 1  # requested pace for wall-clock coupled stacks (1 = real time)

    @property
    def simulated_vessels(self) -> Dict[str, VesselConfig]:
        return {agent_id: vessel for agent_id, vessel in self.vessels.items() if vessel.is_simulated}
