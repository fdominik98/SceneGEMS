from typing import Dict, List

import numpy as np

from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.relation import Relation
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.scene_builder import SceneBuilder
from logical_level.models.actor_variable import ActorVariable
from utils.global_constants import ONE_N_MILE_IN_M
from utils.math_utils import rotate_heading


class RiskVector:
    def __init__(self, scene: ConcreteScene) -> None:
        self.proximity_vectors: Dict[Relation, ProximityVector] = {r: ProximityVector(scene, r.actor1, r.actor2) for r in scene.os_ts_pairs}
        self.danger_sectors: Dict[ConcreteVessel, float] = {vessel: NavigationRiskIndex(scene, vessel).find_danger_sector() for vessel in [scene.os]}

        self.max_proximity_index = min(self.proximity_vectors.values(), key=lambda obj: obj.tcpa)
        # self.safe_navigation_area_index = self.nav_risk_vector.find_safe_navigation_area_index()
        self.danger_sector = self.danger_sectors[scene.os]

        self.min_dcpa = self.max_proximity_index.dcpa
        self.min_tcpa = self.max_proximity_index.tcpa
        self.max_proximity_index = self.max_proximity_index.proximity_index

        # self.distance = (pow(np.e, magnitude(self.risk_vector) / np.sqrt(3)) - 1) / (np.e - 1)


class ProximityVector:
    def __init__(
        self,
        scene: ConcreteScene,
        actor1: ConcreteActor,
        actor2: ConcreteActor,
    ) -> None:
        self.props = scene.get_geo_props(actor1, actor2)
        self.dist = self.props.o_distance
        self.tcpa = self.props.tcpa
        self.dcpa = self.props.dcpa

        dr = 1 * ONE_N_MILE_IN_M
        ts = 10 * 60

        if self.tcpa < 0 or self.tcpa > ts:
            self.dcpa_norm = 0
            self.tcpa_norm = 0
        else:
            if self.dcpa < self.props.safety_dist:
                self.dcpa_norm = 1
            else:
                # self.dcpa_norm = (pow(np.e, (dr - self.dcpa) / (dr - relation.safety_dist)) - 1) / (np.e - 1)
                self.dcpa_norm = (pow(np.e, (dr - self.dcpa) / (dr - self.props.safety_dist)) - 1) / (np.e - 1)
            # self.tcpa_norm = (pow(np.e, (ts - self.tcpa) / ts) - 1) / (np.e - 1)
            self.tcpa_norm = (pow(np.e, (ts - self.tcpa) / ts) - 1) / (np.e - 1)
        if self.dcpa_norm * self.tcpa_norm > 0:
            self.proximity_index = np.sqrt(self.dcpa_norm * self.tcpa_norm)
        else:
            self.proximity_index = 0


class NavigationRiskIndex:
    def __init__(self, scene: ConcreteScene, vessel: ConcreteVessel) -> None:
        self.scene = scene
        self.initial_state = self.scene[vessel]
        self.vessel = vessel
        self.variable: ActorVariable = self.vessel.logical_variable

    def find_danger_sector(self) -> float:
        
        def rotate_heading_get_new_scene(i) -> ConcreteScene:
            scene_builder = SceneBuilder(self.scene)
            state = self.initial_state.modify_copy(heading=rotate_heading(self.initial_state.heading, np.radians(i)))
            scene_builder.set_state(self.vessel, state)
            return scene_builder.build()
        
        for i in range(91):
            new_scene = rotate_heading_get_new_scene(i)
            if not new_scene.may_collide_anyone(self.vessel):
                break
        for j in range(91):
            new_scene = rotate_heading_get_new_scene(j)
            if not new_scene.may_collide_anyone(self.vessel):
                break
        return pow((i + j) / 180, 0.33)

    def find_safe_navigation_area_index(self) -> float:
        collides = 0
        no_collides = 0
        partitions = 50

        speeds = [i * (self.variable.max_speed / partitions) for i in range(1, partitions + 1)]
        for speed in speeds:
            for i in range(0, 180):
                for direction in [-1, 1]:  # -1 for counterclockwise, 1 for clockwise
                    new_state = self.initial_state.modify_copy(
                        heading=rotate_heading(self.initial_state.heading, direction * np.radians(i)),
                        speed=speed,
                    )
                    new_scene = SceneBuilder(self.scene).set_state(self.vessel, new_state).build()
                    if new_scene.may_collide_anyone(self.vessel):
                        collides += 1
                    else:
                        no_collides += 1
        return (pow(np.e, collides / (collides + no_collides)) - 1) / (np.e - 1)


class TrajectoryRiskEvaluator:
    def __init__(self, trajectories: Trajectories) -> None:
        self.trajectories = trajectories
        self.risk_vectors: List[RiskVector] = []
        last_vector = RiskVector(trajectories.initial_scene)
        for t in range(self.trajectories.timespan):
            if t % 15 == 0:
                scenario = self.trajectories.get_scene_by_time(t)
                last_vector = RiskVector(scenario)
            self.risk_vectors.append(last_vector)
