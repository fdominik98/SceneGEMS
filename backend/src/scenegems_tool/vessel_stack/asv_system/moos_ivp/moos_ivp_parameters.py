"""Configuration of the MOOS-IvP helm of one vessel and how SceneGEMS derives it from a scenario.

The parameters are what the helm's two behaviours are written from (moos_ivp_server.py): the
waypoint behaviour that takes the vessel to its goal, and the collision avoidance behaviour the
helm spawns once per contact.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

import numpy as np

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel
from utils.colregs_approximations import vis_distance, vis_distance_with_obstacle

AVOIDANCE_COLREGS = "colregs"  # BHV_AvdColregsV22: the give-way and stand-on modes of rules 13 to 17
AVOIDANCE_CPA = "cpa"  # BHV_AvoidCollision: keeps the closest point of approach, with no rule
AVOIDANCE_BEHAVIOURS = (AVOIDANCE_COLREGS, AVOIDANCE_CPA)

# A closest point of approach at this many safety radii or more is as good as any: the avoidance behaviour asks for no more room.
MAX_UTILITY_CPA_RADII = 2.0
# The avoidance behaviour of a contact ends once the contact is this many times its outer distance away.
COMPLETED_DISTANCE_FACTOR = 1.1
# The goal counts as reached within this many vessel lengths, and never within less than the vessel sails in two steps.
CAPTURE_RADIUS_LENGTHS = 2.0


@dataclass(frozen=True)
class MoosIvpParameters:
    """The helm configuration of one vessel. Use from_reference for the SceneGEMS defaults."""

    goal: Tuple[float, float]  # the waypoint [m, local frame]
    speed: float  # transit speed of the waypoint behaviour [m/s]
    max_speed: float  # upper end of the speed the helm may decide [m/s]
    min_util_cpa_dist: float  # [m] a closest point of approach at this distance or less has no utility: the helm avoids it
    max_util_cpa_dist: float  # [m] a closest point of approach at this distance or more has full utility
    pwt_outer_dist: float  # [m] the avoidance behaviour has no say beyond this range to its contact
    pwt_inner_dist: float  # [m] and its full priority weight within this range
    completed_dist: float  # [m] a contact is given an avoidance behaviour within this range, and the behaviour ends beyond 1.1 times it
    capture_radius: float  # [m] the goal is reached within this distance
    avoidance: str = AVOIDANCE_COLREGS
    # Further parameter lines of the avoidance behaviour (pwt_grade, giveway_bow_dist, ...); upstream defaults when absent.
    behaviour_options: Tuple[Tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.avoidance not in AVOIDANCE_BEHAVIOURS:
            raise ValueError(f"avoidance must be one of {', '.join(AVOIDANCE_BEHAVIOURS)}, not {self.avoidance!r}")
        if not 0 < self.speed <= self.max_speed:
            raise ValueError(f"speed must be positive and at most max_speed {self.max_speed}, not {self.speed}")
        if not 0 <= self.min_util_cpa_dist <= self.max_util_cpa_dist:
            raise ValueError("min_util_cpa_dist must not exceed max_util_cpa_dist")
        if not 0 < self.pwt_inner_dist <= self.pwt_outer_dist <= self.completed_dist:
            raise ValueError("the distances must be ordered: pwt_inner_dist <= pwt_outer_dist <= completed_dist")
        if self.capture_radius <= 0:
            raise ValueError("capture_radius must be positive")

    @classmethod
    def from_reference(cls, vessel: ConcreteVessel, reference_states: Sequence[ActorState], actors: Iterable[ConcreteActor], dt: float) -> "MoosIvpParameters":
        """SceneGEMS defaults for a vessel with a generated trajectory.

        They follow the requirement set for USV Navigation: the horizon is the visibility
        distance, the safety radius is the vessels' safety domain, and neither domain may be
        entered.

        - goal: the end of the generated trajectory.
        - speed: the reference speed at t = 0 (the mean reference speed when that is zero),
          capped at the vessel's max speed. max_speed is the vessel's.
        - min_util_cpa_dist: the largest safety radius in the scene, own ship included, since
          SceneGEMS counts a domain violation when a vessel enters either vessel's safety radius.
        - max_util_cpa_dist: twice that.
        - pwt_outer_dist: the largest visibility distance between the vessel and another actor,
          seen from neither one's stern, as USV Navigation's horizon; never less than twice
          max_util_cpa_dist, so the behaviour has room to act, which is also its value for a
          vessel alone.
        - pwt_inner_dist: half of pwt_outer_dist, never less than max_util_cpa_dist.
        - completed_dist: 1.1 times pwt_outer_dist.
        - capture_radius: two vessel lengths, never less than the distance of two steps at speed.
        - avoidance: the COLREGS behaviour, with upstream's other parameters.
        """
        actors = list(actors)
        if not reference_states:
            raise ValueError(f"Vessel {vessel.id} has an empty reference trajectory")
        speed = float(reference_states[0].speed)
        if speed <= 0:
            speed = float(np.mean([state.speed for state in reference_states]))
        speed = min(speed, float(vessel.max_speed))
        if speed <= 0:
            raise ValueError(f"Vessel {vessel.id} has no positive reference speed, which MOOS-IvP's waypoint behaviour needs")
        end = reference_states[-1]
        safety_radius = max(float(actor.safety_radius) for actor in actors)
        max_utility = MAX_UTILITY_CPA_RADII * safety_radius
        visibility = max(((vis_distance if actor.is_vessel else vis_distance_with_obstacle)(False, vessel.length, False, actor.length) for actor in actors if actor.id != vessel.id), default=0.0)
        outer = max(float(visibility), 2.0 * max_utility)
        return cls(
            goal=(float(end.x), float(end.y)),
            speed=speed,
            max_speed=float(vessel.max_speed),
            min_util_cpa_dist=safety_radius,
            max_util_cpa_dist=max_utility,
            pwt_outer_dist=outer,
            pwt_inner_dist=max(max_utility, 0.5 * outer),
            completed_dist=COMPLETED_DISTANCE_FACTOR * outer,
            capture_radius=max(CAPTURE_RADIUS_LENGTHS * float(vessel.length), 2.0 * speed * dt),
        )

    def as_dict(self) -> Dict[str, Any]:
        """The parameters as the run record and the helm's start config hold them."""
        return {
            "goal": list(self.goal),
            "speed": self.speed,
            "max_speed": self.max_speed,
            "avoidance": self.avoidance,
            "min_util_cpa_dist": self.min_util_cpa_dist,
            "max_util_cpa_dist": self.max_util_cpa_dist,
            "pwt_outer_dist": self.pwt_outer_dist,
            "pwt_inner_dist": self.pwt_inner_dist,
            "completed_dist": self.completed_dist,
            "capture_radius": self.capture_radius,
            "behaviour_options": [list(option) for option in self.behaviour_options],
        }


def parameters_for(vessel: ConcreteVessel, trajectories: Any, dt: float, given: Optional[Mapping[int, MoosIvpParameters]] = None) -> MoosIvpParameters:
    """The parameters of a vessel's run: the ones the caller gave for it, else the SceneGEMS defaults from its generated trajectory."""
    chosen = (given or {}).get(vessel.id)
    return chosen or MoosIvpParameters.from_reference(vessel, trajectories.state_list(vessel), trajectories.initial_scene.actors, dt)
