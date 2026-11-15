"""Hydrodynamic coefficients of the generated vessel model (gz-sim Hydrodynamics system, SNAME names) and the forces of its steering gear.

Every coefficient is negative (it opposes the motion) and follows the vessel's dimensions:

- surge: the total resistance at max speed from a resistance coefficient on the hull's wetted surface;
- sway: hull lift, linear with Clarke's (1983) derivative Y'v taken at max speed, plus quadratic
  cross-flow drag of the underwater side;
- yaw: calibrated by the caller (vessel_dynamics.py) so that full helm reaches the design yaw rate
  (control margin times the vessel's max angular speed);
- heave, roll and pitch: linear damping at a fixed damping ratio of the buoyancy restoring;
- added mass from strip theory, capped below the rigid-body value because the gz-sim system
  applies it explicitly from the previous step's acceleration, which diverges at or above it.

Surge and yaw split their damping at a reference speed into a linear share (low-speed
stability) and a quadratic remainder. The coefficients are constants (the gz-sim system has no
speed-dependent terms), and the model leaves out the added-mass Coriolis terms and the sway-yaw
cross terms (see vessel_model_generator.py), so the hull itself is directionally stable.

The steering gear's forces are what the model's plugins apply: a rudder is a foil in the water
flowing past the stern (a second Hydrodynamics system on the rudder link, with one cross term),
a vectored thruster pushes along its turned axis. The helm angle is counterclockwise seen from above, so a positive angle
swings the rudder's trailing edge, or the thruster's wash, to starboard and turns the vessel to
starboard.
"""

import math
from typing import Dict, Tuple

RHO_WATER = 1025.0  # kg/m^3
GRAVITY = 9.81  # m/s^2


def split_damping(damping_at_reference: float, reference_speed: float, linear_share: float) -> Tuple[float, float]:
    """(linear, quadratic) coefficients whose sum at the reference speed is the given damping."""
    linear = -linear_share * damping_at_reference / reference_speed
    quadratic = -(1.0 - linear_share) * damping_at_reference / reference_speed**2
    return linear, quadratic


def surge_damping(wetted_surface: float, max_speed: float, resistance_coefficient: float, linear_damping_share: float) -> Tuple[float, float]:
    """(xU, xUabsU) from the total resistance at max speed on the hull's wetted surface."""
    resistance = 0.5 * RHO_WATER * resistance_coefficient * wetted_surface * max_speed**2
    return split_damping(resistance, max_speed, linear_damping_share)


def damping_force(linear: float, quadratic: float, speed: float) -> float:
    """Magnitude of the damping force (or moment) at the given speed."""
    return abs(linear) * speed + abs(quadratic) * speed**2


def rudder_normal_force_coefficient(area: float, lift_slope: float) -> float:
    """yVabsU of the rudder link: its normal force is this times its velocity across the blade times its speed along it."""
    return -0.5 * RHO_WATER * area * lift_slope


def rudder_force(angle: float, surge: float, sway_at_rudder: float, area: float, lift_slope: float) -> Tuple[float, float]:
    """(X, Y) in N of a rudder at a helm angle, in the body frame (x forward, y to port).

    surge and sway_at_rudder are the rudder's own velocity through the water. The force is
    normal to the blade and grows with the flow across it times the flow along it, which is
    the lift of a foil at a small angle of attack and fades out as the blade turns broadside
    (the rudder's normal force of the MMG model). It is what the Hydrodynamics system gives the
    rudder link with a yVabsU coefficient.
    """
    cos_angle, sin_angle = math.cos(angle), math.sin(angle)
    along = surge * cos_angle + sway_at_rudder * sin_angle
    across = -surge * sin_angle + sway_at_rudder * cos_angle
    normal = rudder_normal_force_coefficient(area, lift_slope) * across * abs(along)
    return -normal * sin_angle, normal * cos_angle


def vectored_thrust_force(angle: float, thrust: float) -> Tuple[float, float]:
    """(X, Y) in N of a thruster turned by the helm angle."""
    return thrust * math.cos(angle), thrust * math.sin(angle)


def calculate_hydrodynamics(
    *,
    length: float,
    breadth: float,
    draft: float,
    displacement_mass: float,
    hull_ixx: float,
    hull_iyy: float,
    hull_izz: float,
    roll_metacentric_height: float,
    pitch_metacentric_height: float,
    waterplane_area: float,
    max_speed: float,
    cross_flow_drag_coefficient: float,
    block_coefficient: float,
    surge_added_mass_ratio: float,
    added_mass_cap: float,
    heave_damping_ratio: float,
    roll_pitch_damping_ratio: float,
) -> Dict[str, float]:
    mass = displacement_mass

    # Added mass (strip theory): sway as a half plate of depth T, heave as a half plate of
    # breadth B, yaw as the sway strips weighted by their lever arm.
    sway_strip = 0.5 * RHO_WATER * math.pi * draft**2 * length
    heave_strip = 0.5 * RHO_WATER * math.pi * (breadth / 2.0) ** 2 * length
    yaw_strip = sway_strip * length**2 / 12.0
    xDotU = -surge_added_mass_ratio * mass
    yDotV = -min(sway_strip, added_mass_cap * mass)
    zDotW = -min(heave_strip, added_mass_cap * mass)
    nDotR = -min(yaw_strip, added_mass_cap * hull_izz)

    # Sway: hull lift (Clarke's linear derivative, made dimensional at max speed) and cross-flow drag.
    clarke_yv = math.pi * (draft / length) ** 2 * (1.0 + 0.40 * block_coefficient * breadth / draft)
    yV = -0.5 * RHO_WATER * length**2 * max_speed * clarke_yv
    yVabsV = -0.5 * RHO_WATER * cross_flow_drag_coefficient * length * draft

    # Heave, roll and pitch: linear damping at a damping ratio of the hydrostatic stiffness.
    heave_stiffness = RHO_WATER * GRAVITY * waterplane_area
    zW = -2.0 * heave_damping_ratio * math.sqrt(heave_stiffness * (mass - zDotW))
    roll_stiffness = mass * GRAVITY * roll_metacentric_height
    kP = -2.0 * roll_pitch_damping_ratio * math.sqrt(roll_stiffness * hull_ixx)
    pitch_stiffness = mass * GRAVITY * pitch_metacentric_height
    mQ = -2.0 * roll_pitch_damping_ratio * math.sqrt(pitch_stiffness * hull_iyy)

    return {
        "xDotU": xDotU,
        "yDotV": yDotV,
        "zDotW": zDotW,
        "nDotR": nDotR,
        "yV": yV,
        "zW": zW,
        "kP": kP,
        "mQ": mQ,
        "yVabsV": yVabsV,
    }
