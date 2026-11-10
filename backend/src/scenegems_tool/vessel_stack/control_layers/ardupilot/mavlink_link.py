"""Clock-stepped MAVLink link to one ArduPilot SITL vessel, the runtime of adapter replay_mavlink_lockstep.

The link carries the heading_speed_cmd of an in-process ASV system into the ardupilot
control layer and reports vessel states and the clock back. It never paces itself on the
wall clock: every streamed message carries SITL's own time (time_boot_ms), and the lockstep
runner (mavlink_lockstep_runner.py) acts when that time crosses a simulation-time step
boundary. Wall time is used only for connection, readiness and step timeouts.

The vessel is armed in HOLD and switched to GUIDED with its first command. An armed boat
in GUIDED without a target loiters, and with the generated hull parameters loiter spins it
around its start point, so every repeat would start from a different state (WP4 finding).

SITL keeps running while a command travels to it, so a command takes effect a few wall
milliseconds, times the speedup, after its boundary. Stepping on SITL time removes the
dependence on a wall-clock timer in SceneGEMS, not that latency (design doc 12.8).
"""

import math
import socket
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from haversine import Unit
from pymavlink import mavutil

from concrete_level.models.actor_state import ActorState
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence, from_true_north, to_true_north
from utils.math_utils import heading_diff, rotate_heading

ROVER_HOLD_MODE = 4  # Rover custom_mode of HOLD: throttle and steering exactly 0
ROVER_GUIDED_MODE = 15  # Rover custom_mode of GUIDED
# Early-boot heartbeats can report armed and mode 15 before ArduPilot is usable (Phase 0), so
# readiness is this EKF message, and arming state is read only from later heartbeats.
EKF_READY_TEXT = "EKF3 IMU0 is using GPS"
SITL_SERIAL0_BASE_PORT = 5760  # SITL instance i listens on 5760 + 10 * i and boots only after a client connects
GCS_SYSTEM_ID = 245
GUIDED_TARGET_TIMEOUT_S = 3.0  # Rover drops a GUIDED target older than this, so commands must come faster
_FORCE_ARM_MAGIC = 21196  # arming checks are covered by the EKF gate; a SITL boat fails some RC checks
_RETRY_INTERVAL_MS = 2000  # in SITL time
_UNKNOWN_HEADING = 65535

_IGNORE_POSITION = mavutil.mavlink.POSITION_TARGET_TYPEMASK_X_IGNORE | mavutil.mavlink.POSITION_TARGET_TYPEMASK_Y_IGNORE | mavutil.mavlink.POSITION_TARGET_TYPEMASK_Z_IGNORE
_IGNORE_VELOCITY = mavutil.mavlink.POSITION_TARGET_TYPEMASK_VX_IGNORE | mavutil.mavlink.POSITION_TARGET_TYPEMASK_VY_IGNORE | mavutil.mavlink.POSITION_TARGET_TYPEMASK_VZ_IGNORE
_IGNORE_ACCELERATION = mavutil.mavlink.POSITION_TARGET_TYPEMASK_AX_IGNORE | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AY_IGNORE | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AZ_IGNORE
_IGNORE_YAW = mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_IGNORE
_IGNORE_YAW_RATE = mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_RATE_IGNORE
# Rover GUIDED takes yaw as the heading and the velocity length as the speed. vx carries the
# speed and vy is 0, because Rover reverses when vx is negative.
HEADING_SPEED_TYPE_MASK = _IGNORE_POSITION | _IGNORE_ACCELERATION | _IGNORE_YAW_RATE
POSITION_TYPE_MASK = _IGNORE_VELOCITY | _IGNORE_ACCELERATION | _IGNORE_YAW | _IGNORE_YAW_RATE


def sitl_mavlink_endpoint(host: str, vessel_id: int) -> str:
    """SERIAL0 of a vessel's SITL instance (SITL_INSTANCE is the vessel id)."""
    return f"tcp:{host}:{SITL_SERIAL0_BASE_PORT + 10 * int(vessel_id)}"


class MavlinkLinkError(RuntimeError):
    pass


@dataclass(frozen=True)
class StampedState:
    """A vessel state in the local frame, stamped with SITL time."""

    boot_ms: int
    state: ActorState


class MavlinkLink:
    """MAVLink connection to one SITL instance, read and written only at simulation-time instants."""

    def __init__(self, endpoint: str, vessel_id: int, reference_geofence: Geofence, *, stream_interval_s: float = 0.04, source_system: int = GCS_SYSTEM_ID):
        self.endpoint = endpoint
        self.vessel_id = int(vessel_id)
        self.participant_id = f"mavlink/{self.vessel_id}"
        self.reference_geofence = reference_geofence
        self.stream_interval_s = stream_interval_s
        self.source_system = source_system
        self.samples: List[StampedState] = []  # every GLOBAL_POSITION_INT, in arrival (and SITL time) order
        self.status_texts: List[Tuple[Optional[int], str]] = []  # (SITL time, text)
        self.engaged_boot_ms: Optional[int] = None
        self._connection: Any = None
        self._boot_ms: Optional[int] = None
        self._ekf_ready = False
        self._armed = False
        self._custom_mode: Optional[int] = None
        self._cursor = 0
        self._last_attempt_ms: Optional[int] = None
        self._guided_requested = False

    # Connection, readiness and arming

    def connect(self, timeout_s: float = 300.0) -> None:
        """Connect and wait for the first heartbeat. SITL may still be starting, so connection errors are retried."""
        deadline = time.monotonic() + timeout_s
        last_error: Optional[BaseException] = None
        while time.monotonic() < deadline:
            connection = None
            try:
                connection = mavutil.mavlink_connection(self.endpoint, source_system=self.source_system, autoreconnect=False)
                heartbeat = connection.wait_heartbeat(timeout=min(5.0, max(0.1, deadline - time.monotonic())))
                if heartbeat is not None:
                    # pymavlink leaves target_component at 0 (broadcast); address the autopilot itself.
                    connection.target_component = heartbeat.get_srcComponent()
                    self._connection = connection
                    break
            except (OSError, socket.error) as error:
                last_error = error
            if connection is not None:
                connection.close()
            time.sleep(1.0)
        if self._connection is None:
            raise MavlinkLinkError(f"{self.endpoint}: no heartbeat within {timeout_s:g} s (last error: {last_error})")
        self._send_gcs_heartbeat()
        self._request_streams()

    def wait_until_ready(self, timeout_s: float = 600.0) -> None:
        """Wait for the EKF to use GPS; only then are GUIDED targets accepted (they need the EKF origin)."""
        deadline = time.monotonic() + timeout_s
        while not self._ekf_ready:
            if time.monotonic() > deadline:
                raise MavlinkLinkError(f"{self.endpoint}: '{EKF_READY_TEXT}' not seen within {timeout_s:g} s; last texts: {self.status_texts[-5:]}")
            self.poll(1.0)
        # Parameters loaded during boot can reset the stream rates, so ask again now.
        self._request_streams()

    def engage(self, timeout_s: float = 300.0) -> int:
        """Arm in HOLD and return the SITL time when confirmed. The first command switches to GUIDED."""
        self.begin_engagement()
        deadline = time.monotonic() + timeout_s
        while not self.advance_engagement():
            if time.monotonic() > deadline:
                raise MavlinkLinkError(f"{self.endpoint}: not armed in HOLD within {timeout_s:g} s (armed={self._armed}, mode={self._custom_mode})")
            self.poll(0.5)
        return int(self.engaged_boot_ms or 0)

    def begin_engagement(self) -> None:
        if not self._ekf_ready:
            raise MavlinkLinkError(f"{self.endpoint}: engagement before the EKF is ready")
        # Forget the arming state of early heartbeats; only heartbeats from now on count.
        self._armed = False
        self._custom_mode = None
        self._last_attempt_ms = None
        self._guided_requested = False
        self.engaged_boot_ms = None

    def advance_engagement(self) -> bool:
        """One non-blocking step toward armed in HOLD, retried every 2 s of SITL time. True once engaged."""
        now_ms = self._boot_ms or 0
        if self._armed and self._custom_mode == ROVER_HOLD_MODE:
            if self.engaged_boot_ms is None:
                self.engaged_boot_ms = now_ms
            return True
        if self._last_attempt_ms is None or now_ms - self._last_attempt_ms >= _RETRY_INTERVAL_MS:
            self._last_attempt_ms = now_ms
            connection = self._require_connection()
            if self._custom_mode != ROVER_HOLD_MODE:
                connection.mav.set_mode_send(connection.target_system, mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, ROVER_HOLD_MODE)
            else:
                connection.mav.command_long_send(connection.target_system, connection.target_component, mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 0, 1, _FORCE_ARM_MAGIC, 0, 0, 0, 0, 0)
        return False

    @property
    def in_guided(self) -> bool:
        """The latest heartbeat reports armed in GUIDED."""
        return self._armed and self._custom_mode == ROVER_GUIDED_MODE

    # Simulated time and states

    @property
    def boot_ms(self) -> Optional[int]:
        """Latest SITL time seen on this link."""
        return self._boot_ms

    def fileno(self) -> int:
        return self._require_connection().port.fileno()

    def poll(self, timeout_s: float) -> bool:
        """Wait up to timeout_s for data, then handle everything that arrived. True when a message was handled."""
        connection = self._require_connection()
        message = connection.recv_match(blocking=True, timeout=timeout_s)
        if message is None:
            return False
        self._handle(message)
        self.drain()
        return True

    def drain(self) -> int:
        """Handle every message already received, without waiting. Returns the number of messages."""
        connection = self._require_connection()
        count = 0
        while True:
            message = connection.recv_match(blocking=False)
            if message is None:
                return count
            self._handle(message)
            count += 1

    def first_sample_at(self, boot_ms: int) -> Optional[StampedState]:
        """The first state sample stamped at or after boot_ms, or None until one arrived.

        Which sample that is depends only on SITL time, not on when it was read. Samples
        before it are skipped for later calls, so boundaries must be asked in order.
        """
        while self._cursor < len(self.samples) and self.samples[self._cursor].boot_ms < boot_ms:
            self._cursor += 1
        return self.samples[self._cursor] if self._cursor < len(self.samples) else None

    def state_at(self, boot_ms: int) -> Optional[StampedState]:
        """The state at exactly boot_ms, interpolated between the samples around it, or None until a later sample arrived.

        Samples come every second scheduler loop, in a phase set by when ArduPilot handled the
        stream request, which is wall-timed. Interpolating to the boundary leaves only the
        curvature within one sample interval of that phase in the observation.
        """
        after = self.first_sample_at(boot_ms)
        if after is None:
            return None
        if after.boot_ms == boot_ms or self._cursor == 0:
            return StampedState(boot_ms=boot_ms, state=after.state)
        before = self.samples[self._cursor - 1]
        fraction = (boot_ms - before.boot_ms) / (after.boot_ms - before.boot_ms)
        a, b = before.state, after.state
        state = ActorState(
            x=a.x + (b.x - a.x) * fraction,
            y=a.y + (b.y - a.y) * fraction,
            speed=a.speed + (b.speed - a.speed) * fraction,
            heading=rotate_heading(a.heading, heading_diff(b.heading, a.heading) * fraction),
        )
        return StampedState(boot_ms=boot_ms, state=state)

    # Commands

    def send_heading_speed(self, command: HeadingSpeedCommand, boot_ms: int = 0) -> None:
        """GUIDED heading and speed target. Heading is in the SceneGEMS local frame (radians, counterclockwise from east).

        The first target is preceded by the switch from HOLD to GUIDED, on the same stream, so
        ArduPilot handles both in order.
        """
        connection = self._require_connection()
        if not self._guided_requested:
            connection.mav.set_mode_send(connection.target_system, mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, ROVER_GUIDED_MODE)
            self._guided_requested = True
        yaw = _wrap_pi(to_true_north(command.heading))
        connection.mav.set_position_target_local_ned_send(
            int(boot_ms) & 0xFFFFFFFF,
            connection.target_system,
            connection.target_component,
            mavutil.mavlink.MAV_FRAME_LOCAL_NED,
            HEADING_SPEED_TYPE_MASK,
            0,
            0,
            0,
            max(0.0, float(command.speed)),
            0,
            0,
            0,
            0,
            0,
            yaw,
            0,
        )

    def send_position_target(self, position_xy: Tuple[float, float], boot_ms: int = 0) -> None:
        """GUIDED position target in the local frame; ArduPilot drives there at its waypoint speed."""
        connection = self._require_connection()
        if not self._guided_requested:
            connection.mav.set_mode_send(connection.target_system, mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED, ROVER_GUIDED_MODE)
            self._guided_requested = True
        latitude, longitude = self.reference_geofence.to_lat_long((float(position_xy[0]), float(position_xy[1])))
        connection.mav.set_position_target_global_int_send(
            int(boot_ms) & 0xFFFFFFFF,
            connection.target_system,
            connection.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_INT,
            POSITION_TYPE_MASK,
            int(round(latitude * 1e7)),
            int(round(longitude * 1e7)),
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> "MavlinkLink":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # Internals

    def _require_connection(self) -> Any:
        if self._connection is None:
            raise MavlinkLinkError(f"{self.endpoint}: not connected")
        return self._connection

    def _send_gcs_heartbeat(self) -> None:
        # ArduPilot sends status texts only on channels that have received MAVLink.
        self._connection.mav.heartbeat_send(mavutil.mavlink.MAV_TYPE_GCS, mavutil.mavlink.MAV_AUTOPILOT_INVALID, 0, 0, 0)

    def _request_streams(self) -> None:
        """State samples every stream_interval_s of SITL time. ArduPilot refuses intervals shorter than
        1.25 scheduler loops (25 ms at Rover's 50 Hz), and sends on loop ticks, so 40 ms is every second loop."""
        connection = self._require_connection()
        for message_id, interval_s in ((mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT, self.stream_interval_s), (mavutil.mavlink.MAVLINK_MSG_ID_SYSTEM_TIME, 1.0)):
            connection.mav.command_long_send(connection.target_system, connection.target_component, mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL, 0, message_id, interval_s * 1e6, 0, 0, 0, 0, 0)

    def _handle(self, message: Any) -> None:
        message_type = message.get_type()
        if message_type == "BAD_DATA" or message.get_srcSystem() != self._connection.target_system:
            return
        boot_ms = getattr(message, "time_boot_ms", None)
        if boot_ms is not None and (self._boot_ms is None or boot_ms > self._boot_ms):
            self._boot_ms = int(boot_ms)
        if message_type == "GLOBAL_POSITION_INT":
            self.samples.append(StampedState(boot_ms=int(message.time_boot_ms), state=self._state_from(message)))
        elif message_type == "HEARTBEAT":
            if message.get_srcComponent() == self._connection.target_component and self._ekf_ready:
                self._armed = bool(message.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
                self._custom_mode = int(message.custom_mode)
        elif message_type == "STATUSTEXT":
            self.status_texts.append((self._boot_ms, message.text))
            if EKF_READY_TEXT in message.text:
                self._ekf_ready = True

    def _state_from(self, message: Any) -> ActorState:
        position = self.reference_geofence.to_coord(message.lat / 1e7, message.lon / 1e7)
        north, east = message.vx / 100.0, message.vy / 100.0
        if message.hdg != _UNKNOWN_HEADING:
            true_north_deg = message.hdg / 100.0
        else:
            true_north_deg = math.degrees(math.atan2(east, north)) % 360.0
        heading = math.radians(from_true_north(true_north_deg, unit=Unit.DEGREES))
        return ActorState(x=float(position[0]), y=float(position[1]), speed=math.hypot(north, east), heading=heading)


def _wrap_pi(angle: float) -> float:
    return (angle + math.pi) % (2.0 * math.pi) - math.pi
