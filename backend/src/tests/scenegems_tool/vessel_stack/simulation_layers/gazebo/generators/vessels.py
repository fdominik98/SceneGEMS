"""Vessels for the tests of the generated Gazebo model: one of each steering type, and vessels of the shipped vessel types."""

import dataclasses
from typing import Tuple

from concrete_level.models.concrete_actors import ConcreteVessel
from logical_level.mapping.vessel_type import HEIGHT_TO_DRAFT, SteeringType, VesselType
from tests.scenegems_tool.vessel_stack.scenarios import make_vessel

STEERING_TYPES: Tuple[str, ...] = tuple(steering.value for steering in SteeringType)
HELM_STEERING_TYPES: Tuple[str, ...] = (SteeringType.RUDDER.value, SteeringType.VECTORED_THRUST.value)

# The three scales of the Phase 2 manoeuvre checks (design doc 12.7): 5 m, 30 m and 100 m.
SCALES = {
    "5m": dict(length=5.0, max_speed=4.0, max_angular_speed=0.5, max_acceleration=1.0),
    "30m": dict(length=30.0, max_speed=20.57778, max_angular_speed=0.05, max_acceleration=0.4),
    "100m": dict(length=100.0, max_speed=12.9, max_angular_speed=0.008, max_acceleration=0.05),
}


def steered(vessel: ConcreteVessel, steering_type: str) -> ConcreteVessel:
    """The same vessel with another steering type."""
    return dataclasses.replace(vessel, _steering_type=steering_type)


def scaled_vessel(scale: str, steering_type: str = SteeringType.SKID.value, vessel_id: int = 0) -> ConcreteVessel:
    return steered(make_vessel(vessel_id, True, **SCALES[scale]), steering_type)


def vessel_of_type(vessel_type: VesselType, length: float, vessel_id: int = 0) -> ConcreteVessel:
    """A vessel as the scene builder makes one of a vessel type: its hull ratios, steering type and block coefficient."""
    breadth = vessel_type.breadth_of(length)
    draft = vessel_type.draft_of(breadth)
    height = draft * HEIGHT_TO_DRAFT
    total_mass = 1025 * vessel_type.block_coefficient * length * breadth * draft
    thruster_mass = total_mass * 0.001
    propeller_diameter = draft * 0.6
    return ConcreteVessel(
        id=vessel_id,
        type=vessel_type.name,
        length=length,
        breadth=breadth,
        height=height,
        draft=draft,
        mass=total_mass - 2 * thruster_mass,
        safety_radius=4 * length,
        _is_os=vessel_id == 0,
        _max_speed=vessel_type.max_speed,
        _max_angular_speed=vessel_type.max_angular_speed,
        _max_acceleration=vessel_type.max_acceleration,
        _rudder_mass=0.0,
        _rudder_length=length * 0.02,
        _rudder_width=0.1,
        _rudder_height=height * 0.8,
        _propeller_diameter=propeller_diameter,
        _thruster_mass=thruster_mass,
        _motor_length=propeller_diameter * 1.5,
        _steering_type=vessel_type.steering_type,
        _block_coefficient=vessel_type.block_coefficient,
    )
