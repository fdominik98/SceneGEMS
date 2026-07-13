import math
import time
import traceback
from datetime import datetime
from config import AgentConfig

from connections import MAVLinkConnection
from dronekit import (  # type: ignore  # noqa: PGH003
    Command,
    LocationGlobalRelative,
    LocationGlobal,
    Vehicle,
    VehicleMode,
)
from pymavlink import mavutil  # type: ignore  # noqa: PGH003
from pymavlink.quaternion import QuaternionBase  # type: ignore  # noqa: PGH003
from shapely.geometry import Point, Polygon  # type: ignore  # noqa: PGH003


class VehicleCategory:
    SPACE = "SPACE"
    AIR = "AIR"
    GROUND = "GROUND"
    SURFACE = "SURFACE"
    SUBSURFACE = "SUBSURFACE"
    UNKNOWN = "UNKNOWN"


class Mavlink:
    def __init__(self, mavlink_connection: MAVLinkConnection) -> None:
        self.vehicle : Vehicle = mavlink_connection.vehicle

        self.cargo_collection: list = []
        self.auto_arm: bool = False  # Set by topic /simulation/

        self.vehicle_type: int = -1
        self.landed_state: int = -1

        self.mission_done: bool = False
        self.on_mission: bool = False

        self.wanted_speed_mps: float = 0.0
        self.speed_override_mps: float | None = None
        self.sog_mps: float = 0.0

        self.current_altitude_relative: float = 0.0
        self.minimum_takeoff_altitude_relative: float = (
            AgentConfig.MINIMUM_TAKEOFF_ALTITUDE_RELATIVE
        )
        self.minimum_mission_altitude_relative: float = (
            AgentConfig.MINIMUM_MISSION_ALTITUDE_RELATIVE
        )

        self.home_altitude_global = None

        self.in_collision_avoidance_mode: bool = False

        self.geofence: list = []
        self.no_go_zones: list = []

        self.cog_deg: float = 0.0

        self.mode_name_before_pause = None
        self.mode_name_before_rc = None

        self.pos_lead_old: list = [0.0, 0.0, 0.0]
        self.pos_lead_old_ts: float = 0.0

        self.initial_pos_follow_me_sent = False

        self.heading_thrust_waypoint: list = []
        
        self.clock = 0

        try:
            self.print_all_attributes()
        except Exception:
            print(traceback.format_exc())


    def send_obstacle_distances(self, distances: list, increment: float, min_distance: float, max_distance: float) -> None:
        """
        Packs and sends the OBSTACLE_DISTANCE MAVLink message.
        """
        max_distance_cm = 65534
        min_distance_cm = max(int(min_distance * 100), 0)
        
        distances_cm = [min(int(d * 100), 65535) for d in distances[:72]]
        if len(distances_cm) < 72:
            distances_cm.extend([65535] * (72 - len(distances_cm)))
            

        self.vehicle._master.mav.obstacle_distance_send(
            time_usec=0,
            sensor_type=mavutil.mavlink.MAV_DISTANCE_SENSOR_LASER, # 0 = Laser/LiDAR
            distances=distances_cm,
            increment=int(increment),            # degrees between each measurement (5 * 72 = 360)
            min_distance=min_distance_cm,
            max_distance=max_distance_cm,
            increment_f=float(increment),        # Float version of increment
            angle_offset=0.0,       # 0.0 means the 0th index is directly straight ahead
            frame=mavutil.mavlink.MAV_FRAME_BODY_FRD # Forward-Right-Down frame
        )

    def _make_do_change_speed_cmd(self, speed_mps: float) -> Command:
        return Command(
            0,
            0,
            0,
            mavutil.mavlink.MAV_FRAME_MISSION,
            mavutil.mavlink.MAV_CMD_DO_CHANGE_SPEED,
            0,
            1,
            0,
            speed_mps,
            0,
            0,
            0,
            0,
            0,
        )

    def _supports_spline_waypoints(self) -> bool:
        # ArduPilot documents spline missions for Copter only (not Rover/Plane).
        return self.is_rotary()

    def _global_mission_frame(self) -> int:
        if self.is_ground() or self.is_surface():
            return mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
        return mavutil.mavlink.MAV_FRAME_GLOBAL_INT

    def _global_nav_command(self, waypoint_index: int, waypoint_count: int) -> int:
        if (
            self._supports_spline_waypoints()
            and waypoint_count >= 2
            and waypoint_index < waypoint_count - 1
        ):
            return mavutil.mavlink.MAV_CMD_NAV_SPLINE_WAYPOINT
        return mavutil.mavlink.MAV_CMD_NAV_WAYPOINT

    def add_waypoints_to_mission_global(
        self, waypoints: list, speed_str: str = "standard", loop: int = 0) -> None:
        self.configure_task_speed(speed_str)

        if waypoints is not None and len(waypoints) > 0:
            mission_frame = self._global_mission_frame()
            if self.speed_override_mps is not None:
                self.vehicle.commands.add(
                    self._make_do_change_speed_cmd(self.speed_override_mps)
                )

            waypoint_count = len(waypoints)
            for waypoint_index, point in enumerate(waypoints):
                lat = point[0]
                lon = point[1]
                alt = point[2]

                wp_cmd: Command = Command(
                    0,  # target system
                    0,  # target component
                    0,  # sequence
                    mission_frame,  # INT frame => MISSION_ITEM_INT upload path
                    self._global_nav_command(waypoint_index, waypoint_count),
                    0,  # current
                    0,  # autucontinue
                    0,  # param1: Speed type (0=Airspeed, 1=Ground Speed)
                    0,  # param2: Speed in m/s
                    0,  # param3: Throttle (ignored)
                    0,  # param4: Absolute or relative (ignored)
                    lat,  # 11: latitude in degrees
                    lon,  # 12: longitude in degrees
                    alt,  # 13: altigutde in meters
                )
                self.vehicle.commands.add(wp_cmd)

            if loop != 0:
                wp_start_index = 1

                # Add DO_JUMP command
                loop_cmd = Command(
                    0,
                    0,
                    0,
                    mavutil.mavlink.MAV_FRAME_MISSION,
                    mavutil.mavlink.MAV_CMD_DO_JUMP,
                    0,
                    1,
                    wp_start_index,
                    loop,
                    0,
                    0,
                    lat,  # 11: latitude in degrees (DUMMY)
                    lon,  # 12: longitude in degrees (DUMMY)
                    alt,  # 13: altigutde in meters (DUMMY)
                )
                self.vehicle.commands.add(loop_cmd)

    def add_waypoints_to_mission_relative(
        self, waypoints: dict, speed_str: str = "standard", loop: int = 0
    ) -> None:
        self.configure_task_speed(speed_str)

        if waypoints is not None and len(waypoints) > 0:
            print(f"ALT={waypoints[0][2]}")

            if self.speed_override_mps is not None:
                self.vehicle.commands.add(
                    self._make_do_change_speed_cmd(self.speed_override_mps)
                )

            for point in waypoints:
                lat = point[0]
                lon = point[1]
                alt = point[2]

                wp_cmd: Command = Command(
                    0,  # target system
                    0,  # target component
                    0,  # sequence
                    mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,  # frame
                    mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,  # command
                    0,  # current
                    0,  # autocontinue
                    0,  # param1: Speed type (0=Airspeed, 1=Ground Speed)
                    0,  # param2: Speed in m/s
                    0,  # param3: Throttle (ignored)
                    0,  # param4: Yaw angle (ignored)
                    lat,  # param5: latitude in degrees
                    lon,  # param6: longitude in degrees
                    alt,  # param7: altitude in meters (relative to home position)
                )
                self.vehicle.commands.add(wp_cmd)

            if loop != 0:
                wp_start_index = 1

                # Add DO_JUMP command
                loop_cmd = Command(
                    0,
                    0,
                    0,
                    mavutil.mavlink.MAV_FRAME_MISSION,
                    mavutil.mavlink.MAV_CMD_DO_JUMP,
                    0,
                    1,
                    wp_start_index,
                    loop,
                    0,
                    0,
                    lat,  # 11: latitude in degrees (DUMMY)
                    lon,  # 12: longitude in degrees (DUMMY)
                    alt,  # 13: altigutde in meters (DUMMY)
                )
                self.vehicle.commands.add(loop_cmd)

    def set_speed(self, speed_mps: float) -> None:
        """Send DO_CHANGE_SPEED. Overrides FC WP_SPEED until mode change."""
        msg = self.vehicle.message_factory.command_long_encode(
            0,
            0,  # target_system, target_component
            mavutil.mavlink.MAV_CMD_DO_CHANGE_SPEED,  # command
            0,  # confirmation
            0,  # speed type (ignored by Rover; use 1 for Copter groundspeed)
            speed_mps,  # target speed in m/s
            0,
            0,
            0,
            0,
            0,
        )  # param 3 ~ 7 not used
        self.vehicle.send_mavlink(msg)
        self.vehicle.flush()
        print(f"DO_CHANGE_SPEED: {speed_mps} m/s")

    def apply_task_speed(self) -> None:
        """Apply a task speed override. No-op when using FC WP_SPEED."""
        if self.speed_override_mps is not None:
            self.set_speed(self.speed_override_mps)

    def clear_speed_override(self) -> None:
        self.speed_override_mps = None
        self.wanted_speed_mps = self.get_wp_speed_param()

    def configure_task_speed(self, speed_str) -> None:
        """Resolve task speed. 'standard' uses FC WP_SPEED without overriding it."""
        speed_label = (
            str(speed_str).strip().lower() if speed_str is not None else "standard"
        )

        if speed_label in ("standard", "normal", ""):
            self.wanted_speed_mps = self.get_wp_speed_param()
            self.speed_override_mps = None
            print(
                f"Task speed: use FC WP_SPEED ({self.wanted_speed_mps} m/s)"
            )
            return

        try:
            sp = float(speed_str)
            wp_speed = self.get_wp_speed_param()
            max_spd = self.get_max_speed()
            if sp > max_spd * 1.01:
                raise ValueError(f"Speed {sp} exceeds max {max_spd}")

            if abs(sp - wp_speed) < max(0.05, wp_speed * 0.02):
                self.wanted_speed_mps = wp_speed
                self.speed_override_mps = None
                print(
                    f"Task speed matches WP_SPEED ({wp_speed} m/s), no override"
                )
                return

            # C2 may send a pre-resolved float from speed_preset (e.g. 1.618
            # from the old 50%-of-wrong-max bug). Prefer FC WP_SPEED for those.
            stale_preset_cap = min(2.0, wp_speed * 0.2)
            if wp_speed > 3.0 and sp < stale_preset_cap:
                self.wanted_speed_mps = wp_speed
                self.speed_override_mps = None
                print(
                    f"Task speed {sp} m/s looks like stale preset; "
                    f"using FC WP_SPEED ({wp_speed} m/s)"
                )
                return

            self.wanted_speed_mps = sp
            self.speed_override_mps = sp
            print(f"Task speed override: {sp} m/s")
            return
        except (TypeError, ValueError) as exc:
            if "exceeds" in str(exc):
                raise

        wp_speed = self.get_wp_speed_param()
        fast_fraction = 1.0
        standard_fraction = 0.5
        slow_fraction = 0.25
        if self.is_fixed_wing():
            standard_fraction = 0.8
            slow_fraction = 0.6

        if speed_label == "fast":
            fraction = fast_fraction
        elif speed_label in ("standard", "normal"):
            fraction = standard_fraction
        else:
            fraction = slow_fraction

        self.wanted_speed_mps = fraction * wp_speed
        self.speed_override_mps = self.wanted_speed_mps
        print(
            f"Task speed preset '{speed_label}': {self.wanted_speed_mps} m/s"
        )

    def reset_speed(self) -> None:
        """Restore speed after collision avoidance or reset-speed."""
        if self.speed_override_mps is not None:
            self.set_speed(self.speed_override_mps)
        elif self.is_auto() or self.is_guided():
            self.set_speed(self.get_wp_speed_param())

    def set_home_position_global(
        self, lat: float, lon: float, alt_global: float
    ):
        print(f"Setting global home position to {lat}, {lon}, {alt_global}")
        # Create the MAVLink command to set the home position
        msg = self.vehicle.message_factory.set_home_position_encode(
            self.vehicle.location.global_frame.lat
            * 1e7,  # Latitude in scaled degrees
            self.vehicle.location.global_frame.lon
            * 1e7,  # Longitude in scaled degrees
            self.vehicle.location.global_frame.alt
            * 1000,  # Altitude in millimeters
            0,
            0,
            0,  # X, Y, Z (local offset)
            0,
            0,
            0,  # Q (quaternion)
            0,
            0,
            0,  # Approach X, Y, Z
        )

        # Send the command to the vehicle
        self.vehicle.send_mavlink(msg)
        self.vehicle.flush()
        self.home_altitude_global = alt_global

    def collect_cargo(self) -> None:
        msg = self.vehicle.message_factory.command_long_encode(
            0,
            0,
            mavutil.mavlink.MAV_CMD_DO_GRIPPER,
            0,
            1,
            mavutil.mavlink.GRIPPER_ACTION_GRAB,
            0,
            0,
            0,
            0,
            0,
        )
        self.vehicle.send_mavlink(msg)
        self.vehicle.flush()

    def release_cargo(self) -> None:
        msg = self.vehicle.message_factory.command_long_encode(
            0,
            0,
            mavutil.mavlink.MAV_CMD_DO_GRIPPER,
            0,
            1,
            mavutil.mavlink.GRIPPER_ACTION_RELEASE,
            0,
            0,
            0,
            0,
            0,
        )
        self.vehicle.send_mavlink(msg)
        self.vehicle.flush()

    def land(self) -> None:
        msg = self.vehicle.message_factory.command_long_encode(
            0,
            0,
            mavutil.mavlink.MAV_CMD_NAV_LAND,  # command
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )
        self.vehicle.send_mavlink(msg)
        self.vehicle.flush()

    def set_mode(self, new_mode: str) -> bool:
        print("Setting new mode:", new_mode)
        print("Current mode:", self.get_mode_name())
        if self.get_mode_name() == new_mode:
            return True

        else:
            loop: int = 0
            timeout_count: int = 5

            while self.get_mode_name() != new_mode:
                self.vehicle.mode = VehicleMode(new_mode)
                loop += 1

                if loop > timeout_count:
                    print("Timeout waiting for mode change")
                    break

                time.sleep(1)
        print(f"{self.get_mode_name()=} {new_mode=}")
        return self.get_mode_name() == new_mode

    def check_armable(self) -> bool:
        """Check if the Vehicle is armable, if not, waits."""
        if self.is_armable():
            print("Vehicle is armable")
            pass

        else:
            loop: int = 0
            timeout_count: int = 5

            while not self.is_armable():
                loop += 1
                if loop > timeout_count:
                    break

                time.sleep(2)

        return self.is_armable()

    def arm_vehicle(self) -> bool:
        """Check if the Vehicle is armed, if not, tries to arm it."""
        if self.is_armed():
            print("Vehicle is already armed")
            pass

        elif self.auto_arm:
            # if not self.is_armable():
            #     pass

            # else:
            loop: int = 0
            timeout_count: int = 5

            while self.is_disarmed():
                self.vehicle._master.mav.command_long_send(
                    self.vehicle._master.target_system,
                    self.vehicle._master.target_component,
                    mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                    0,
                    1,          # 1 = arm
                    21196,      # force arm magic number
                    0, 0, 0, 0, 0
                )
                self.vehicle.armed = True
                loop += 1

                if loop > timeout_count:
                    break

                time.sleep(2)

        return self.is_armed()

    def disarm_vehicle(self) -> bool:
        """Check if the Vehicle is disarmed, if not, tries to disarm it."""
        if not self.vehicle.armed:
            pass
        else:
            loop: int = 0
            timeout_count: int = 5

            while self.vehicle.armed:
                self.vehicle.armed = False
                loop += 1

                if loop > timeout_count:
                    break

                time.sleep(2)

        return self.is_disarmed()

    def prepare_vehicle_global(
        self, takeoff_altitude_global: float = None
    ) -> bool:
        # Calculate the relative altitude needed for takeoff

        if not takeoff_altitude_global or not self.vehicle.home_location.alt:
            takeoff_altitude_relative = self.minimum_takeoff_altitude_relative
        else:
            takeoff_altitude_relative = (
                takeoff_altitude_global - self.vehicle.home_location.alt
            )

        print(
            f"Wanted global/relative takeoff altitude is {takeoff_altitude_global / takeoff_altitude_relative}m."
        )

        return self.prepare_vehicle_relative(takeoff_altitude_relative)

    def prepare_vehicle_relative(
        self, takeoff_altitude_relative: float = None
    ) -> bool:
        # Default take off (for flying agents) relative altitude is defined in
        # self.minimum_takeoff_altitude_relative
        # If a mission has a greater take off relative altitude, use this

        if takeoff_altitude_relative is None:
            takeoff_safe_altitude_relative = (
                self.minimum_takeoff_altitude_relative
            )
        else:
            takeoff_safe_altitude_relative = max(
                takeoff_altitude_relative,
                self.minimum_takeoff_altitude_relative,
            )

        print(
            f"Wanted relative/Safe relative takeoff altitude is {takeoff_altitude_relative}/{takeoff_safe_altitude_relative}m."
        )

        if self.is_fixed_wing():
            return self.prepare_fixed_wing(takeoff_safe_altitude_relative)

        if self.is_rotary():
            return self.prepare_rotary(takeoff_safe_altitude_relative)

        if self.is_ground() or self.is_surface():
            return self.prepare_ground_surface()

        if self.is_subsurface():
            return self.prepare_subsurface()

        print(f"ERROR: In preparation of vehicle: {self.get_vehicle_class()!s}")
        return False

    def prepare_fixed_wing(
        self, takeoff_altitude_relative: float = None
    ) -> bool:
        if self.is_fixed_wing():
            if self.is_flying():
                return True

            if (
                not takeoff_altitude_relative
                or takeoff_altitude_relative
                < self.minimum_takeoff_altitude_relative
            ):
                takeoff_altitude_relative = (
                    self.minimum_takeoff_altitude_relative
                )

            """Prepares the fixed-wing vehicle for the mission."""
            # Perform pre-arm checks
            if (
                self.check_armable()
                and self.set_mode("MANUAL")
                and self.arm_vehicle()
            ):
                """Add take off command if needed to the vehicle."""
                to_cmd = Command(
                    0,  # target system
                    0,  # target component
                    0,  # sequence
                    mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,  # frame
                    mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,  # command
                    0,  # current
                    0,  # autocontinue
                    15,  # param1: pitch
                    0,  # param2:
                    0,  # param3:
                    0,  # param4:
                    self.vehicle.location.global_frame.lat,  # lat
                    self.vehicle.location.global_frame.lon,  # lon
                    takeoff_altitude_relative,  # alt
                )

                self.vehicle.commands.add(to_cmd)
                self.set_mode("TAKEOFF")

                return True

        return False

    def prepare_rotary(self, takeoff_altitude_relative: float = None) -> bool:
        if not self.is_rotary():
            return False

        if self.is_flying():
            return True

        # The agent is simulated.
        if self.auto_arm:
            if (
                not takeoff_altitude_relative
                or takeoff_altitude_relative
                < self.minimum_takeoff_altitude_relative
            ):
                takeoff_altitude_relative = (
                    self.minimum_takeoff_altitude_relative
                )

            """Prepare the multirotor vehicle for the mission, including takeoff."""
            # Perform pre-arm checks
            if (
                self.check_armable()
                and self.set_mode("GUIDED")
                and self.arm_vehicle()
            ):
                # Take off to target altitude
                print(f"Taking off to {takeoff_altitude_relative} meters")
                self.vehicle.simple_takeoff(takeoff_altitude_relative)
                print("Taking off...")
                print("Mode after takeoff:", self.vehicle.mode.name)
                print(
                    "Altitude after takeoff:",
                    self.vehicle.location.global_relative_frame.alt,
                )
                print("Armed:", self.vehicle.armed)

                # Wait until the vehicle reaches a safe height
                while True:
                    rel_alt = self.vehicle.location.global_relative_frame.alt
                    abs_alt = self.vehicle.location.global_frame.alt
                    print(
                        f"Altitude (rel) < TakeOff altitude (rel), abs alttitude: {rel_alt} < {takeoff_altitude_relative}, {abs_alt}"
                    )
                    if (
                        self.vehicle.location.global_relative_frame.alt
                        >= takeoff_altitude_relative * 0.95
                    ):
                        print("Reached target altitude")
                        break
                    time.sleep(1)
                return True

        # Agent is real
        else:
            print("Take off from ground not supported. Do a manual takeoff.")
            return False

        return False

    def prepare_ground_surface(self) -> bool:
        if self.is_ground() or self.is_surface():
            """Prepares the rover or boat vehicle for the mission."""
            # Perform pre-arm checks
            if (
                # self.check_armable() and
                self.set_mode("LOITER")
                and self.arm_vehicle()
            ):
                return True

        return False

    def prepare_subsurface(self) -> bool:
        if self.is_subsurface():
            """Prepares the ArduSub vehicle for the mission."""
            # Perform pre-arm checks
            if (
                # self.check_armable() and
                self.set_mode("POSHOLD")
                and self.arm_vehicle()
            ):
                return True

        return False

    def clear_mission(self) -> None:
        self.vehicle.commands.download()
        self.vehicle.commands.wait_ready()
        self.vehicle.commands.clear()
        self.vehicle.commands.next = 0
        self.vehicle.commands.upload()

        self.mission_done = False
        self.on_mission = False
        self.mode_name_before_pause = None
        self.speed_override_mps = None
        self.reset_heading_thrust()

    def start_mission(self, mission_to: str = "AUTO") -> bool:
        # Safety
        if self.is_manual():
            print("Cannot start mission in manual mode")
            return False

        res: bool = False

        if self.is_subsurface() or mission_to == "GUIDED":
            print("Starting mission in GUIDED mode")
            res = self.set_mode("GUIDED")
        else:
            print("Starting mission in AUTO mode")
            self.vehicle.commands.next = 0
            self.vehicle.commands.upload()
            res = self.set_mode("AUTO")

        if res:
            self.apply_task_speed()

        return res

    def stop_mission(self) -> bool:
        self.clear_mission()
        return self.paus_mission()

    def paus_mission(self) -> bool:
        current_mode: str = self.get_mode_name()
        paus_mode: str = None

        if self.is_rotary():
            paus_mode = "BRAKE"
            # paus_mode = "POSHOLD"

        elif self.is_fixed_wing():
            paus_mode = "LOITER"

        elif self.is_subsurface():
            paus_mode = "POSHOLD"

        elif self.is_ground():
            paus_mode = "LOITER"

        else:
            paus_mode = "LOITER"

        if self.set_mode(paus_mode):
            self.mode_name_before_pause = current_mode
            return True

        return False

    def continue_mission(self) -> bool:
        res: bool = False

        if self.mode_name_before_pause:
            res = self.set_mode(self.mode_name_before_pause)

        elif self.is_subsurface():
            res = self.set_mode("GUIDED")
        else:
            res = self.set_mode("AUTO")

        return res

    def is_heading_thrust(self):
        return (
            self.heading_thrust_waypoint
            and len(self.heading_thrust_waypoint) >= 2
        )

    def reset_heading_thrust(self):
        self.heading_thrust_waypoint = []

    def get_heading_thrust_waypoint(self):
        return self.heading_thrust_waypoint

    def send_attitude(
        self,
        yaw_angle: float,
        pitch_angle: float = 0.0,
        thrust: float = 0.5,
        roll_angle: float = 0.0,
        use_yaw_rate: bool = False,
        yaw_rate: float = 0.0,
    ) -> bool:
        if self.is_ready_for_guidance():
            if yaw_angle is None:
                # this value may be unused by the vehicle, depending on use_yaw_rate
                yaw_angle = float(self.vehicle.attitude.yaw)

            command = self.vehicle.message_factory.set_attitude_target_encode(
                0,
                1,
                1,
                0b00000000 if use_yaw_rate else 0b00000100,
                QuaternionBase(
                    [
                        math.radians(angle)
                        for angle in (roll_angle, pitch_angle, yaw_angle)
                    ]
                ),
                0,
                0,
                math.radians(yaw_rate),
                thrust,
            )
            self.vehicle.send_mavlink(command)

            return True

        return False

    def follow_lead_global(
        self, lat_lead: float, lon_lead: float, alt_lead_global: float
    ) -> None:
        if (
            lat_lead
            and lon_lead
            and alt_lead_global
            and self.vehicle.home_location.alt
        ):
            alt_lead_global_safe = max(
                alt_lead_global,
                (
                    self.vehicle.home_location.alt
                    + self.minimum_mission_altitude_relative
                ),
            )

            target_location = LocationGlobal(
                lat_lead, lon_lead, alt_lead_global_safe
            )

            # Command the following boat to move to the target position
            if not self.is_ready_for_guidance():
                print(
                    "Vehicle not ready for following leader with guidence mode."
                )
                return

            if self.set_mode("GUIDED"):
                # There is a command simple_goto with the additional speed parameter
                # but the speed is handled separately
                # (follow-lead, collision avoidance, no-go-zone, geofence)
                self.vehicle.simple_goto(target_location)

    def set_heading_thrust(self, hdg: float, spd: float = 0.0) -> None:
        # For now: Using the below design to prevent the need for
        # periodic updates that is needed if send_attitude is used.
        # I.e. use a projected point, 1000 seconds ahead, to go for.

        pos_own: list = self.get_current_position_global()
        lat_own: float = pos_own[0]
        lon_own: float = pos_own[1]

        if lat_own and lon_own and spd > 0:
            fut_pos: list = self.get_projected_position(
                lat_own, lon_own, spd, hdg, 1000
            )
            lat_go: float = fut_pos[0]
            lon_go: float = fut_pos[1]
            alt_go: float = self.get_current_altitude_global()

            if lat_go and lon_go and alt_go:
                self.heading_thrust_waypoint = [lat_go, lon_go, alt_go]
                loc_go = LocationGlobalRelative(lat_go, lon_go, alt_go)
                spd_go = self.get_speed_from_percent(spd)

                if not self.is_ready_for_guidance():
                    print(
                        "Vehicle not ready for following leader with guidence mode."
                    )
                    return

                if self.set_mode("GUIDED"):
                    self.vehicle.simple_goto(loc_go)
                    self.set_speed(spd_go)

    def terminate(self) -> None:
        self.vehicle.close()

    def is_system_ready(self) -> bool:
        return self.is_armable()

    def is_armable(self) -> bool:
        return self.vehicle.is_armable

    def is_armed(self) -> bool:
        return self.vehicle.armed

    def is_auto_armed(self) -> bool:
        return self.auto_arm

    def is_disarmed(self) -> bool:
        return not self.is_armed()

    def is_manual(self) -> bool:
        return self.is_armed() and self.get_mode_name() in [
            "ACRO",
            "ALT_HOLD",
            "AUTOTUNE",
            "AUTO_TUNE",
            "DRIFT",
            "FBWA",
            "FBWB",
            "FLIP",
            "MANUAL",
            # "POSHOLD",
            "STABLILIZE",
            "SPORT",
            "SIMPLE",
            "STEERING",
            "THROTTLE",
            "TRAINING",
        ]

    def is_auto(self) -> bool:
        return self.is_armed() and self.get_mode_name() in [
            "AUTO",
            "CIRCLE",
            "CRUISE",
            "DOCK",
            "FOLLOW",
            "INITIALIZE",
            "LAND",
            "RTL",
            "SMARTRTL",
            "SMART_RTL",
            "SURFACE",
            "TAKEOFF",
            "TERRAIN",
            "QRTL",
        ]

    def is_still(self) -> bool:
        return self.is_armed() and self.get_mode_name() in [
            "BRAKE",
            "HOLD",
            "FLOWHOLD",
            "LOITER",
            "LOITER_TURNS",
            "POSHOLD",
        ]

    def is_guided(self) -> bool:
        return self.is_armed() and self.get_mode_name() in ["GUIDED"]

    def is_busy(self) -> bool:
        return self.is_on_mission() or self.is_manual() or self.is_guided()

    def is_stopped(self) -> bool:
        return self.is_armed() and self.is_still() and self.is_mission_done()

    def is_paused(self) -> bool:
        return self.is_armed() and self.is_still() and self.is_on_mission()

    def is_ready_for_guidance(self) -> bool:
        if self.is_manual():
            return False

        return bool(self.is_guided() or self.is_auto())

    def is_ready_for_mission(self) -> bool:
        if self.is_manual():
            return False

        return bool(
            self.is_stopped() or self.is_guided() or self.is_mission_done()
        )

    def is_mission_done(self):
        return self.mission_done

    def is_on_mission(self):
        return self.on_mission or self.is_guided()

    def is_space(self):
        return self.get_vehicle_class() == VehicleCategory.SPACE

    def is_air(self):
        return self.get_vehicle_class() == VehicleCategory.AIR

    def is_ground(self):
        return self.get_vehicle_class() == VehicleCategory.GROUND

    def is_surface(self):
        return self.get_vehicle_class() == VehicleCategory.SURFACE

    def is_subsurface(self):
        return self.get_vehicle_class() == VehicleCategory.SUBSURFACE

    def get_state_name(self) -> str:
        return "armed" if self.is_armed() else "disarmed"

    def get_mode_name(self) -> str:
        return self.vehicle.mode.name

    def is_fixed_wing(self):
        return self.vehicle_type == mavutil.mavlink.MAV_TYPE_FIXED_WING

    def is_multi_rotor(self):
        return self.vehicle_type == mavutil.mavlink.MAV_TYPE_QUADROTOR

    def is_single_rotor(self):
        return self.vehicle_type == mavutil.mavlink.MAV_TYPE_HELICOPTER

    def is_rotary(self):
        return self.is_multi_rotor() or self.is_single_rotor()

    def is_on_ground(self):
        return not self.is_flying()

    def is_flying(self):
        return (
            self.is_air() and self.get_current_altitude_relative() > 1.0
        ) or (
            self.is_subsurface and self.get_current_altitude_relative() < -1.0
        )

    def is_valid_vehicle_type(self, type):
        return type != mavutil.mavlink.MAV_TYPE_GCS

    def get_vehicle_class(self):
        # print(
        #     f"Vehicle type: {self.vehicle_type} ==================================================="
        # )
        if self.vehicle_type in [
            mavutil.mavlink.MAV_TYPE_FIXED_WING,
            mavutil.mavlink.MAV_TYPE_QUADROTOR,
            mavutil.mavlink.MAV_TYPE_HELICOPTER,
        ]:
            return VehicleCategory.AIR
        elif self.vehicle_type in [mavutil.mavlink.MAV_TYPE_GROUND_ROVER]:
            return VehicleCategory.GROUND
        elif self.vehicle_type in [mavutil.mavlink.MAV_TYPE_SURFACE_BOAT]:
            return VehicleCategory.SURFACE
        elif self.vehicle_type in [mavutil.mavlink.MAV_TYPE_SUBMARINE]:
            return VehicleCategory.SUBSURFACE
        else:
            return VehicleCategory.UNKNOWN

    def get_current_position_global(self) -> list:
        """Help function for current position."""

        location = self.vehicle.location.global_frame
        if location and location.lat:
            lat = location.lat
            lon = location.lon
            alt = location.alt
            return [lat, lon, alt]
        return [0.0, 0.0, 0.0]

    def get_current_altitude_global(self) -> list:
        """Get the current altitude of the vehicle."""
        pos: list = self.get_current_position_global()
        return pos[2]

    def get_current_altitude_relative(self) -> list:
        """Get the current relative altitude of the vehicle."""
        return self.current_altitude_relative

    def get_next_waypoint_global(self) -> list:
        """Help function for next waypoint."""

        if self.is_on_mission():
            cmds = self.vehicle.commands
            if cmds and len(cmds) > 0:
                next_cmd = cmds[cmds.next - 1]
                if isinstance(next_cmd, Command):
                    print("HAS_POINT")
                    lat = next_cmd.x
                    lon = next_cmd.y
                    alt = next_cmd.z
                    return [lat, lon, alt]

        return []

    def get_waypoints_global(self) -> list:
        """Help function for waypoints."""

        wps: list = []

        if self.is_on_mission():
            cmds = self.vehicle.commands
            next_index = cmds.next  # Get the index of the next waypoint

            if cmds and len(cmds) > 0:
                for i, cmd in enumerate(cmds):
                    if i >= next_index - 1 and isinstance(cmd, Command):
                        lat = round(float(cmd.x), 7)
                        lon = round(float(cmd.y), 7)
                        alt = round(float(cmd.z), 2)
                        wp = [lat, lon, alt]
                        wps.append(wp)

        return wps

    def get_wp_speed_param(self) -> float:
        try:
            if self.is_fixed_wing():
                max_spd = self.vehicle.parameters.get("AIRSPEED_CRUISE")
                if not max_spd:
                    max_spd = self.vehicle.parameters.get("ARSPD_FPW_MAX")
            elif self.is_rotary() or self.is_subsurface():
                max_spd = self.vehicle.parameters.get("WPNAV_SPEED") / 100.0
            elif self.is_ground() or self.is_surface():
                max_spd = self.vehicle.parameters.get("WP_SPEED")
                if not max_spd:
                    max_spd = self.vehicle.parameters.get("CRUISE_SPEED")
            else:
                max_spd = 0.0

            if not max_spd:
                max_spd = 0.9
        except Exception:
            print(traceback.format_exc())
            max_spd = 0.9

        return float(max_spd)

    def get_max_speed(self) -> float:
        return self.get_wp_speed_param()

    def get_speed_from_string(self, speed: str):
        if speed is None:
            speed = "standard"
        speed_label = str(speed).strip().lower()
        wp_speed = self.get_wp_speed_param()
        max_spd = self.get_max_speed()

        try:
            sp = float(speed)
            if sp > max_spd * 1.01:
                raise ValueError(f"Speed {sp} exceeds max {max_spd}")
            return sp
        except ValueError as exc:
            if "exceeds" in str(exc):
                raise

        fast_fraction = 1.0
        standard_fraction = 0.5
        slow_fraction = 0.25
        if self.is_fixed_wing():
            standard_fraction = 0.8
            slow_fraction = 0.6

        if speed_label == "fast":
            return fast_fraction * max_spd
        if speed_label in ("standard", "normal", ""):
            return wp_speed
        return slow_fraction * max_spd
        
    def get_speed_preset(self) -> dict:
        speed_preset: dict = {
            "slow": self.get_speed_from_string("slow"),
            "standard": self.get_speed_from_string("standard"),
            "fast": self.get_speed_from_string("fast"),
        }
        return speed_preset

    def get_speed_from_percent(self, speed_fraction: float):
        max_spd: float = self.get_max_speed()

        if speed_fraction and max_spd:
            return speed_fraction * max_spd

        return 0.0

    def set_auto_arm(self, val: bool = False) -> None:
        self.auto_arm = val

    def return_to_launch(self) -> bool:
        is_returning: bool = False
        if self.is_subsurface():
            is_returning = self.set_mode("SURFACE")
        else:
            is_returning = self.set_mode("RTL")

        self.vehicle.flush()

        return is_returning

    # Geographical helpers =====================================================

    def set_geofence(self, area: list) -> bool:
        if area and len(area) > 3:
            self.geofence = area
            return True

        return False

    def clear_geofence(self) -> bool:
        self.geofence = []
        return True

    def add_to_no_go_zones(self, area: list) -> bool:
        if not self.no_go_zones:
            self.no_go_zones = []

        self.no_go_zones.append(area)
        return True

    def clear_no_go_zones(self) -> bool:
        self.no_go_zones = []
        return True

    def get_horizontal_distance_to_own(
        self, lat_other: float, lon_other: float
    ):
        pos_own: list = self.get_current_position_global()
        lat_own: float = pos_own[0]
        lon_own: float = pos_own[1]

        return self.get_horizontal_distance_between_points(
            lat_own, lon_own, lat_other, lon_other
        )

    def get_horizontal_distance_between_points(
        self, lat1: float, lon1: float, lat2: float, lon2: float
    ):
        # convert decimal degrees to radians
        lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
        # haversine formula
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.asin(math.sqrt(a))

        # Radius of earth in meters is 6371000
        er: int = 6371000
        return round(er * c, 3)

    def get_bearing_to_other(self, lat_other: float, lon_other: float) -> float:
        """Calculates the bearing between two points."""

        pos_own: list = self.get_current_position_global()
        lat_own: float = pos_own[0]
        lon_own: float = pos_own[1]

        return self.get_bearing(lat_own, lon_own, lat_other, lon_other)

    def get_bearing(
        self,
        lat_own: float = 0.0,
        lon_own: float = 0.0,
        lat_other: float = 0.0,
        lon_other: float = 0.0,
    ) -> float:
        """Calculates the bearing between two points."""

        if (
            lat_own
            and lat_own != 0.0
            and lon_own
            and lon_own != 0.0
            and lat_other
            and lat_other != 0.0
            and lon_other
            and lon_other != 0.0
        ):
            lat1 = math.radians(lat_own)
            lon1 = math.radians(lon_own)
            lat2 = math.radians(lat_other)
            lon2 = math.radians(lon_other)

            dlon = lon2 - lon1

            x = math.sin(dlon) * math.cos(lat2)
            y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(
                lat2
            ) * math.cos(dlon)

            initial_bearing = math.atan2(x, y)

            # Convert bearing from radians to degrees
            initial_bearing = math.degrees(initial_bearing)
            # Normalize the bearing to 0-360 degrees
            compass_bearing = (initial_bearing + 360) % 360

            if compass_bearing:
                return round(compass_bearing, 1)

        # Default is the vehicles course over ground
        return self.cog_deg

    def get_projected_position_from_me(self, time_seconds: int = 3) -> list:
        pos_own: list = self.get_current_position_global()
        lat_own: float = pos_own[0]
        lon_own: float = pos_own[1]

        return self.get_projected_position(
            lat_own, lon_own, self.sog_mps, self.cog_deg, time_seconds
        )

    def get_projected_position(
        self,
        lat: float,
        lon: float,
        speed: float,
        course: float,
        time_seconds: int = 3,
    ) -> list:
        # Convert latitude and longitude from degrees to radians
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)

        # Distance travelled in meters
        distance = speed * time_seconds

        # Convert course from degrees to radians
        course_rad = math.radians(course)

        # Earth's radius in meters
        er: int = 6371000

        # Calculate the new latitude
        new_lat_rad = math.asin(
            math.sin(lat_rad) * math.cos(distance / er)
            + math.cos(lat_rad) * math.sin(distance / er) * math.cos(course_rad)
        )

        # Calculate the new longitude
        new_lon_rad = lon_rad + math.atan2(
            math.sin(course_rad) * math.sin(distance / er) * math.cos(lat_rad),
            math.cos(distance / er) - math.sin(lat_rad) * math.sin(new_lat_rad),
        )

        # Convert the new latitude and longitude from radians to degrees
        new_lat = math.degrees(new_lat_rad)
        new_lon = math.degrees(new_lon_rad)

        return [new_lat, new_lon]

    def position_is_allowed(self):
        geofence_is_ok = (
            self.me_inside_geofence() or self.me_inside_geofence_soon()
        )
        no_go_zone_is_ok = (
            not self.me_inside_no_go_zone()
            and not self.me_inside_no_go_zone_soon()
        )

        return geofence_is_ok and no_go_zone_is_ok

    def me_inside_geofence_soon(self, secs: int = 3):
        """Check if current location is within the geofence boundary in specified seconds."""
        fut_p: list = self.get_projected_position_from_me(secs)

        return self.is_inside_geofence(fut_p[0], fut_p[1])

    def me_inside_geofence(self) -> bool:
        """Check if current location is within the geofence boundary."""
        pos_own: list = self.get_current_position_global()
        lat_own: float = pos_own[0]
        lon_own: float = pos_own[1]

        return self.is_inside_geofence(lat_own, lon_own)

    def is_inside_geofence(self, lat: float, lon: float) -> bool:
        """Check if current location is within the geofence boundary."""
        if lat and lon and self.geofence and len(self.geofence) > 0:
            return self.point_in_polygon((lat, lon), self.geofence)

        # If no geofence is found -> do not use geofence at all
        return True
        # return False

    def me_inside_no_go_zone_soon(self, secs: int = 3):
        """Check if current location is within the geofence boundary in specified seconds."""

        fut_p: list = self.get_projected_position_from_me(secs)

        return self.is_inside_no_go_zone(fut_p[0], fut_p[1])

    def me_inside_no_go_zone(self) -> bool:
        """Check if current location is within any no-fly zones."""
        pos_own: list = self.get_current_position_global()
        lat_own: float = pos_own[0]
        lon_own: float = pos_own[1]

        return self.is_inside_no_go_zone(lat_own, lon_own)

    def is_inside_no_go_zone(self, lat: float, lon: float) -> bool:
        """Check if a location is within any no-fly zones."""
        if lat and lon and self.no_go_zones and len(self.no_go_zones) > 0:
            for zone in self.no_go_zones:
                return self.point_in_polygon((lat, lon), zone)

        return False

    def point_in_polygon(self, point: list, points: list):
        """Check if a point is inside a polygon."""
        if point and points and len(points) > 0:
            return Polygon(points).contains(Point(point))

        return False

    def get_destination_position_with_bearing_and_distance(
        self, pos_from: list, bearing: float, distance: float
    ):
        if not self.validate_pos(pos_from):
            return 0.0, 0.0, 0.0

        R = 6371000  # Earth radius in meters
        bearing = math.radians(bearing)
        alt: float = pos_from[2]

        lat1 = math.radians(pos_from[0])
        lon1 = math.radians(pos_from[1])

        lat2 = math.asin(
            math.sin(lat1) * math.cos(distance / R)
            + math.cos(lat1) * math.sin(distance / R) * math.cos(bearing)
        )
        lon2 = lon1 + math.atan2(
            math.sin(bearing) * math.sin(distance / R) * math.cos(lat1),
            math.cos(distance / R) - math.sin(lat1) * math.sin(lat2),
        )

        lat2 = round(math.degrees(lat2), 7)
        lon2 = round(math.degrees(lon2), 7)
        alt = round(alt, 2)

        return (lat2, lon2, alt)

    def get_destination_position(
        self,
        pos_curr: list,
        h_distance_offset: float,
        h_angle_offset: float,
        v_distance_offset: float,
    ):
        # print(f"get_destination_position: {pos_curr=}, {h_distance_offset=}, {v_distance_offset}")

        lat: float = 0.0
        lon: float = 0.0
        alt: float = 0.0

        if self.validate_pos(pos_curr):
            lat, lon, alt = (
                self.get_destination_position_from_positions_and_offsets(
                    pos_curr,
                    self.pos_lead_old,
                    self.pos_lead_old_ts,
                    h_distance_offset,
                    h_angle_offset,
                    v_distance_offset,
                )
            )

            # Save the previous position of the leader to be able to calculate its course
            self.pos_lead_old = pos_curr
            self.pos_lead_old_ts = self.get_epoch_millis()

            if self.validate_lat_lon_alt(lat, lon, alt):
                return lat, lon, alt

        return 0.0, 0.0, 0.0

    def get_destination_position_from_positions_and_offsets(
        self,
        targ_pos_curr: list = None,
        targ_pos_old: list = None,
        targ_pos_old_ts: float = 0.0,
        h_distance_offset: float = 10.0,
        h_angle_offset: float = 0.0,
        v_distance_offset: float = 10.0,
    ):
        # print(f"get_destination_position_from_positions_and_offsets: {targ_pos_curr=}, {targ_pos_old}, {h_distance_offset=}, {v_distance_offset}")

        if targ_pos_curr is None:
            targ_pos_curr = []

        if targ_pos_old is None:
            targ_pos_old = []

        targ_course: float = self.cog_deg

        go_for_lat: float = 0.0
        go_for_lon: float = 0.0
        go_for_alt: float = 0.0

        if (
            self.validate_pos(targ_pos_curr)
            and self.validate_pos(targ_pos_old)
            and (
                targ_pos_old[0] != targ_pos_curr[0]
                or targ_pos_old[1] != targ_pos_curr[1]
                or targ_pos_old[2] != targ_pos_curr[2]
            )
        ):
            targ_course = self.get_bearing(
                targ_pos_old[0],
                targ_pos_old[1],
                targ_pos_curr[0],
                targ_pos_curr[1],
            )

        elif self.validate_pos(targ_pos_curr):
            # Default same as own cog + 180
            # Initial assumtion: The target has same course as own course
            targ_course = (180 + self.cog_deg) % 360

        # Do follow mode by calculating the wanted position only if the leader is moving
        # Prohibits wanted position to go back-and-forth depending
        # on the leader is standing relatively still and small changes in position
        # makes a calculated course in turn gives direction to wanted position.

        if (
            self.is_moving(
                targ_pos_curr,
                self.get_epoch_millis(),
                targ_pos_old,
                targ_pos_old_ts,
                0.2,
            )
            or not self.initial_pos_follow_me_sent
        ):
            self.initial_pos_follow_me_sent = True
            # if not self.is_near(targ_pos_curr, targ_pos_old, 0.1):
            targ_angle_offset = (targ_course + h_angle_offset) % 360

            go_for_lat, go_for_lon, dummy_alt = (
                self.get_destination_position_with_bearing_and_distance(
                    targ_pos_curr, targ_angle_offset, h_distance_offset
                )
            )
            go_for_alt: float = targ_pos_curr[2] + v_distance_offset
            # print(f"Result: {targ_pos_curr[2]=}, {v_distance_offset=}, {go_for_alt=}")

            return go_for_lat, go_for_lon, go_for_alt

        return 0.0, 0.0, 0.0

    def validate_pos(self, pos: list) -> bool:
        return bool(
            pos
            and len(pos) == 3
            and self.validate_lat_lon_alt(pos[0], pos[1], pos[2])
        )

    def validate_lat_lon_alt(self, lat: float, lon: float, alt: float) -> bool:
        return bool(
            lat
            and lon
            and alt
            and not (lat == 0.0 and lon == 0.0 and alt == 0.0)
        )

    def is_near(self, pos1: list, pos2: list, margin_meters: float = 1.0):
        near: bool = False
        if self.validate_pos(pos1) and self.validate_pos(pos2):
            dist: float = self.get_horizontal_distance_between_points(
                pos1[0], pos1[1], pos2[0], pos2[1]
            )

            near = bool(dist <= margin_meters)

        return near

    def is_moving(
        self,
        pos1: list,
        ts1: float,
        pos2: list,
        ts2: float,
        speed_th: float = 0.1,
    ):
        moving: bool = False

        if self.validate_pos(pos1) and self.validate_pos(pos2) and ts1 > ts2:
            dist: float = self.get_horizontal_distance_between_points(
                pos1[0], pos1[1], pos2[0], pos2[1]
            )

            period: float = ts1 - ts2
            speed: float = dist / period

            moving = bool(speed > speed_th)

        return moving

    def get_spacing_for_coverage(self, fov_degrees, altitude_relative) -> float:
        overcoverage: float = 0.2
        half_angle_rad: float = math.radians(
            fov_degrees * (1.0 - overcoverage) / 2
        )
        spacing_meters: float = 2 * altitude_relative * math.tan(half_angle_rad)
        return spacing_meters

    #  HELPERS/TESTERS =================================================================

    def get_epoch_millis(self) -> float:
        dt = datetime.now()
        # round to seconds with 3 decimal places for microsecond precision
        return round(dt.microsecond / 1000000.0, 3)

    def print_all_attributes(self) -> None:
        """Print all vehicle attributes.

        Args:
        ----
            vehicle (Vehicle): The vehicle instance.

        """
        try:
            print("\nGet all vehicle attribute values:")
            print(f" Autopilot Firmware version: {self.vehicle.version}")
            print(f"   Major version number: {self.vehicle.version.major}")
            print(f"   Minor version number: {self.vehicle.version.minor}")
            print(f"   Patch version number: {self.vehicle.version.patch}")
            print(f"   Release type: {self.vehicle.version.release_type()}")
            print(
                f"   Release version: {self.vehicle.version.release_version()}"
            )
            print(f"   Stable release?: {self.vehicle.version.is_stable()}")
            print(" Autopilot supported capabilities")
            print(
                f"   MISSION_FLOAT message type: {self.vehicle.capabilities.mission_float}"
            )
            print(
                f"   PARAM_FLOAT message type: {self.vehicle.capabilities.param_float}"
            )
            print(
                f"   MISSION_INT message type: {self.vehicle.capabilities.mission_int}"
            )
            print(
                f"   COMMAND_INT message type: {self.vehicle.capabilities.command_int}"
            )
            print(
                f"   PARAM_UNION message type: {self.vehicle.capabilities.param_union}"
            )
            print(f"   ftp for file transfers: {self.vehicle.capabilities.ftp}")
            print(
                f"   commanding attitude offboard: {self.vehicle.capabilities.set_attitude_target}"
            )
            print(
                f"   commanding position and velocity targets in local NED frame: {self.vehicle.capabilities.set_attitude_target_local_ned}"
            )
            print(
                f"   set position + velocity targets in global scaled integers: {self.vehicle.capabilities.set_altitude_target_global_int}"
            )
            print(
                f"   terrain protocol / data handling: {self.vehicle.capabilities.terrain}"
            )
            print(
                f"   direct actuator control: {self.vehicle.capabilities.set_actuator_target}"
            )
            print(
                f"   the flight termination command: {self.vehicle.capabilities.flight_termination}"
            )
            print(
                f"   mission_float message type: {self.vehicle.capabilities.mission_float}"
            )
            print(
                f"   onboard compass calibration: {self.vehicle.capabilities.compass_calibration}"
            )
            print(f" Global Location: {self.vehicle.location.global_frame}")
            print(
                f" Global Location (relative altitude): {self.vehicle.location.global_relative_frame}"
            )
            print(f" Local Location: {self.vehicle.location.local_frame}")
            print(f" Attitude: {self.vehicle.attitude}")
            print(f" Velocity: {self.vehicle.velocity}")
            print(f" GPS: {self.vehicle.gps_0}")
            print(f" Gimbal status: {self.vehicle.gimbal}")
            print(f" Battery: {self.vehicle.battery}")
            print(f" EKF OK?: {self.vehicle.ekf_ok}")
            print(f" Last Heartbeat: {self.vehicle.last_heartbeat}")
            print(f" Rangefinder: {self.vehicle.rangefinder}")
            print(f" Rangefinder distance: {self.vehicle.rangefinder.distance}")
            print(f" Rangefinder voltage: {self.vehicle.rangefinder.voltage}")
            print(f" Heading: {self.vehicle.heading}")
            print(f" Is Armable?: {self.vehicle.is_armable}")
            print(f" System status: {self.vehicle.system_status.state}")
            print(f" Groundspeed: {self.vehicle.groundspeed}")  # settable
            print(f" Airspeed: {self.vehicle.airspeed}")  # settable
            print(f" Mode: {self.vehicle.mode.name}")  # settable
            print(f" Armed: {self.vehicle.armed}")  # settable
            print(f" Clock: {self.clock}")
        except TypeError:
            return

    def decode_command_ack(self, message) -> dict:
        command_enum = mavutil.mavlink.enums["MAV_CMD"]
        result_enum = mavutil.mavlink.enums["MAV_RESULT"]

        command_str = (
            command_enum[message.command].name
            if message.command in command_enum
            else "UNKNOWN"
        )
        result_str = (
            result_enum[message.result].name
            if message.result in result_enum
            else "UNKNOWN"
        )

        human_readable_message: dict = {
            "command": command_str,
            "result": result_str,
            "progress": message.progress,
            "result_param2": message.result_param2,
            "target_system": message.target_system,
            "target_component": message.target_component,
        }
        return human_readable_message

    def print_agent_state(self) -> None:
        out = (
            f"class:{self.get_vehicle_class()}, "
            f"armable:{self.is_armable()}, "
            f"system_ready:{self.is_system_ready()}, "
            f"auto_armed:{self.is_auto_armed()}, "
            # f"armed:{self.is_armed()}, "
            # f"disarmed:{self.is_disarmed()}, "
            f"state:{self.get_state_name()}, "
            f"mode:{self.get_mode_name()}, "
            f"manual:{self.is_manual()}, "
            f"auto:{self.is_auto()}, "
            f"still:{self.is_still()}, "
            f"on_miss:{self.is_on_mission()}, "
            f"miss_done:{self.is_mission_done()}, "
            f"wanted gnd spd:{self.wanted_speed_mps}, "
            f"speed override:{self.speed_override_mps}, "
            f"actual gnd spd:{self.sog_mps}, "
            f"max spd:{self.get_max_speed()}, "
            f"grounded:{self.is_on_ground()}, "
            f"flying:{self.is_flying()}, "
        )

        print(out)
        
        
    def send_rc_override(self, left_pwm, right_pwm):
        """
        Sends RC overrides.
        Skid-steer boats: Ch 1 = left throttle, Ch 3 = right throttle.
        Values should be between 1000 and 2000.
        """
        if left_pwm is None or right_pwm is None:
            if self.is_manual():
                self.vehicle._master.mav.rc_channels_override_send(
                    self.vehicle._master.target_system,
                    self.vehicle._master.target_component,
                    0, 0, 0, 0, 0, 0, 0, 0,
                )
                print("RC Overrides released.")
                restore = self.mode_name_before_rc or "AUTO"
                if self.set_mode(restore):
                    self.apply_task_speed()
                self.mode_name_before_rc = None
            return

        if not self.is_manual():
            self.mode_name_before_rc = self.get_mode_name()
            self.set_mode("MANUAL")
            print("Set mode to MANUAL")

        self.vehicle._master.mav.rc_channels_override_send(
            self.vehicle._master.target_system,
            self.vehicle._master.target_component,
            left_pwm,
            0,
            right_pwm,
            0, 0, 0, 0, 0,
        )
        print(f"RC Overrides sent: {left_pwm=}, {right_pwm=}")
