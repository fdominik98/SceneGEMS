"""A fake of the runner's gz-transport actuator link (GzLockstepLink) for the gz lockstep runner tests: each model's hull is the surge-yaw model."""

import math
from typing import Dict, Tuple

from scenegems_tool.vessel_stack.control_layers.custom.hull_surge_yaw_model import HullState, HullSurgeYawModel
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_link import GzStepResult, HullOdometry


def odometry(state: HullState) -> HullOdometry:
    return HullOdometry(state.x, state.y, -0.1, 0.0, 0.0, math.sin(state.heading / 2), math.cos(state.heading / 2), state.surge, state.sway, 0.0, 0.0, 0.0, state.yaw_rate)


class FakeHullLink:
    """Stands in for GzLockstepLink: each model is a HullSurgeYawModel, stepped step_ns per iteration with the thrust held over the step."""

    def __init__(self, hulls: Dict[str, Tuple[HullSurgeYawModel, HullState]], late_steps=()):
        self.models = {name: model for name, (model, _) in hulls.items()}
        self.states = {name: state for name, (_, state) in hulls.items()}
        self.late_steps = set(late_steps)  # step numbers (from 1) whose port thrusters report late
        self.started = None
        self.steps = 0
        self.sim_time_ns = 0
        self.step_ns = 0
        self.closed = False

    def connect(self, timeout_s: float) -> None:
        del timeout_s

    def close(self) -> None:
        self.closed = True

    def start(self, thrusters, step_ns, settle_iterations) -> GzStepResult:
        self.started = ({name: dict(values) for name, values in thrusters.items()}, step_ns, settle_iterations)
        self.step_ns = step_ns
        return self._iterate(settle_iterations, {name: (0.0, 0.0) for name in self.states}, ())

    def step(self, iterations, thrust) -> GzStepResult:
        self.steps += 1
        late = tuple(f"{name}/port" for name in sorted(thrust)) if self.steps in self.late_steps else ()
        return self._iterate(iterations, thrust, late)

    def _iterate(self, iterations, thrust, late) -> GzStepResult:
        for _ in range(iterations):
            for name, model in self.models.items():
                self.states[name] = model.step(self.states[name], *thrust[name], self.step_ns / 1e9)
        self.sim_time_ns += iterations * self.step_ns
        return GzStepResult(self.sim_time_ns, {name: odometry(state) for name, state in self.states.items()}, late)


def hull_link(trajectories, environment) -> FakeHullLink:
    """A FakeHullLink with every vessel of the trajectories as model vessel_<id>, at rest at its initial pose, its hull from its generated dynamics."""
    from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_runner import hull_dynamics

    scene = trajectories.initial_scene
    hulls = {}
    for vessel in scene.vessels:
        initial = scene[vessel]
        hulls[f"vessel_{vessel.id}"] = (HullSurgeYawModel(hull_dynamics(vessel, environment)), HullState(initial.x, initial.y, initial.heading, 0.0, 0.0, 0.0))
    return FakeHullLink(hulls)
