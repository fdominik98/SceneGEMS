"""replay_mission: the ArduAgent mission shaped from a generated trajectory."""

from scenegems_tool.vessel_stack.asv_system.replay.replay_mission import REPLAY_MISSION_MAX_SCENES, cap_mission_trajectories, replay_mission_waypoints
from tests.scenegems_tool.vessel_stack.scenarios import GEOFENCE, encounter_trajectories, straight_trajectories


def test_short_trajectories_pass_the_scene_cap_unchanged():
    trajectories = encounter_trajectories("head_on", 100)
    assert len(cap_mission_trajectories(trajectories)) == len(trajectories)


def test_long_trajectories_are_capped_in_scene_count():
    trajectories = straight_trajectories(timespan=2000)
    capped = cap_mission_trajectories(trajectories)
    assert len(trajectories) == 2001
    assert capped.timespan / capped.time_step <= REPLAY_MISSION_MAX_SCENES  # the cap counts time steps, so the scene list has one more scene
    assert capped.time_step == 5
    assert capped.timespan == 2000


def test_straight_run_becomes_start_and_end_waypoints():
    trajectories = straight_trajectories(timespan=100)
    vessel = trajectories.initial_scene.os
    waypoints = replay_mission_waypoints(trajectories, vessel, 8.0, GEOFENCE)
    assert len(waypoints) == 2
    assert waypoints[0]["rostype"] == "GeoPoint"
    assert waypoints[0]["altitude"] == 0
    assert waypoints[1]["longitude"] > waypoints[0]["longitude"], "the vessel sails east"
    assert abs(waypoints[1]["latitude"] - waypoints[0]["latitude"]) < 1e-3  # UTM grid north is not true north away from the central meridian


def test_mission_starts_at_the_first_state_above_ninety_percent_of_max_speed():
    trajectories = straight_trajectories(speed=8.0, timespan=50)
    vessel = trajectories.initial_scene.os
    from_start = replay_mission_waypoints(trajectories, vessel, 8.0, GEOFENCE)
    assert from_start[0]["longitude"] == GEOFENCE.to_lat_long(trajectories.initial_scene.os_state.p)[1]
    # With a max speed above the vessel's speed no state qualifies, and the mission starts at the first state.
    unreachable = replay_mission_waypoints(trajectories, vessel, 100.0, GEOFENCE)
    assert unreachable[0] == from_start[0]
