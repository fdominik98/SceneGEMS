
import numpy as np

param allowCollisions = True

class GenObject(Object):
    is_actor : False
    allowCollisions : True

class Actor(GenObject):
    id : int
    length : 1
    is_vessel : False
    is_actor : True

class Obstacle(Actor):
    area_radius : float

class Vessel(Actor):
    is_vessel : True
    is_os : False

class OwnShip(Vessel):
    is_os : True


def create_scenario(os_id, ts_ids, obst_ids, length_map, radius_map, speed_boundary_map, possible_distances_map, min_distance_map, vis_distance_map, bearing_map, drift_threshold_map):
    max_ts_visibility_dist = SIX_NAUTICAL_MILES

    os_radius = radius_map[os_id]
    os_length = length_map[os_id]
    os_min_speed = speed_boundary_map[os_id][0]
    os_max_speed = speed_boundary_map[os_id][1]
    ego = new OwnShip with id os_id, with length os_length, at (0, 0), with velocity (0, Range(os_min_speed, os_max_speed)), facing toward (0, MAX_COORD)

    def add_ts(ts_id, existing_ts_states = []):
        ts_length = length_map[ts_id]
        ts_radius = radius_map[ts_id]
        ts_min_speed = speed_boundary_map[ts_id][0]
        ts_max_speed = speed_boundary_map[ts_id][1]
        heading_ego_to_ts, bearing_angle_ego_to_ts, heading_ts_to_ego, bearing_angle_ts_to_ego = bearing_map.get((os_id, ts_id), (0, 2*np.pi, 0, 2*np.pi))

        visibility_dist = vis_distance_map.get((os_id, ts_id), None)

        d_thrs = drift_threshold_map.get((os_id, ts_id), 0.0)

        if visibility_dist is not None:
            distance_region = CircularRegion(ego.position, visibility_dist + d_thrs - EPSILON).difference(CircularRegion(ego.position, visibility_dist - d_thrs + EPSILON))
            min_distance = visibility_dist
        else:
            dist1 = possible_distances_map[(os_id, ts_id)][0]
            dist2 = possible_distances_map[(os_id, ts_id)][1]
            dist3 = possible_distances_map[(os_id, ts_id)][2]
            dist4 = possible_distances_map[(os_id, ts_id)][3]

            region_1 = CircularRegion(ego.position, dist1 + d_thrs - EPSILON).difference(CircularRegion(ego.position, dist1 - d_thrs + EPSILON))
            region_2 = CircularRegion(ego.position, dist2 + d_thrs - EPSILON).difference(CircularRegion(ego.position, dist2 - d_thrs + EPSILON))
            region_3 = CircularRegion(ego.position, dist3 + d_thrs - EPSILON).difference(CircularRegion(ego.position, dist3 - d_thrs + EPSILON))
            region_4 = CircularRegion(ego.position, dist4 + d_thrs - EPSILON).difference(CircularRegion(ego.position, dist4 - d_thrs + EPSILON))

            distance_region = region_1.union(region_2).union(region_3).union(region_4)
            min_distance = min_distance_map[(os_id, ts_id)]


        bearing_region_ego_to_ts = SectorRegion(ego.position, MAX_DISTANCE*3, heading_ego_to_ts + ego.heading, bearing_angle_ego_to_ts - EPSILON)

        ts_point_region = distance_region.intersect(bearing_region_ego_to_ts)


        # for ts_state in existing_ts_states:
        #     ts_point_region = ts_point_region.difference(CircularRegion(ts_state.position, ts_state.length + GlobalConfig.EPSILON))

        ts_point = new Point in ts_point_region

        speed_region = CircularRegion(ts_point.position, ts_max_speed).difference(CircularRegion(ts_point.position, ts_min_speed))
        p21 = new GenObject facing toward ego.position - ts_point.position
        bearing_region_ts_to_ego = SectorRegion(ts_point.position, MAX_DISTANCE*3, heading_ts_to_ego + p21.heading, bearing_angle_ts_to_ego - EPSILON)

        sin_half_cone_theta = np.clip(max(ts_radius, os_radius) / min_distance, -1, 1)
        angle_half_cone = abs(np.arcsin(sin_half_cone_theta))
        voc_region = SectorRegion(ts_point.position + ego.velocity, MAX_DISTANCE*3, p21.heading, 2 * angle_half_cone)

        ts_velocity_region = speed_region.intersect(voc_region).intersect(bearing_region_ts_to_ego)

        for ts_state in existing_ts_states:
            other_ts_radius = radius_map[ts_state.id]
            ts_p21 = new GenObject facing toward ts_state.position - ts_point.position
            ts_sin_half_cone_theta = np.clip(max(ts_radius, other_ts_radius) / max_ts_visibility_dist, -1, 1)
            ts_angle_half_cone = abs(np.arcsin(ts_sin_half_cone_theta))
            ts_voc_region = SectorRegion(ts_point.position + ts_state.velocity, max_ts_visibility_dist, ts_p21.heading, 2 * ts_angle_half_cone)
            ts_velocity_region = ts_velocity_region.difference(ts_voc_region)

        velocity_point = new Point in ts_velocity_region
        ts = new Vessel with id ts_id, at ts_point.position, with velocity velocity_point.position-ts_point.position, with length ts_length
        return ts


    def add_obst(obst_id, existing_ts_states = [], existing_obst_states = []):
        visibility_dist = vis_distance_map[(os_id, obst_id)]
        obst_radius = radius_map[obst_id]
        d_thrs = drift_threshold_map.get((os_id, obst_id), 0.0)
        heading_ego_to_obst, bearing_angle_ego_to_obst, heading_obst_to_ego, bearing_angle_obst_to_ego = bearing_map.get((os_id, obst_id), (0, 2*np.pi, 0, 2*np.pi))

        distance_region = CircularRegion(ego.position, visibility_dist + d_thrs - EPSILON).difference(CircularRegion(ego.position, visibility_dist - d_thrs + EPSILON))
        distance = visibility_dist

        bearing_region_ego_to_obst = SectorRegion(ego.position, MAX_DISTANCE*3, heading_ego_to_obst + ego.heading, bearing_angle_ego_to_obst - EPSILON)

        sin_half_cone_theta = np.clip(max(obst_radius, os_radius) / distance, -1, 1)
        angle_half_cone = abs(np.arcsin(sin_half_cone_theta))
        voc_region = SectorRegion(ego.position, MAX_DISTANCE*3, ego.heading, 2 * angle_half_cone)

        obst_point_region = distance_region.intersect(bearing_region_ego_to_obst).intersect(voc_region)

        for ts_state in existing_ts_states:
            other_ts_radius = radius_map[ts_state.id]
            ts_sin_half_cone_theta = np.clip(max(obst_radius, other_ts_radius) / max_ts_visibility_dist, -1, 1)
            ts_angle_half_cone = abs(np.arcsin(ts_sin_half_cone_theta))
            obst_pos_region = SectorRegion(ts_state.position, max_ts_visibility_dist, ts_state.heading, 2 * ts_angle_half_cone)
            obst_point_region = obst_point_region.difference(obst_pos_region)

        for obst_state in existing_obst_states:
            other_obst_radius = radius_map[obst_state.id]
            obst_pos_region = CircularRegion(obst_state.position, max(obst_radius, other_obst_radius))
            obst_point_region = obst_point_region.difference(obst_pos_region)


        obst_point = new Point in obst_point_region

        obst = new Obstacle with id obst_id, at obst_point.position, with area_radius obst_radius
        return obst

    ts_states = []
    obst_states = []
    for ts_id in ts_ids:
        ts_states.append(add_ts(ts_id, ts_states))
    for obst_id in obst_ids:
        obst_states.append(add_obst(obst_id, ts_states, obst_states))
    return ts_states, obst_states
