"""Configuration of the USV Navigation runtime and how SceneGEMS derives it from a scenario.

Kept apart from the participant so callers can build parameters without importing
colav_automaton.
"""

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

import numpy as np

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel
from utils.colregs_approximations import vis_distance

# Upstream's validated geometric prescribed time (behaviour regression suite and CommonOcean
# batch, dt 1 s). It sizes dsafe = Cs + v * tp and the arrival radius at the virtual waypoint.
DEFAULT_PRESCRIBED_TIME_S = 3.0
# Upstream CommonOcean default for the control horizon, in steps.
DEFAULT_CONTROL_HORIZON_STEPS = 60
# Upstream's DCPA bounds of the risk index. They do not grow with Cs: at long range a target
# above the upper bound stays under the risk threshold, so a large vessel with a safety radius
# beyond it (a hull of about 232 m) would enter the domain without ever starting to avoid.
UPSTREAM_DCPA_BETA1_M = 463.0
UPSTREAM_DCPA_BETA2_M = 926.0
# The same bounds in safety radii, used where they exceed upstream's: full risk up to the
# 1.25 Cs upstream places the virtual waypoint at, the upper bound at twice that as upstream has it.
DCPA_BETA1_RADII = 1.25
DCPA_BETA2_RADII = 2.5


@dataclass(frozen=True)
class UsvNavigationParameters:
    """Arguments of one SyncColavRuntime. Use from_reference for the SceneGEMS defaults."""

    goal: Tuple[float, float]  # waypoint [m, local frame]
    speed: float  # v [m/s]: the runtime's fixed speed, also the commanded speed
    safety_radius: float  # Cs [m]: the radius the runtime steers around every obstacle; a target's motion can still bring it closer
    control_horizon: float  # tp_control [s]: horizon of the prescribed-time heading law, not a look-ahead
    prescribed_time: float = DEFAULT_PRESCRIBED_TIME_S  # tp [s]
    # How far the navigator looks [m]: targets beyond it are not passed to the runtime, and it replaces the runtime's dsafe.
    # None passes every target and keeps upstream's dsafe.
    horizon: Optional[float] = None
    # Further SyncColavRuntime keyword arguments (a, eta, K, K_off, v1_buffer, ...); upstream defaults when absent.
    runtime_options: Tuple[Tuple[str, float], ...] = ()

    @classmethod
    def from_reference(cls, vessel: ConcreteVessel, reference_states: Sequence[ActorState], actors: Iterable[ConcreteActor], dt: float) -> "UsvNavigationParameters":
        """SceneGEMS defaults for a vessel with a generated trajectory.

        - goal: the end of the generated trajectory, so the run heads where the scenario
          generator sent the vessel.
        - speed: the reference speed at t = 0 (the mean reference speed when that is zero),
          capped at the vessel's max speed. The runtime assumes the vessel keeps it.
        - safety_radius: the largest safety radius in the scene, own ship included, since
          SceneGEMS counts a domain violation when a vessel enters either vessel's safety
          radius, and the runtime takes one Cs for all obstacles.
        - control_horizon: the longest of 60 steps (upstream default), tp, and one full turn
          at the vessel's max yaw rate. The prescribed-time feedback switches off
          control_horizon seconds after each transition, so the vessel must be able to turn
          through half a circle well before that.
        - horizon: the largest visibility distance between the vessel and another actor, seen
          from neither one's stern. One value per run, so it does not follow the bearing as the
          monitor's visibility does. None when the vessel is alone.
        - dcpa_beta1, dcpa_beta2: upstream's, or 1.25 and 2.5 safety radii where those are larger.
        - prescribed_time and every other runtime argument: upstream defaults.
        """
        actors = list(actors)
        if not reference_states:
            raise ValueError(f"Vessel {vessel.id} has an empty reference trajectory")
        speed = float(reference_states[0].speed)
        if speed <= 0:
            speed = float(np.mean([state.speed for state in reference_states]))
        speed = min(speed, vessel.max_speed)
        if speed <= 0:
            raise ValueError(f"Vessel {vessel.id} has no positive reference speed, which USV Navigation needs")
        end = reference_states[-1]
        full_turn_s = 2 * math.pi / vessel.max_angular_speed if vessel.max_angular_speed > 0 else 0.0
        safety_radius = max(float(actor.safety_radius) for actor in actors)
        return cls(
            goal=(float(end.x), float(end.y)),
            speed=speed,
            safety_radius=safety_radius,
            control_horizon=max(DEFAULT_CONTROL_HORIZON_STEPS * dt, DEFAULT_PRESCRIBED_TIME_S, full_turn_s),
            horizon=max((vis_distance(False, vessel.length, False, actor.length) for actor in actors if actor.id != vessel.id), default=None),
            runtime_options=(
                ("dcpa_beta1", max(UPSTREAM_DCPA_BETA1_M, DCPA_BETA1_RADII * safety_radius)),
                ("dcpa_beta2", max(UPSTREAM_DCPA_BETA2_M, DCPA_BETA2_RADII * safety_radius)),
            ),
        )

    def runtime_kwargs(self) -> Dict[str, float]:
        return {"Cs": self.safety_radius, "v": self.speed, "tp": self.prescribed_time, "tp_control": self.control_horizon, **dict(self.runtime_options)}

    def as_dict(self) -> Dict[str, Any]:
        horizon = {} if self.horizon is None else {"horizon": self.horizon}
        return {"goal": list(self.goal), **self.runtime_kwargs(), **horizon}
