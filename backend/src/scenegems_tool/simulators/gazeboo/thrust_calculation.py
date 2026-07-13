import math

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel


def calculate_thrust_coefficient(vessel: ConcreteVessel, xU: float, xUU: float, xDotU: float) -> float:
    # ============================================================
    # PROPULSION CALIBRATION (Velocity & Acceleration)
    # ============================================================
    target_max_vel = vessel.max_speed  # e.g., 10.0 m/s
    target_max_accel = vessel.max_acceleration  # e.g., 0.5 m/s^2

    # --- 1. Thrust needed for Top Speed ---
    drag_at_max_vel = (abs(xU) * target_max_vel) + (abs(xUU) * (target_max_vel**2))
    thrust_for_vel = drag_at_max_vel / 2.0

    # --- 2. Thrust needed for Max Acceleration ---
    # F = m * a. In water, effective mass includes the "added mass" of water being pushed.
    effective_mass = vessel.mass + abs(xDotU)
    force_for_accel = effective_mass * target_max_accel
    thrust_for_accel = force_for_accel / 2.0

    # --- 3. Size the physical motor for the hardest requirement ---
    # We install a motor capable of whichever thrust value is higher.
    max_required_thrust = max(thrust_for_vel, thrust_for_accel)

    # --- 4. Lock ArduPilot to a realistic motor speed ---
    ardupilot_multiplier = 100.0
    max_rad_per_sec = 50.0

    # --- 5. Calculate the Gazebo Thrust Coefficient ---
    rho = 1025.0
    D = vessel.propeller_diameter

    if D > 0:
        dynamic_thrust_coeff = max_required_thrust / (rho * (D**4) * (max_rad_per_sec**2))
    else:
        dynamic_thrust_coeff = 0.1
    return dynamic_thrust_coeff


def calculate_thrust_multiplier(vessel: ConcreteVessel, xU: float, xUU: float, number_of_motors: int) -> float:
    overhead_margin = 1.1
    offset_factor = 2
    return (abs(xU) * vessel.max_speed + abs(xUU) * (vessel.max_speed**2)) / number_of_motors * overhead_margin * offset_factor
