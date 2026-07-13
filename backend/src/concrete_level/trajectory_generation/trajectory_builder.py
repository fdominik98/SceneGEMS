from typing import Dict, List

import numpy as np
from scipy.interpolate import interp1d

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel
from concrete_level.models.concrete_scene import ConcreteScene
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.scene_builder import SceneBuilder
from utils.global_constants import ONE_HOUR_IN_SEC, ONE_SECOND
from utils.math_utils import compute_start_point, distance


class TrajectoryBuilder:
    def __init__(
        self,
        time_step: int,
        scene_list: List[ConcreteScene] = [],
    ):
        self.scene_list = scene_list.copy()
        self.time_step = time_step

    def add_scene_as_dict(self, scene_dict: Dict[ConcreteActor, ActorState]):
        builder = SceneBuilder()
        builder.set_states_as_dict(scene_dict)
        return self.add_scene(builder.build())

    def add_scene(self, scene: ConcreteScene) -> "TrajectoryBuilder":
        self.scene_list.append(scene)
        return self

    def build(self) -> Trajectories:
        return Trajectories(self.scene_list, self.time_step)

    @staticmethod
    def default_trajectory_from_scene(scene: ConcreteScene, time_step: int, timespan: int) -> Trajectories:
        return TrajectoryBuilder.default_builder_from_scene(scene, time_step, timespan).build()

    @staticmethod
    def default_builder_from_scene(scene: ConcreteScene, time_step: int, timespan: int) -> "TrajectoryBuilder":
        return TrajectoryBuilder(time_step).add_scene(scene).simulate_to_timespan(timespan)

    @staticmethod
    def from_trajectories(Trajectories: Trajectories) -> "TrajectoryBuilder":
        return TrajectoryBuilder(Trajectories.time_step, Trajectories.scene_list)

    def merge(self, trajectories: Trajectories) -> "TrajectoryBuilder":
        new_scene_list: List[ConcreteScene] = []
        if self.time_step != trajectories.time_step:
            raise ValueError("The time steps of the trajectories must be the same")
        if len(self.scene_list) != len(trajectories.scene_list):
            raise ValueError("The number of scenes must be the same")
        for scene, other_scene in zip(self.scene_list, trajectories.scene_list):
            builder = SceneBuilder(scene)
            builder.merge(other_scene)
            new_scene_list.append(builder.build())
        self.scene_list = new_scene_list
        return self

    def remove_vessel(self, vessel: ConcreteVessel) -> "TrajectoryBuilder":
        new_scene_list: List[ConcreteScene] = []
        for scene in self.scene_list:
            builder = SceneBuilder(scene)
            builder.remove_vessel(vessel)
            new_scene_list.append(builder.build())
        self.scene_list = new_scene_list
        return self

    @staticmethod
    def default_trajectory_from_vessel(vessel: ConcreteVessel, state: ActorState, time_step: int, timespan: int) -> Trajectories:
        return TrajectoryBuilder(time_step).simulate_to_timespan(timespan).simulate_and_add_vessel(vessel, state).build()

    def add_vessel(self, actor: ConcreteActor, states: List[ActorState]) -> "TrajectoryBuilder":
        for i, state in enumerate(states):
            if i >= len(self.scene_list):
                self.scene_list.append(ConcreteScene({actor: state}))
            else:
                scene_builder = SceneBuilder(self.scene_list[i])
                self.scene_list[i] = scene_builder.set_state(actor, state).build()
        return self

    @staticmethod
    def trajectory_from_actor_state_dict(state_dict: Dict[ConcreteActor, List[ActorState]], time_step: int) -> Trajectories:
        trajectory_builder = TrajectoryBuilder(time_step)
        for actor, states in state_dict.items():
            trajectory_builder.add_vessel(actor, states)
        return trajectory_builder.build()

    def simulate_and_add_vessel(self, vessel: ConcreteVessel, state: ActorState) -> "TrajectoryBuilder":
        new_scene_list: List[ConcreteScene] = []
        for scene in self.scene_list:
            new_scene_builder = SceneBuilder(scene)
            if len(new_scene_list) == 0:
                new_state = state
            else:
                last_state = new_scene_list[-1][vessel]
                new_state = vessel.simulate(last_state, (last_state.heading, last_state.speed), self.time_step)
            new_scene_builder.set_state(vessel, new_state)
            new_scene_list.append(new_scene_builder.build())
        self.scene_list = new_scene_list
        return self

    def simulate_to_length(self, length: int = 1) -> "TrajectoryBuilder":
        while len(self) < length:
            self.simulate_by_one()
        return self

    def simulate_by_one(self) -> "TrajectoryBuilder":
        if len(self.scene_list) == 0:
            return self.add_scene(SceneBuilder().build())
        last_scene = self.scene_list[-1]
        builder = SceneBuilder(last_scene)
        for actor in last_scene:
            if isinstance(actor, ConcreteVessel):
                state = last_scene[actor]
                builder.set_state(actor, actor.simulate(state, (state.heading, state.speed), self.time_step))
        return self.add_scene(builder.build())

    def simulate_to_timespan(self, timespan: int = ONE_HOUR_IN_SEC) -> "TrajectoryBuilder":
        while self.timespan < timespan:
            self.simulate_by_one()
        return self

    def shift_positions_to_zero(self) -> "TrajectoryBuilder":
        new_scene_list = []
        initial_scene = self.scene_list[0]
        os_state = initial_scene.os_state
        for scene in self.scene_list:
            builder = SceneBuilder(scene)
            for actor in builder:
                builder[actor] = scene[actor].modify_copy(x=scene[actor].x - os_state.x, y=scene[actor].y - os_state.y)
            new_scene_list.append(builder.build())
        self.scene_list = new_scene_list
        return self

    @property
    def timespan(self) -> int:
        return (len(self.scene_list) - 1) * self.time_step

    def __len__(self) -> int:
        return len(self.scene_list)

    def convert_to_one_second_step_with_interpolation(self, kind: str = "cubic") -> "TrajectoryBuilder":
        # use scene builder interpolate_to to create a new scene list
        if len(self.scene_list) <= 1 or self.time_step == ONE_SECOND:
            self.time_step = ONE_SECOND
            return self
        actor_state_dict: Dict[ConcreteActor, List[ActorState]] = {}
        trajectories = self.build()
        times = np.arange(0, len(trajectories) * self.time_step, self.time_step)
        for actor in trajectories.actors:
            states = trajectories.actor_states(actor)
            x_vals = [state.x for state in states]
            y_vals = [state.y for state in states]
            heading_vals = [state.heading for state in states]
            speed_vals = [state.speed for state in states]
            x_spline = interp1d(times, x_vals, kind=kind)
            y_spline = interp1d(times, y_vals, kind=kind)
            speed_spline = interp1d(times, speed_vals, kind=kind)
            # Interpolate sine and cosine separately
            heading_sin_spline = interp1d(times, np.sin(heading_vals), kind=kind)
            heading_cos_spline = interp1d(times, np.cos(heading_vals), kind=kind)

            new_times = np.arange(0, times[-1], 1.0)
            new_x_vals = x_spline(new_times)
            new_y_vals = y_spline(new_times)
            new_speed_vals = speed_spline(new_times)
            new_heading_vals = np.arctan2(heading_sin_spline(new_times), heading_cos_spline(new_times))
            new_states = [ActorState(x=x, y=y, speed=speed, heading=heading) for x, y, speed, heading in zip(new_x_vals, new_y_vals, new_speed_vals, new_heading_vals)]
            actor_state_dict[actor] = new_states

        new_trajectory = TrajectoryBuilder.trajectory_from_actor_state_dict(actor_state_dict, ONE_SECOND)
        self.scene_list = new_trajectory.scene_list
        self.time_step = ONE_SECOND
        return self

    def convert_to_time_step(self, time_step: int) -> "TrajectoryBuilder":
        if self.time_step == time_step:
            return self
        self.convert_to_one_second_step_with_interpolation()
        # get every time_step-th scene
        self.scene_list = self.scene_list[:: time_step // self.time_step]
        self.time_step = time_step
        return self

    def convert_to_max_scene_number(self, scene_number: int) -> "TrajectoryBuilder":
        time_step = max(ONE_SECOND, np.ceil(self.timespan / scene_number))
        return self.convert_to_time_step(int(time_step))

    def simulate_to_alignment(self) -> "TrajectoryBuilder":
        if len(self.scene_list) == 0:
            return self
        first_scene = self.scene_list[0]
        last_scene = self.scene_list[-1]
        scenes: list[SceneBuilder] = []
        for actor in last_scene:
            if actor not in first_scene:
                continue
            dist_from_first = distance(first_scene[actor].p, last_scene[actor].p)
            pseudo_target_state = actor.simulate_distance(first_scene[actor], dist_from_first + 2 * actor.safety_radius)
            trajectory = actor.simulate_to_state(last_scene[actor], pseudo_target_state, self.time_step)
            for i, state in enumerate(trajectory):
                if i >= len(scenes):
                    scenes.append(SceneBuilder(last_scene))
                scenes[i].set_state(actor, state)

        self.scene_list += [scene.build() for scene in scenes]
        return self

    def simulate_acceleration_from_zero(self) -> "TrajectoryBuilder":
        if not self.scene_list:
            return self

        new_trajectory_chunks: Dict[ConcreteActor, List[ActorState]] = {}
        initial_scene = self.scene_list[0]
        for actor, state in initial_scene.items():
            if isinstance(actor, ConcreteVessel):
                if state.speed < 1e-8:
                    new_trajectory_chunks[actor] = []
                    continue
                vessel_start_pos = compute_start_point(state.p, state.v, state.speed, actor.max_acceleration)
                start_state = ActorState(x=vessel_start_pos[0], y=vessel_start_pos[1], speed=0.0, heading=state.heading)
                new_trajectory_chunk = actor.simulate_to_state(start_state, state, self.time_step)
                new_trajectory_chunks[actor] = new_trajectory_chunk[:-1] if len(new_trajectory_chunk) > 1 else []
            else:
                new_trajectory_chunks[actor] = []

        max_length = max((len(chunk) for chunk in new_trajectory_chunks.values()), default=0)
        if max_length == 0:
            return self

        for actor, chunk in new_trajectory_chunks.items():
            pad_state = initial_scene[actor]
            if isinstance(actor, ConcreteVessel):
                pad_state = ActorState.modify_copy(pad_state, speed=0.0)
            if len(chunk) == 0:
                new_chunk = [pad_state] * max_length
            else:
                new_chunk = ([chunk[0]] * (max_length - len(chunk))) + chunk
            new_trajectory_chunks[actor] = new_chunk
        new_scene_list = []
        for i in range(max_length):
            new_scene_list.append(ConcreteScene({actor: chunk[i] for actor, chunk in new_trajectory_chunks.items()}))
        self.scene_list = new_scene_list + self.scene_list
        return self
