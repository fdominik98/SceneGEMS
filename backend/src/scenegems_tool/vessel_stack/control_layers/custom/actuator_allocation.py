"""Actuator allocation of the custom autopilot: the wanted surge force and yaw moment as thrusts and a helm angle.

One allocator per steering type of the generated hull (simulation_layers/gazebo/generators/
vessel_dynamics.py). Forces are in the body frame, x forward and y to port. A positive yaw
moment turns the vessel counterclockwise seen from above, to port. A positive helm angle turns
it to starboard: the helm's side force acts at steering_x, aft of midship, so the moment is
steering_x times the side force and a turn to port needs a negative helm angle.

Yaw has priority in every allocator: the turn gets what it needs first and the surge force what
is left. Each command says the force and moment it gives, which is how the autopilot knows when
to hold an integrator (anti-windup).

- skid: two thrusters side by side. Their difference gives the moment, their sum the force.
- rudder: one thruster and a rudder. The thrust is the surge force. The helm angle comes from
  the rudder's side force Y = K q sin(a) cos(a)^2, with K one half rho times the rudder's area
  times its lift slope, q the speed of the flow at the rudder squared and a the blade's angle of
  attack, which on a straight course is the helm angle. Below the speed floor the rudder has
  next to no force and the inversion would divide by zero: the flow is then taken as straight
  ahead at the floor speed, so the helm goes hard over for a moment that the rudder cannot
  give and the command reports the yaw as saturated.
- vectored_thrust: one thruster that turns with the helm, (X, Y) = T (cos d, sin d). When the
  helm's limit binds, the thrust is what the side force needs, so the vessel gets more surge
  force than wanted. Braking (a negative surge force): reversed thrust pushes the stern the
  other way, so the helm gives the wanted side force from the mirrored angle, and going astern
  or back ahead in a turn sends the helm across while the thrust pushes the wrong way. So the
  thruster goes astern only when the wanted force points astern within REVERSE_ENTRY_SHARE of
  the helm's limit, where the helm has little to travel, and it then stays astern while the
  mirrored angle is within the helm's limit. A turn that needs more side force than that
  keeps the thrust ahead with the helm hard over: the vessel does not brake until the turn eases.
  The helm takes time to cross from one side to the other, and the thrust it carries would
  meanwhile turn the vessel the wrong way: wait_for_helm holds the thrust back until the helm
  is nearly across (the autopilot follows the helm with helm_travel, as the model moves it).
"""

import math
from dataclasses import dataclass
from typing import Optional, Tuple

# Angle of attack at which sin(a) cos(a)^2 peaks (tan(a)^2 = 1/2): beyond it a rudder gives less side force, not more.
RUDDER_PEAK_ANGLE = math.atan(math.sqrt(0.5))
_RUDDER_PEAK_FORCE = 2.0 / (3.0 * math.sqrt(3.0))  # sin(a) cos(a)^2 at the peak
# A vectored thruster goes astern when the wanted force points astern within this share of the helm's limit.
REVERSE_ENTRY_SHARE = 1.0 / 3.0
# A vectored thruster's thrust is held back while the helm is farther than this share of its limit on the wrong side.
HELM_CROSSING_SHARE = 1.0 / 12.0


@dataclass(frozen=True)
class ActuatorCommand:
    thrusts: Tuple[float, ...]  # N, in the order of the model's thrusters (generators/vessel_model_generator.thruster_names)
    helm_angle: Optional[float]  # rad, positive turns to starboard; None for a skid steered hull, which has no helm
    force: float  # N, the surge force the command gives: the wanted one unless surge_saturated
    moment: float  # N m, the yaw moment the command gives: the wanted one unless yaw_saturated
    yaw_saturated: bool
    surge_saturated: bool


def _limited(value: float, limit: float) -> float:
    return min(max(value, -limit), limit)


def allocate_skid(force: float, moment: float, *, max_thrust: float, thruster_arm: float) -> ActuatorCommand:
    """Port and starboard thrust: the differential is limited first and the common thrust gets what is left."""
    differential = moment / thruster_arm  # starboard minus port
    differential_limit = 2.0 * max_thrust
    yaw_saturated = abs(differential) > differential_limit
    differential = _limited(differential, differential_limit)
    common_limit = differential_limit - abs(differential)
    surge_saturated = abs(force) > common_limit
    common = _limited(force, common_limit)
    return ActuatorCommand(
        thrusts=((common - differential) / 2.0, (common + differential) / 2.0),
        helm_angle=None,
        force=common if surge_saturated else force,
        moment=thruster_arm * differential if yaw_saturated else moment,
        yaw_saturated=yaw_saturated,
        surge_saturated=surge_saturated,
    )


def rudder_attack_angle(side_force_share: float) -> float:
    """The angle of attack a with sin(a) cos(a)^2 equal to the share, up to the peak either way.

    With x = sin(a) the equation is x^3 - x + share = 0, whose root between the peaks is
    x = 2/sqrt(3) sin(asin(3 sqrt(3)/2 share) / 3).
    """
    share = _limited(side_force_share, _RUDDER_PEAK_FORCE)
    triple = _limited(1.5 * math.sqrt(3.0) * share, 1.0)
    return math.asin(2.0 / math.sqrt(3.0) * math.sin(math.asin(triple) / 3.0))


def allocate_rudder(
    force: float,
    moment: float,
    surge: float,
    sway_at_rudder: float = 0.0,
    *,
    max_thrust: float,
    steering_x: float,
    max_angle: float,
    force_gain: float,
    speed_floor: float,
) -> ActuatorCommand:
    """Thrust from the surge force, helm angle from the yaw moment in the flow at the rudder.

    surge and sway_at_rudder are the rudder's own velocity through the water (the hull's sway
    plus steering_x times its yaw rate). The flow meets the blade at the drift angle
    atan(sway / surge), so the helm angle is the angle of attack for the side force plus that
    drift: on a straight course it inverts Y = K u|u| sin(d) cos(d)^2. Astern the side force
    changes sign with the flow. Within the speed floor the flow counts as straight ahead at the
    floor speed.
    """
    thrust = _limited(force, max_thrust)
    surge_saturated = abs(force) > max_thrust

    ahead = surge if abs(surge) >= speed_floor else speed_floor
    drift = math.atan(sway_at_rudder / ahead)
    dynamic_force = force_gain * math.copysign(ahead**2 + sway_at_rudder**2, ahead)  # N at sin(a) cos(a)^2 = 1
    share = moment / steering_x / dynamic_force
    attack = rudder_attack_angle(share)
    angle = _limited(attack + drift, max_angle)
    yaw_saturated = abs(share) > _RUDDER_PEAK_FORCE or angle != attack + drift
    given = moment
    if yaw_saturated:
        attack = angle - drift
        given = steering_x * dynamic_force * math.sin(attack) * abs(math.cos(attack)) * math.cos(angle)
    return ActuatorCommand(
        thrusts=(thrust,),
        helm_angle=angle,
        force=thrust if surge_saturated else force,
        moment=given,
        yaw_saturated=yaw_saturated,
        surge_saturated=surge_saturated,
    )


def allocate_vectored_thrust(force: float, moment: float, *, max_thrust: float, steering_x: float, max_angle: float, astern: bool = False) -> ActuatorCommand:
    """Thrust and helm angle of a thruster that turns with the helm, for the force (X, Y) with Y = moment / steering_x.

    astern: the thruster ran astern in the step before (the thrust of the last command was negative).
    """
    side = moment / steering_x
    # Braking: on reversed thrust the helm gives the side force from the mirrored angle. The thruster goes
    # astern when that angle is small, and stays astern while the angle is within the helm's limit.
    reach = math.tan(max_angle if astern else REVERSE_ENTRY_SHARE * max_angle)
    direction = -1.0 if force < 0.0 and abs(side) <= -force * reach else 1.0
    x, y = direction * force, direction * side

    angle = math.atan2(y, x)
    angle_limited = abs(angle) > max_angle
    if angle_limited:
        # The helm's limit binds: hard over, with the thrust the side force needs.
        angle = math.copysign(max_angle, y)
        thrust = abs(y) / math.sin(max_angle)
    else:
        thrust = math.hypot(x, y)
    thrust_limited = thrust > max_thrust
    yaw_saturated = False
    if thrust_limited:
        thrust = max_thrust
        yaw_saturated = abs(y) > max_thrust * math.sin(max_angle)
        angle = math.copysign(max_angle, y) if yaw_saturated else math.asin(y / max_thrust)
    angle = _limited(angle, max_angle)  # never a rounding step beyond hard over: the model's helm has its stops just behind it
    surge_saturated = angle_limited or thrust_limited
    return ActuatorCommand(
        thrusts=(direction * thrust,),
        helm_angle=angle,
        force=direction * thrust * math.cos(angle) if surge_saturated else force,
        moment=steering_x * direction * thrust * math.sin(angle) if yaw_saturated else moment,
        yaw_saturated=yaw_saturated,
        surge_saturated=surge_saturated,
    )


def helm_travel(helm_angle: float, commanded_angle: float, max_travel: float) -> float:
    """Where a helm at helm_angle is after moving toward the commanded angle by at most max_travel (its rate times the step)."""
    return helm_angle + _limited(commanded_angle - helm_angle, max_travel)


def wait_for_helm(command: ActuatorCommand, helm_angle: float, *, steering_x: float, max_angle: float) -> ActuatorCommand:
    """A vectored thruster's command with the thrust held back while the helm is still on the other side.

    helm_angle is where the helm is now. A command on the other side of amidships (a turn the
    other way, or going astern or back ahead in a turn) would push the stern the wrong way
    until the helm has crossed. Beyond HELM_CROSSING_SHARE of the helm's limit on the wrong
    side, the thrust is cut to what gives the side force of the full thrust at that share.
    """
    thrust, commanded = command.thrusts[0], command.helm_angle
    tolerance = HELM_CROSSING_SHARE * max_angle
    if commanded is None or helm_angle * commanded >= 0.0 or abs(helm_angle) <= tolerance:
        return command
    thrust *= math.sin(tolerance) / math.sin(abs(helm_angle))
    return ActuatorCommand(
        thrusts=(thrust,),
        helm_angle=commanded,
        force=thrust * math.cos(helm_angle),
        moment=steering_x * thrust * math.sin(helm_angle),
        yaw_saturated=True,
        surge_saturated=True,
    )
