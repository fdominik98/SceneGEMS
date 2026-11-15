"""Parametric dynamics of the generated Gazebo vessel model.

Everything follows the ConcreteVessel's dimensions, limits, block coefficient and steering type:
the hull form (hull_form.py) with its displacement, a mass distribution by radii of gyration,
buoyant boxes along the hull that float the vessel at its draft, the hydrodynamic coefficients
(hydrodynamics.py), thrusters sized from the max speed (thrust_calculation.py), the steering
gear and a windage link that carries the wind force.

Steering, by the vessel's steering type:

- skid: two fixed thrusters side by side. Full differential thrust (one full ahead, one full
  astern) reaches the design yaw rate, control margin times the vessel's max angular speed.
- rudder: one thruster on the centerline and a rudder behind it. The rudder is a foil in the
  flow past the stern, so its turning force grows with the square of the speed and it does
  nothing at rest (the propeller's wash on the rudder is not modelled).
- vectored_thrust: one thruster that turns with the helm, so it steers by its own thrust, at
  rest too, and not at all when the engine is stopped.

For a rudder and for vectored thrust the yaw damping is calibrated on a steady turn: with the
helm hard over and the thrust that holds the steering speed (a share of the max speed) on a
straight course, the hull settles at the design yaw rate. The turn is solved with the drift it
causes (the hull slides outward, which eases the rudder's angle of attack and slows the vessel).
A vessel whose max turn rate no helm can hold at that speed (a long ship with a high turn rate)
keeps a minimum yaw damping, and max_steady_yaw_rate tells what the helm then reaches.

An override (vessel_dynamics_overrides.py) replaces an assumption before the derivation, or
a derived value after it. A derived override replaces only that value; nothing derived from
it is recomputed, so overriding the hull mass changes the draft the vessel floats at.
"""

import dataclasses
import functools
import math
from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, Mapping, Optional, Tuple

from concrete_level.models.concrete_actors import ConcreteVessel
from logical_level.mapping.vessel_type import SteeringType
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hull_form import HullForm, HullStation
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.hydrodynamics import (
    RHO_WATER,
    calculate_hydrodynamics,
    damping_force,
    rudder_force,
    split_damping,
    surge_damping,
    vectored_thrust_force,
)
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.thrust_calculation import size_thrusters

RHO_AIR = 1.225  # kg/m^3
# force_approximation_scaling_factor of the world WindEffects system [1/s]. WindEffects pushes
# a link with mass * factor * (wind velocity - link velocity), so a windage link of mass c / factor
# feels c N per m/s of relative wind, whatever the vessel's own mass.
WIND_FORCE_SCALING = 1.0
# Each buoyant box is split into BUOYANCY_GRID cells across the hull. gz-sim Harmonic up to at
# least 8.15 slices each collision with a water plane that tilts with the shape (fixed upstream
# in gazebosim/gz-sim#3880, not released yet), so one box gets no restoring moment; the cells'
# differential immersion restores roll with 1 - 1/n^2 of the metacentric radius. With the fix
# the cells add up to the exact box.
BUOYANCY_GRID = 3
HULL_STATIONS = 9  # buoyant boxes along the hull in flat water: enough for the hull's shape and its pitch restoring
# The helm goes from hard over to hard over within the time the vessel turns this far at its max turn rate.
HELM_TRAVEL_TURN = math.pi / 6.0
STEADY_TURN_ITERATIONS = 40


@dataclass(frozen=True)
class DynamicsAssumptions:
    block_coefficient: float = 0.6  # displaced volume over L * B * T; the vessel's own unless overridden
    midship_coefficient: float = 0.0  # midship section over B * T; 0 derives it from the block coefficient
    waterplane_coefficient: float = 0.0  # waterplane area over L * B; 0 derives it from the block coefficient
    com_depth_ratio: float = 0.5  # depth of the center of mass below the waterline, share of the draft
    roll_gyration_ratio: float = 0.35  # roll radius of gyration, share of the breadth
    pitch_yaw_gyration_ratio: float = 0.25  # pitch and yaw radius of gyration, share of the length
    thruster_mass_ratio: float = 0.001  # one thruster's mass, share of the displacement
    thruster_beam_ratio: float = 0.8  # lateral offset of each of two thrusters, share of the half breadth
    thruster_aft_ratio: float = 0.9  # thruster distance aft of midship, share of the half length
    propeller_kt: float = 0.3  # open-water thrust coefficient (thrust = K_T * rho * n^2 * D^4, n in rev/s)
    resistance_coefficient: float = 0.005  # total resistance coefficient on the wetted surface
    cross_flow_drag_coefficient: float = 1.0  # sway drag coefficient of the underwater side
    linear_damping_share: float = 0.2  # linear share of the surge and yaw damping at their reference speed
    control_margin: float = 1.2  # full thrust reaches margin * max speed, full helm margin * max yaw rate
    surge_added_mass_ratio: float = 0.05  # surge added mass, share of the displacement
    added_mass_cap: float = 0.5  # cap of the other added masses, share of the rigid-body value
    heave_damping_ratio: float = 0.5
    roll_pitch_damping_ratio: float = 0.3
    air_drag_coefficient: float = 0.9  # drag coefficient of the hull side above water
    wind_reference_speed: float = 1.0  # m/s; the windage is linearized at max(wind speed, this)
    steering_speed_share: float = 0.5  # a rudder or a vectored thruster reaches the design yaw rate at this share of the max speed
    min_yaw_damping_share: float = 0.05  # least yaw damping at the design yaw rate, share of the helm's full moment
    rudder_area_ratio: float = 0.02  # rudder area, share of L * T
    rudder_span_ratio: float = 0.7  # rudder height, share of the draft
    rudder_aft_ratio: float = 0.97  # rudder distance aft of midship, share of the half length
    rudder_lift_slope: float = 2.5  # normal force coefficient of the rudder per rad of angle of attack
    rudder_max_angle_deg: float = 35.0  # hard over
    rudder_rate_deg_s: float = 5.0  # least helm speed
    vectored_max_angle_deg: float = 30.0  # hard over of a vectored thruster
    vectored_rate_deg_s: float = 15.0  # least helm speed of a vectored thruster
    # A measured turning circle to calibrate the yaw damping on, in place of the design yaw rate: the diameter of
    # the steady turn with the helm hard over, in ship lengths (0: none), entered at turn_speed m/s (0: the steering speed).
    turn_diameter_ratio: float = 0.0
    turn_speed: float = 0.0


@dataclass(frozen=True)
class VesselDynamics:
    """Everything the SDF needs, in SI units, body frame x forward, y port, z up, origin at the waterline over the hull's center of buoyancy."""

    # From the vessel, not overridable.
    length: float
    breadth: float
    height: float
    draft: float
    steering_type: str  # SteeringType value
    hull: HullForm
    stations: Tuple[HullStation, ...]  # buoyant boxes along the hull in flat water, stern first, in the model's frame
    hull_x: float  # m, where the hull's midship lies in the model's frame: the origin is over the center of buoyancy
    thruster_count: int  # 2 for skid steering, else 1
    design_speed: float  # full thrust settles here (m/s)
    design_yaw_rate: float  # full helm aims at this (rad/s)
    steering_speed: float  # the speed the helm is calibrated at (m/s); 0 for skid steering, which turns at rest
    # Mass and inertia.
    hull_mass: float
    com_z: float
    hull_ixx: float
    hull_iyy: float
    hull_izz: float
    # Windage link (wind force in N per m/s of relative wind equals its mass * WIND_FORCE_SCALING).
    windage_mass: float
    windage_z: float
    # Thrusters.
    thruster_mass: float
    thruster_x: float
    thruster_y: float  # port thruster of two; 0 for one
    thruster_z: float
    propeller_diameter: float
    motor_length: float
    max_thrust: float  # N per thruster
    thrust_coefficient: float
    # Steering gear: the rudder, or the mount a vectored thruster turns on. All 0 for skid steering.
    steering_mass: float
    steering_x: float  # m, where the helm's side force acts (negative: aft)
    steering_z: float
    steering_max_angle: float  # rad, hard over either way
    steering_rate: float  # rad/s, helm speed
    rudder_area: float  # m^2; 0 without a rudder
    rudder_span: float
    rudder_chord: float
    rudder_lift_slope: float
    max_steady_yaw_rate: float  # rad/s the helm hard over reaches at the steering speed: the design yaw rate unless the hull cannot follow
    # Hydrodynamics (gz-sim Hydrodynamics system names).
    xDotU: float
    yDotV: float
    zDotW: float
    nDotR: float
    xU: float
    yV: float
    zW: float
    kP: float
    mQ: float
    nR: float
    xUabsU: float
    yVabsV: float
    nRabsR: float

    @property
    def total_mass(self) -> float:
        return self.hull_mass + self.thruster_count * self.thruster_mass + self.steering_mass + self.windage_mass

    @property
    def total_thrust(self) -> float:
        return self.thruster_count * self.max_thrust

    @property
    def keel_z(self) -> float:
        return -self.draft

    @property
    def waterplane_area(self) -> float:
        return sum(station.waterplane_area for station in self.stations)

    @property
    def displaced_volume(self) -> float:
        """Volume of the buoyant boxes below the design waterline."""
        return sum(station.volume for station in self.stations)

    @property
    def floating_draft(self) -> float:
        """Draft at which the buoyant boxes displace the total mass (they are wall sided, so every m of sinkage adds the waterplane area)."""
        return self.draft + (self.total_mass / RHO_WATER - self.displaced_volume) / self.waterplane_area

    @property
    def reserve_depth(self) -> float:
        """How far the shallowest buoyant box reaches above the design waterline (each is centered on it)."""
        return min(station.depth for station in self.stations)

    @property
    def roll_metacentric_height(self) -> float:
        return _metacentric_height(self.stations, self.com_z, across=True)

    @property
    def pitch_metacentric_height(self) -> float:
        return _metacentric_height(self.stations, self.com_z, across=False)

    @property
    def yaw_inertia(self) -> float:
        """Rigid body and added inertia about the vertical axis."""
        return self.hull_izz + abs(self.nDotR)

    @property
    def surge_mass(self) -> float:
        return self.total_mass + abs(self.xDotU)

    def helm_force(self, angle: float, surge: float, sway_at_helm: float, thrust: float) -> Tuple[float, float]:
        """(X, Y) in N of thrust and helm together: `thrust` is the total thrust of a vessel with one thruster.

        Not for skid steering, whose two thrusts are its helm.
        """
        if self.steering_type == SteeringType.RUDDER.value:
            x, y = rudder_force(angle, surge, sway_at_helm, self.rudder_area, self.rudder_lift_slope)
            return thrust + x, y
        if self.steering_type == SteeringType.VECTORED_THRUST.value:
            return vectored_thrust_force(angle, thrust)
        raise ValueError("a skid steered vessel has no helm angle")

    def helm_moment(self, angle: float, surge: float, thrust: float) -> float:
        """Yaw moment (N m, counterclockwise) of a helm angle on a straight course at `surge` m/s with `thrust` N of thrust."""
        return self.steering_x * self.helm_force(angle, surge, 0.0, thrust)[1]

    @property
    def max_yaw_moment(self) -> float:
        """Largest yaw moment the steering gives: full differential thrust, or the helm hard over at the steering speed and its thrust."""
        if self.steering_type == SteeringType.SKID.value:
            return 2.0 * self.max_thrust * self.thruster_y
        return abs(self.helm_moment(self.steering_max_angle, self.steering_speed, self.steering_thrust))

    @property
    def steering_thrust(self) -> float:
        """Total thrust that holds the steering speed on a straight course."""
        return min(damping_force(self.xU, self.xUabsU, self.steering_speed), self.total_thrust)


_FIXED_FIELDS = frozenset({"length", "breadth", "height", "draft", "steering_type", "hull", "stations", "hull_x", "thruster_count", "design_speed", "design_yaw_rate", "steering_speed"})
ASSUMPTION_KEYS: FrozenSet[str] = frozenset(field.name for field in dataclasses.fields(DynamicsAssumptions))
# A name both classes have (rudder_lift_slope) is an assumption: the derivation follows it, and the value it yields is not replaced again.
VALUE_KEYS: FrozenSet[str] = frozenset(field.name for field in dataclasses.fields(VesselDynamics)) - _FIXED_FIELDS - ASSUMPTION_KEYS
OVERRIDE_KEYS: FrozenSet[str] = ASSUMPTION_KEYS | VALUE_KEYS


def hull_stations(hull: HullForm, count: int) -> Tuple[Tuple[HullStation, ...], float]:
    """The hull cut into `count` buoyant boxes in the model's frame, and where the hull's midship lies in that frame (m, forward positive).

    A hull with a fine bow has its center of buoyancy aft of midship. The model's center of mass
    is at its origin, so the hull is placed with its center of buoyancy there: with the origin
    amidships the model trimmed by the bow (1.4 degrees for a 30 m hull, measured in Gazebo), ran
    deeper under way and lost 5 percent of its speed.
    """
    stations = hull.stations(count)
    offset = -sum(station.volume * station.x for station in stations) / sum(station.volume for station in stations)
    return tuple(dataclasses.replace(station, x=station.x + offset) for station in stations), offset


def _metacentric_height(stations: Tuple[HullStation, ...], com_z: float, across: bool) -> float:
    """GM of the buoyant boxes at the design waterline: center of buoyancy plus metacentric radius minus center of mass.

    Across the hull each box is split into BUOYANCY_GRID cells, which gives 1 - 1/n^2 of its own
    waterplane inertia. Along the hull the boxes themselves are the cells: only their distance
    from midship counts.
    """
    volume = sum(station.volume for station in stations)
    buoyancy_z = -sum(station.volume * station.depth / 2.0 for station in stations) / volume
    if across:
        inertia = sum(station.length * station.breadth**3 / 12.0 for station in stations) * (1.0 - 1.0 / BUOYANCY_GRID**2)
    else:
        inertia = sum(station.waterplane_area * station.x**2 for station in stations)
    return buoyancy_z + inertia / volume - com_z


def check_inertia(name: str, ixx: float, iyy: float, izz: float) -> None:
    """Gazebo rejects a link whose principal moments break the triangle inequality (Error Code 19)."""
    moments = (ixx, iyy, izz)
    if min(moments) <= 0 or ixx + iyy < izz or iyy + izz < ixx or ixx + izz < iyy:
        raise ValueError(f"{name}: inertia ixx={ixx:.6g}, iyy={iyy:.6g}, izz={izz:.6g} is not a valid rigid body (positive moments satisfying the triangle inequality)")


def _signed_damping(linear: float, quadratic: float, value: float) -> float:
    return abs(linear) * value + abs(quadratic) * value * abs(value)


def _bisect(function: Callable[[float], float], low: float, high: float) -> float:
    """Root of a function that falls from positive at `low` to negative at `high`."""
    for _ in range(STEADY_TURN_ITERATIONS):
        middle = (low + high) / 2.0
        if function(middle) > 0.0:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def steady_turn(
    yaw_rate: float,
    helm_force: Callable[[float, float], Tuple[float, float]],
    mass: float,
    surge_coefficients: Tuple[float, float],
    sway_coefficients: Tuple[float, float],
    helm_x: float,
    top_speed: float,
) -> Tuple[float, float, float]:
    """(surge, sway, yaw moment of the helm) of a hull turning steadily at yaw_rate (rad/s, counterclockwise).

    helm_force(surge, sway at the helm) is the (X, Y) force of thrust and helm. Surge and sway
    are in balance with the hull's damping and the rigid body's centripetal terms, as in the
    plant of the custom autopilot (control_layers/custom/hull_surge_yaw_model.py):

        0 =  m v r + X - (|xU| u + |xUabsU| u|u|)
        0 = -m u r + Y - (|yV| v + |yVabsV| v|v|)
    """
    sway_bound = 2.0 * top_speed + abs(helm_x * yaw_rate)

    def sway_of(surge: float) -> float:
        def residual(sway: float) -> float:
            return -mass * surge * yaw_rate + helm_force(surge, sway + helm_x * yaw_rate)[1] - _signed_damping(*sway_coefficients, sway)

        return _bisect(residual, -sway_bound, sway_bound)

    def surge_residual(surge: float) -> float:
        sway = sway_of(surge)
        return mass * sway * yaw_rate + helm_force(surge, sway + helm_x * yaw_rate)[0] - _signed_damping(*surge_coefficients, surge)

    surge = _bisect(surge_residual, 1e-6 * top_speed, 2.0 * top_speed)
    sway = sway_of(surge)
    return surge, sway, helm_x * helm_force(surge, sway + helm_x * yaw_rate)[1]


def _calibrate_helm_yaw_damping(
    helm_force_at: Callable[[float], Callable[[float, float], Tuple[float, float]]],
    design_yaw_rate: float,
    full_moment: float,
    mass: float,
    surge_coefficients: Tuple[float, float],
    sway_coefficients: Tuple[float, float],
    helm_x: float,
    top_speed: float,
    a: DynamicsAssumptions,
) -> Tuple[float, float, float]:
    """(nR, nRabsR, max steady yaw rate) of a hull steered by a helm.

    helm_force_at(angle) is the helm force function of steady_turn with the helm at that angle.
    The helm goes hard over to port (a negative angle turns the vessel counterclockwise).
    """

    def moment_at(yaw_rate: float) -> float:
        return steady_turn(yaw_rate, helm_force_at(-1.0), mass, surge_coefficients, sway_coefficients, helm_x, top_speed)[2]

    moment = moment_at(design_yaw_rate)
    floor = a.min_yaw_damping_share * full_moment
    if moment >= floor:
        nR, nRabsR = split_damping(moment, design_yaw_rate, a.linear_damping_share)
        return nR, nRabsR, design_yaw_rate
    # The helm cannot hold this turn rate: keep the least damping and find the rate it does hold.
    nR, nRabsR = split_damping(floor, design_yaw_rate, a.linear_damping_share)
    low, high = 0.0, design_yaw_rate
    for _ in range(24):
        middle = (low + high) / 2.0
        if moment_at(middle) > _signed_damping(nR, nRabsR, middle):
            low = middle
        else:
            high = middle
    return nR, nRabsR, (low + high) / 2.0


def _steady_turn_with_damping(
    helm_force: Callable[[float, float], Tuple[float, float]],
    yaw_coefficients: Tuple[float, float],
    mass: float,
    surge_coefficients: Tuple[float, float],
    sway_coefficients: Tuple[float, float],
    helm_x: float,
    top_speed: float,
) -> Tuple[float, float, float]:
    """(surge, sway, yaw rate) of the steady turn of a hull with a given yaw damping under a helm force that turns it counterclockwise.

    The yaw rate is where the helm's moment in the steady turn (steady_turn) equals the yaw damping.
    """

    def excess(yaw_rate: float) -> float:
        return steady_turn(yaw_rate, helm_force, mass, surge_coefficients, sway_coefficients, helm_x, top_speed)[2] - _signed_damping(*yaw_coefficients, yaw_rate)

    high = 2.0 * top_speed / abs(helm_x)  # the helm itself would move sideways at twice the top speed: beyond any turn
    yaw_rate = _bisect(excess, 1e-9 * high, high)
    surge, sway, _ = steady_turn(yaw_rate, helm_force, mass, surge_coefficients, sway_coefficients, helm_x, top_speed)
    return surge, sway, yaw_rate


def _calibrate_turn_diameter(
    helm_force: Callable[[float, float], Tuple[float, float]],
    diameter: float,
    turn_speed: float,
    least_moment: float,
    mass: float,
    surge_coefficients: Tuple[float, float],
    sway_coefficients: Tuple[float, float],
    helm_x: float,
    top_speed: float,
    a: DynamicsAssumptions,
) -> Tuple[float, float]:
    """(nR, nRabsR) with which the steady turn under helm_force (hard over to port, at the trial's thrust) has the given diameter.

    The turn's radius, speed over yaw rate, falls as the yaw rate grows; the yaw rate that gives
    the wanted radius is found first, and the yaw damping is the helm's moment in that turn.
    """

    def radius_excess(yaw_rate: float) -> float:
        surge, sway, _ = steady_turn(yaw_rate, helm_force, mass, surge_coefficients, sway_coefficients, helm_x, top_speed)
        return math.hypot(surge, sway) / yaw_rate - diameter / 2.0

    high = 3.0 * turn_speed / (diameter / 2.0)
    yaw_rate = _bisect(radius_excess, 1e-6 * high, high)
    moment = steady_turn(yaw_rate, helm_force, mass, surge_coefficients, sway_coefficients, helm_x, top_speed)[2]
    return split_damping(max(moment, least_moment), yaw_rate, a.linear_damping_share)


def steady_turn_of(dynamics: VesselDynamics, speed: Optional[float] = None) -> Tuple[float, float, float]:
    """(surge, sway, yaw rate) of a model's steady turn with the helm hard over to port, at the thrust that holds `speed` m/s on a straight course.

    speed defaults to the model's steering speed. For a rudder or a vectored thruster; a skid
    steered model turns by its thrust difference.
    """
    if dynamics.steering_type == SteeringType.SKID.value:
        raise ValueError("a skid steered vessel has no helm to put hard over")
    speed = dynamics.steering_speed if speed is None else speed
    thrust = min(damping_force(dynamics.xU, dynamics.xUabsU, speed), dynamics.total_thrust)

    def helm_force(surge: float, sway_at_helm: float) -> Tuple[float, float]:
        return dynamics.helm_force(-dynamics.steering_max_angle, surge, sway_at_helm, thrust)

    return _steady_turn_with_damping(
        helm_force, (dynamics.nR, dynamics.nRabsR), dynamics.total_mass, (dynamics.xU, dynamics.xUabsU), (dynamics.yV, dynamics.yVabsV), dynamics.steering_x, dynamics.design_speed
    )


def derive_vessel_dynamics(vessel: ConcreteVessel, wind_speed: float = 0.0, overrides: Optional[Mapping[str, float]] = None) -> VesselDynamics:
    overrides = dict(overrides or {})
    unknown = set(overrides) - OVERRIDE_KEYS
    if unknown:
        raise ValueError(f"vessel {vessel.id} ({vessel.type}): unknown vessel dynamics keys {sorted(unknown)}")
    return _derive(vessel, float(wind_speed), tuple(sorted((key, float(value)) for key, value in overrides.items())))


@functools.lru_cache(maxsize=512)
def _derive(vessel: ConcreteVessel, wind_speed: float, override_items: Tuple[Tuple[str, float], ...]) -> VesselDynamics:
    overrides: Dict[str, float] = dict(override_items)
    name = f"vessel {vessel.id} ({vessel.type})"
    if vessel.max_speed <= 0 or vessel.max_angular_speed <= 0:
        raise ValueError(f"{name}: max speed and max angular speed must be positive to size the thrusters")
    a = dataclasses.replace(DynamicsAssumptions(block_coefficient=vessel.block_coefficient), **{key: value for key, value in overrides.items() if key in ASSUMPTION_KEYS})
    steering = vessel.steering_type

    length, breadth, height, draft = vessel.length, vessel.breadth, vessel.height, vessel.draft
    freeboard = height - draft
    design_speed = a.control_margin * vessel.max_speed
    design_yaw_rate = a.control_margin * vessel.max_angular_speed

    hull = HullForm.from_dimensions(length, breadth, draft, a.block_coefficient, a.midship_coefficient or None, a.waterplane_coefficient or None)
    stations, hull_x = hull_stations(hull, HULL_STATIONS)

    # Mass: the displacement at the draft, shared by hull, thrusters, steering gear and windage link.
    thruster_count = 2 if steering == SteeringType.SKID else 1
    displacement_mass = RHO_WATER * hull.displaced_volume
    thruster_mass = a.thruster_mass_ratio * displacement_mass
    steering_mass = 0.0 if steering == SteeringType.SKID else thruster_mass
    side_area_above_water = length * freeboard
    windage_coefficient = 0.5 * RHO_AIR * a.air_drag_coefficient * side_area_above_water * max(wind_speed, a.wind_reference_speed)
    windage_mass = windage_coefficient / WIND_FORCE_SCALING
    hull_mass = displacement_mass - thruster_count * thruster_mass - steering_mass - windage_mass
    com_z = -a.com_depth_ratio * draft
    hull_ixx = hull_mass * (a.roll_gyration_ratio * breadth) ** 2
    hull_iyy = hull_izz = hull_mass * (a.pitch_yaw_gyration_ratio * length) ** 2

    propeller_diameter = vessel.propeller_diameter if vessel.propeller_diameter > 0 else 0.6 * draft
    motor_length = vessel.motor_length if vessel.motor_length > 0 else 1.5 * propeller_diameter

    xU, xUabsU = surge_damping(hull.wetted_surface, vessel.max_speed, a.resistance_coefficient, a.linear_damping_share)
    thrusters = size_thrusters(
        count=thruster_count,
        length=length,
        breadth=breadth,
        propeller_diameter=propeller_diameter,
        design_speed=design_speed,
        xU=xU,
        xUabsU=xUabsU,
        thruster_beam_ratio=a.thruster_beam_ratio,
        thruster_aft_ratio=a.thruster_aft_ratio,
        propeller_kt=a.propeller_kt,
    )
    hydro = calculate_hydrodynamics(
        length=length,
        breadth=breadth,
        draft=draft,
        displacement_mass=displacement_mass,
        hull_ixx=hull_ixx,
        hull_iyy=hull_iyy,
        hull_izz=hull_izz,
        roll_metacentric_height=_metacentric_height(stations, com_z, across=True),
        pitch_metacentric_height=_metacentric_height(stations, com_z, across=False),
        waterplane_area=hull.waterplane_area,
        max_speed=vessel.max_speed,
        cross_flow_drag_coefficient=a.cross_flow_drag_coefficient,
        block_coefficient=a.block_coefficient,
        surge_added_mass_ratio=a.surge_added_mass_ratio,
        added_mass_cap=a.added_mass_cap,
        heave_damping_ratio=a.heave_damping_ratio,
        roll_pitch_damping_ratio=a.roll_pitch_damping_ratio,
    )

    # Steering gear and the yaw damping that makes full helm reach the design yaw rate.
    steering_fields: Dict[str, float] = {
        "steering_mass": steering_mass,
        "steering_x": 0.0,
        "steering_z": 0.0,
        "steering_max_angle": 0.0,
        "steering_rate": 0.0,
        "rudder_area": 0.0,
        "rudder_span": 0.0,
        "rudder_chord": 0.0,
        "rudder_lift_slope": 0.0,
        "max_steady_yaw_rate": design_yaw_rate,
    }
    steering_speed = 0.0
    if steering == SteeringType.SKID:
        # Full differential thrust: one thruster full ahead, the other full astern.
        nR, nRabsR = split_damping(2.0 * thrusters.max_thrust * thrusters.thruster_y, design_yaw_rate, a.linear_damping_share)
    else:
        steering_speed = a.steering_speed_share * vessel.max_speed
        steering_thrust = min(damping_force(xU, xUabsU, steering_speed), thrusters.total_thrust)
        total_mass = displacement_mass
        surge_coefficients, sway_coefficients = (xU, xUabsU), (hydro["yV"], hydro["yVabsV"])
        if steering == SteeringType.RUDDER:
            max_angle = math.radians(a.rudder_max_angle_deg)
            least_rate = math.radians(a.rudder_rate_deg_s)
            area = a.rudder_area_ratio * length * draft
            span = a.rudder_span_ratio * draft
            helm_x = -(length / 2.0) * a.rudder_aft_ratio
            steering_fields.update(rudder_area=area, rudder_span=span, rudder_chord=area / span, rudder_lift_slope=a.rudder_lift_slope, steering_z=-draft + span / 2.0)

            def helm_force_at(share: float, thrust: float = steering_thrust) -> Callable[[float, float], Tuple[float, float]]:
                def force(surge: float, sway_at_helm: float) -> Tuple[float, float]:
                    x, y = rudder_force(share * max_angle, surge, sway_at_helm, area, a.rudder_lift_slope)
                    return thrust + x, y

                return force

        else:
            max_angle = math.radians(a.vectored_max_angle_deg)
            least_rate = math.radians(a.vectored_rate_deg_s)
            helm_x = thrusters.thruster_x
            steering_fields.update(steering_z=com_z)

            def helm_force_at(share: float, thrust: float = steering_thrust) -> Callable[[float, float], Tuple[float, float]]:
                def force(surge: float, sway_at_helm: float) -> Tuple[float, float]:
                    del surge, sway_at_helm
                    return vectored_thrust_force(share * max_angle, thrust)

                return force

        full_moment = abs(helm_x * helm_force_at(1.0)(steering_speed, 0.0)[1])
        if a.turn_diameter_ratio > 0.0:
            # A measured turning circle: the hull turns on that diameter at the trial's speed, whatever yaw rate that is.
            turn_speed = min(a.turn_speed or steering_speed, design_speed)
            turn_thrust = min(damping_force(xU, xUabsU, turn_speed), thrusters.total_thrust)
            nR, nRabsR = _calibrate_turn_diameter(
                helm_force_at(-1.0, turn_thrust),
                a.turn_diameter_ratio * length,
                turn_speed,
                a.min_yaw_damping_share * full_moment,
                total_mass,
                surge_coefficients,
                sway_coefficients,
                helm_x,
                design_speed,
                a,
            )
            max_steady_yaw_rate = _steady_turn_with_damping(helm_force_at(-1.0), (nR, nRabsR), total_mass, surge_coefficients, sway_coefficients, helm_x, design_speed)[2]
        else:
            nR, nRabsR, max_steady_yaw_rate = _calibrate_helm_yaw_damping(helm_force_at, design_yaw_rate, full_moment, total_mass, surge_coefficients, sway_coefficients, helm_x, design_speed, a)
        steering_fields.update(
            steering_x=helm_x,
            steering_max_angle=max_angle,
            steering_rate=max(least_rate, 2.0 * max_angle * vessel.max_angular_speed / HELM_TRAVEL_TURN),
            max_steady_yaw_rate=max_steady_yaw_rate,
        )

    dynamics = VesselDynamics(
        length=length,
        breadth=breadth,
        height=height,
        draft=draft,
        steering_type=steering.value,
        hull=hull,
        stations=stations,
        hull_x=hull_x,
        thruster_count=thruster_count,
        design_speed=design_speed,
        design_yaw_rate=design_yaw_rate,
        steering_speed=steering_speed,
        hull_mass=hull_mass,
        com_z=com_z,
        hull_ixx=hull_ixx,
        hull_iyy=hull_iyy,
        hull_izz=hull_izz,
        windage_mass=windage_mass,
        windage_z=freeboard / 2.0,
        thruster_mass=thruster_mass,
        thruster_x=thrusters.thruster_x,
        thruster_y=thrusters.thruster_y,
        thruster_z=com_z,
        propeller_diameter=propeller_diameter,
        motor_length=motor_length,
        max_thrust=thrusters.max_thrust,
        thrust_coefficient=thrusters.thrust_coefficient,
        xU=xU,
        xUabsU=xUabsU,
        nR=nR,
        nRabsR=nRabsR,
        **steering_fields,
        **hydro,
    )
    dynamics = dataclasses.replace(dynamics, **{key: value for key, value in overrides.items() if key in VALUE_KEYS})
    _validate(dynamics, name)
    return dynamics


def _validate(dynamics: VesselDynamics, name: str) -> None:
    for field in ("hull_mass", "thruster_mass", "windage_mass", "propeller_diameter", "motor_length", "max_thrust"):
        if getattr(dynamics, field) <= 0:
            raise ValueError(f"{name}: {field} must be positive, got {getattr(dynamics, field):.6g}")
    if dynamics.steering_type != SteeringType.SKID.value:
        for field in ("steering_mass", "steering_max_angle", "steering_rate"):
            if getattr(dynamics, field) <= 0:
                raise ValueError(f"{name}: {field} must be positive for {dynamics.steering_type} steering, got {getattr(dynamics, field):.6g}")
    if dynamics.steering_type == SteeringType.RUDDER.value and min(dynamics.rudder_area, dynamics.rudder_span, dynamics.rudder_chord) <= 0:
        raise ValueError(f"{name}: a rudder needs a positive area, span and chord")
    check_inertia(f"{name} hull", dynamics.hull_ixx, dynamics.hull_iyy, dynamics.hull_izz)
    if dynamics.floating_draft - dynamics.draft >= dynamics.reserve_depth:
        raise ValueError(f"{name}: the buoyant volume cannot carry the total mass ({dynamics.total_mass:.6g} kg); the vessel would sink")
    if dynamics.roll_metacentric_height <= 0:
        raise ValueError(f"{name}: the hull is unstable in roll (metacentric height {dynamics.roll_metacentric_height:.3g} m); raise com_depth_ratio or the breadth")
