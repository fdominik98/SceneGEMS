"""ArduAgent's control mode for the ASV system that drives an ArduPilot vessel.

MqttAgentClient and the ArduAgent driver of an attended simulation speak these modes: autonomous uploads
the trajectory as a mission to follow, external sends the vessel toward its last waypoint
and leaves the rest to whoever is on the MAVLink port, and on_board sends nothing: the
vessel's own software steers and ArduAgent only reports where it is.
"""

from typing import Dict

from scenegems_tool.vessel_stack.asv_system.mission_planner.mission_planner_specs import MISSION_PLANNER_MAVLINK_PORT
from scenegems_tool.vessel_stack.asv_system.replay.replay_specs import REPLAY_ARDUAGENT_FOLLOWER
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId
from scenegems_tool.vessel_stack.control_layers.real_vessel.real_vessel_specs import (
    MISSION_PLANNER_ARDUAGENT_REAL_VESSEL,
    ON_BOARD_ARDUAGENT_REAL_VESSEL,
    REPLAY_ARDUAGENT_REAL_VESSEL,
)

# Adapters whose vessels ArduAgent drives, commanded over MQTT (subsystems/simulation/arduagent_simulation_driver.py):
# a simulated vessel gets SITL, MAVProxy and ArduAgent, a real vessel brings its own ArduAgent.
# Any other adapter into ardupilot talks MAVLink to SITL itself (replay_mavlink_lockstep,
# usv_navigation_mavlink_lockstep), so its vessel gets SITL only.
ARDUAGENT_ADAPTER_IDS = frozenset(
    {
        REPLAY_ARDUAGENT_FOLLOWER.id,
        MISSION_PLANNER_MAVLINK_PORT.id,
        REPLAY_ARDUAGENT_REAL_VESSEL.id,
        MISSION_PLANNER_ARDUAGENT_REAL_VESSEL.id,
        ON_BOARD_ARDUAGENT_REAL_VESSEL.id,
    }
)

ON_BOARD_CONTROL_MODE = "on_board"

_ARDUAGENT_CONTROL_MODES: Dict[AsvSystemId, str] = {
    AsvSystemId.REPLAY: "autonomous",
    AsvSystemId.MISSION_PLANNER: "external",
    AsvSystemId.ON_BOARD: ON_BOARD_CONTROL_MODE,
}


def arduagent_control_mode(asv_system: AsvSystemId) -> str:
    if asv_system not in _ARDUAGENT_CONTROL_MODES:
        raise ValueError(f"ArduAgent has no control mode for ASV system {asv_system.value}")
    return _ARDUAGENT_CONTROL_MODES[asv_system]
