"""Generated Docker stacks for the snapshot and property tests: three representative instances.

- gazebo_lockstep_wind: Gazebo with the default replay_mavlink_lockstep link and a wind
  (SITL only per vessel, the assurance path);
- ardupilot_sim_lockstep: ArduPilot Sim with the same link at 5x;
- ardupilot_sim_arduagent: ArduPilot Sim as the workbench builds it, one autonomous vessel on
  the ArduAgent follower and one external vessel for Mission Planner (SITL, MAVProxy and ArduAgent).
"""

import os
from dataclasses import dataclass
from typing import Dict

import yaml

from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentConnection, SimulationInstanceConfig, VesselConfig, VesselStackConfig
from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, mqtt_connection, stack_instance, wind_environment

CASE_NAMES = ("gazebo_lockstep_wind", "ardupilot_sim_lockstep", "ardupilot_sim_arduagent")


@dataclass(frozen=True)
class GeneratedStack:
    case: str
    files: Dict[str, str]  # by file name; trajectories.json is left out (it is the input, serialized)
    pending_paths: tuple  # every path written, in order
    compose: dict

    @property
    def compose_yaml(self) -> str:
        return yaml.dump(self.compose, default_flow_style=False, sort_keys=False, width=10000)


def _instance(case: str) -> SimulationInstanceConfig:
    if case == "gazebo_lockstep_wind":
        return stack_instance(SimulationLayerId.GAZEBO, [0, 1], environment=wind_environment(3.0, 4.0))
    if case == "ardupilot_sim_lockstep":
        return stack_instance(SimulationLayerId.ARDUPILOT_SIM, [0, 1], speedup=5)
    if case == "ardupilot_sim_arduagent":
        layer = SimulationLayerId.ARDUPILOT_SIM
        instance = stack_instance(layer, [0, 1], adapter_ids=["replay_arduagent_follower"])
        instance.vessels["1"] = VesselConfig(
            agent_id="1",
            stack=VesselStackConfig(AsvSystemId.MISSION_PLANNER, ControlLayerId.ARDUPILOT, layer),
            connection=AgentConnection(agent_name="agent_1", topic="waraps/unit/surface/agent_1", port=14560),
            adapter_ids=("mission_planner_mavlink_port",),
        )
        return instance
    raise KeyError(case)


def generate_stack(case: str, headless: bool = True) -> GeneratedStack:
    trajectories = encounter_trajectories("head_on", 60)
    writes, compose = build_simulation_docker_stack_artifacts(_instance(case), trajectories, mqtt_connection(), GEOFENCE, headless=headless)
    files = {os.path.basename(path): content for path, content in writes if not path.endswith("trajectories.json")}
    return GeneratedStack(case=case, files=files, pending_paths=tuple(os.path.basename(path) for path, _ in writes), compose=compose)
