import numpy as np

from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.simulators.simulation_config import WaveConfig
from utils.global_constants import ONE_N_MILE_IN_M


def generate_ardu_params(vessel: ConcreteVessel, cruise_speed: float, wind: np.ndarray, wave: WaveConfig) -> dict:
    """
    Generates ArduPilot Rover parameters for a vessel based on its physical properties.

    Args:
        vessel: The ConcreteVessel instance containing physical and kinematic limits.
        max_speed: The desired mission/cruising speed (m/s).
    """
    physical_max_speed = vessel.max_speed

    # max_angular_speed in ConcreteVessel is in rad/s. Ardupilot needs degrees/s.
    max_turn_rate_deg_s = np.degrees(vessel.max_angular_speed)

    # Derive minimum turning radius: r = v / omega
    # Guard against division by zero if a vessel is defined without turning capabilities
    if vessel.max_angular_speed > 0:
        turning_radius = physical_max_speed / vessel.max_angular_speed
    else:
        turning_radius = vessel.length * 5  # Safe fallback

    # CRITICAL FIX 1: Bypass Rollover Protection
    # Force a minimum of 1.0 G so ArduPilot never disables steering at high speeds.
    calculated_g = (physical_max_speed**2) / (turning_radius * 9.81)
    turn_max_g = max(calculated_g, 1.0)

    params = {
        # ----------------------------------------
        # Base Frame & Mode Setup
        # ----------------------------------------
        "FRAME_CLASS": 2,  # 2 = Motorboat
        "INITIAL_MODE": 10,  # 10 = Auto
        # ----------------------------------------
        # Navigation & Waypoint Behavior
        # ----------------------------------------
        "PIVOT_TURN_ANGLE": 0,
        "WP_PIVOT_ANGLE": 45,
        # Directly utilizing properties from ConcreteVessel
        "WP_RADIUS": vessel.waypoint_radius,  # Your model sets this to length * 2.0
        # "TURN_RADIUS": turning_radius,
        # --- Speed Distinctions ---
        # Navigation targets use the desired mission speed
        "WP_SPEED": cruise_speed,
        "WPNAV_SPEED": cruise_speed,
        "CRUISE_SPEED": cruise_speed,
        # Absolute limits use the vessel's physical max
        "SPEED_MAX": physical_max_speed,
        "SIM_SHIP_SPEED": physical_max_speed,
        "CRUISE_THROTTLE": 60,  # Base estimate to achieve target_cruise_speed
        # 1. Position & Angle Controllers (The "Brain")
        # Higher PSC_POS_P makes it react faster to being off the path.
        # "PSC_POS_P": 0.25,        # (Default is 0.2, we had it at 0.1)
        # ----------------------------------------
        # Longitudinal Control (Speed & Throttle)
        # ----------------------------------------
        "ATC_ACCEL_MAX": vessel.max_acceleration,
        "ATC_DECEL_MAX": vessel.max_acceleration * 0.5,  # Ships coast, avoid aggressive reversing
        # Slew rate: 20 means 0-100% throttle takes 5 seconds. Prevents cavitation.
        # "MOT_SLEWRATE": 20,
        # Speed PID
        # "ATC_SPEED_P": 0.1,
        # "ATC_SPEED_I": 0.02,
        # "ATC_SPEED_D": 0.0,
        # ----------------------------------------
        # Lateral Control (Steering & Turn Rate)
        # ----------------------------------------
        # Limits define what the controller is ALLOWED to ask of the hull
        # "TURN_MAX_G": turn_max_g,
        # "ATC_STR_RAT_MAX": max_turn_rate_deg_s,
        # # CRITICAL FIX 2: L1 Controller Damping for Water
        # # 0.75 is default. Lowering it to 0.65 makes the L1 navigation controller
        # # more aggressive at correcting cross-track error (sliding sideways).
        # "NAV_L1_DAMPING": 0.65,
        # "NAV_L1_PERIOD": 8.0, # Time in seconds to correct the path. Smaller = more aggressive.
        # # ATC_STR_ANG_P dictates how aggressively heading error converts to turn rate.
        # # Higher = instant sharp turn demands when the heading is slightly off.
        # "ATC_STR_ANG_P": 3.0,     # (Standard rover is ~2.5)
        # STR_ACC_MAX is how fast the vessel is allowed to accelerate its rotation.
        # If left unset, Ardupilot defaults to a very sluggish ramp-up.
        # Setting this to 2x or 3x the max turn rate ensures immediate thruster application.
        # "ATC_STR_ACC_MAX": max_turn_rate_deg_s * 3.0,
        # Steering PID
        # "ATC_STR_RAT_FF": 1.0,   # Pushed to 1.0: 100% of turn demand goes instantly to thrusters
        # "ATC_STR_RAT_P": 0.2,    # Increased slightly to bite harder into the error
        # "ATC_STR_RAT_I": 0.05,
        # "ATC_STR_RAT_D": 0.01,
        # ----------------------------------------
        # Hardware / I/O Defaults
        # ----------------------------------------
        "SERVO1_FUNCTION": 73,  # Throttle Left
        "SERVO1_MIN": 1000,
        "SERVO1_MAX": 2000,
        "SERVO1_TRIM": 1500,  # 1500 must be neutral for skid steering to work
        "SERVO3_FUNCTION": 74,  # Throttle Right
        "SERVO3_MIN": 1000,
        "SERVO3_MAX": 2000,
        "SERVO3_TRIM": 1500,
        "SERVO_32_ENABLE": 0,
        "SKID_STEER_OUT": 1,
        "BATT_MONITOR": 4,
        # ----------------------------------------
        # FAILSAFES: Disabled for Simulation
        # ----------------------------------------
        "ARMING_CHECK": 0,  # Bypass pre-arm checks (GPS lock, sensors)
        "ARMING_REQUIRE": 0,  # 0 = No arming required (auto-arms on boot)
        "FS_GCS_ENABLE": 0,  # Disable Ground Control Station failsafe
        "FS_THR_ENABLE": 0,  # Disable Throttle failsafe
        "FS_CRASH_CHECK": 0,  # Disable crash detection failsafe
        "FS_EKF_ACTION": 0,  # Disable EKF action failsafe
        "BAT_FS": 0,  # Disable battery failsafe
        "FS_ACTION": 0,  # Disable failsafe action
        "FS_TIMEOUT": 60,  # 60 seconds before failsafe can be triggered
    }

    environment_params = {
        # Wind Parameters:
        "SIM_WIND_SPD": np.linalg.norm(wind),  # Sets the wind speed in meters per second (m/s).
        "SIM_WIND_DIR": np.degrees(np.arctan2(wind[1], wind[0])),  # Sets the direction the wind is coming from (0-360 degrees).
        "SIM_WIND_TURB": 0,  # Introduces turbulence and wind variation for a more realistic, chaotic breeze.
        "SIM_WIND_DIR_Z": 0,  # Adds a vertical wind component (useful for simulating up-drafts or down-drafts).
        # Wave Parameters (For ArduRover/Boats & ArduSub):
        "SIM_WAVE_ENABLE": 1 if wave.is_enabled else 0,  # Set to 1 to turn on the wave physics.
        "SIM_WAVE_AMP": wave.amplitude,  # Sets the wave amplitude (height) in meters.
        "SIM_WAVE_DIR": np.degrees(np.arctan2(wave.direction[1], wave.direction[0])),  # The compass direction the waves are moving.
        "SIM_WAVE_LENGTH": wave.length,  # The distance between the wave crests.
        "SIM_WAVE_SPEED": wave.speed,  # The speed at which the waves are traveling.
    }

    # not used, too constrained
    proximity_sensor_params = {
        # Proximity Sensor configurations
        "SERIALx_PROTOCOL": 2,  # (Set this on the telemetry port connected to your companion computer/script. 2 = MAVLink 2).
        "PRX1_TYPE": 2,  # (Tells ArduPilot to read proximity data from incoming MAVLink messages).
        "PRX1_MAX": 65534 / 100.0,
        "OA_TYPE": 1,  # (Enables the BendyRuler algorithm).
        "OA_BR_TYPE": 1,  # (Set to 1 for horizontal/2D routing, which matches 2D array).
        "OA_MARGIN_MAX": 1.0,  # (The minimum distance in meters to keep from the obstacle).
        "OA_BR_LOOKAHEAD": 65534 / 100.0,  # (How far ahead in meters ArduPilot should look to find a clear path).
        "RNGFND1_TYPE": 0,  # (Set to 0 to disable the proximity sensor).
        "RNGFND2_TYPE": 0,  # (Set to 0 to disable the proximity sensor).
    }

    return {**params, **environment_params}
