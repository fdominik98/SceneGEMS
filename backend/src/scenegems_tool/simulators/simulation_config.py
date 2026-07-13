from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np


@dataclass
class SimulatedAgentConfig:
    agent_id: str
    context: str
    control_mode: str
    agent_name: str
    topic: str
    port: Optional[int]
    gazebo_vessel_model: Optional[str]


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
class SimulationConfig:
    simulator_type: str
    wind_vector: np.ndarray
    wave: WaveConfig
    simulated_agents: Dict[str, SimulatedAgentConfig]
    simulation_speed: int

    @property
    def is_gazebo_sim(self) -> bool:
        return self.simulator_type.lower() == "gazebo"

    @property
    def is_ardupilot_sim(self) -> bool:
        return self.simulator_type.lower() == "ardupilot sim"
