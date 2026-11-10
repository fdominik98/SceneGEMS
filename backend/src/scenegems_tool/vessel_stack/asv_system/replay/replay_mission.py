"""The mission ArduAgent receives for a vessel: its generated trajectory, shaped for ArduPilot."""

from typing import List

from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.vessel_stack.asv_system.replay.path_simplification import simplify_state_path
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence, waypoint_from_state

REPLAY_MISSION_MAX_SCENES = 400


def cap_mission_trajectories(trajectories: Trajectories) -> Trajectories:
    return TrajectoryBuilder.from_trajectories(trajectories).convert_to_max_scene_number(REPLAY_MISSION_MAX_SCENES).build()


def replay_mission_waypoints(capped_trajectories: Trajectories, vessel: ConcreteVessel, max_speed: float, reference_geofence: Geofence) -> List[dict]:
    """Waypoints from the first state above 90 percent of max_speed, thinned to the real corners."""
    state_list = capped_trajectories.state_list(vessel)
    first_index_with_max_speed = next((i for i, s in enumerate(state_list) if s.speed > max_speed * 0.9), 0)
    path_states = state_list[first_index_with_max_speed:]

    # Thin the densely sampled path so ArduPilot waypoint navigation can
    # build smooth legs instead of treating every 1-2 s sample as a
    # corner (which makes skid-steer hulls pivot and crawl). Straight
    # runs collapse to their endpoints; real corners are kept.
    epsilon_m = max(vessel.length * 0.5, 1.0)
    path_states = simplify_state_path(path_states, epsilon_m=epsilon_m)

    return [waypoint_from_state(s, reference_geofence) for s in path_states]
