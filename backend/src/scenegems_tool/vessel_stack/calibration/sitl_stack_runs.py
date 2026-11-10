"""Repeats of a reference run on ArduPilot Sim and Gazebo stacks in Docker (needs Docker and the simulator images).

The control layer is ardupilot (SITL per vessel) or, on Gazebo, the custom controller, whose
world is stepped by the gz-transport actuator in the Gazebo container.

The stack of every repeat is generated with the project's own builder
(simulation_docker_stack.build_simulation_docker_stack_artifacts) from a mavlink_instance,
so what is measured is what a campaign would start. This module only adapts the generated
compose file to run several repeats side by side on one host:

- the shared runtime assets volume becomes a bind mount of a folder per repeat, mounted at /runtime_assets
  (every host path in the generated files is rewritten to it);
- each SITL serial port, or the gz-transport actuator's port, is published on a host port of its own, which the run connects to;
- fixed container names and the Gazebo host port are dropped, so repeats do not collide;
- the ASV software and controller containers of the vessels are left out: the measurement runs on the host, outside the
  stack's network, and hosts those layers in its own process (vessel_stack/hosting.py, InProcessHosting). They compute
  the same commands there, but a campaign's hop from its runner to each container is not part of what is measured.

Three ways of driving an ArduPilot repeat are measured:

- replay: run_mavlink_stack with the lockstep adapter that replays the trajectory (design doc 12.8). Repeats are
  compared at equal scenario time. This is the number the resolver needs for replay_mavlink_lockstep.
- usv_navigation: run_mavlink_stack with USV Navigation toward the end of the reference over the same link
  (usv_navigation_mavlink_lockstep), compared the same way.
- target: one position target far ahead on an engaged vessel, sampled against SITL time (design doc 10.5). Repeats are
  compared from the movement onset. This isolates the simulator and ArduPilot from the follower.

A custom controller repeat is driven by run_gz_custom (gz_lockstep_runner.py) and compared at equal scenario time; its
track is the odometry of every control step. Its drive is replay (the line-of-sight waypoint follower) or usv_navigation
(USV Navigation toward the end of the reference, with nothing to avoid).

The resolver used for the run knows no stored measurements, so a speedup above today's measured limit is not refused
before it is measured.
"""

import copy
import math
import os
import re
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple
from unittest import mock

import numpy as np
import yaml

from concrete_level.models.trajectories import Trajectories
from scenegems_tool.messaging.mqtt_client import MQttConnectionInfo
from scenegems_tool.vessel_stack.asv_software.replay.replay_specs import REPLAY_MAVLINK_LOCKSTEP
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_specs import USV_NAVIGATION_MAVLINK_LOCKSTEP
from scenegems_tool.vessel_stack.calibration.measured_entry import MeasuredEntry, evidence, host_label
from scenegems_tool.vessel_stack.calibration.reference_scenarios import REFERENCE_RUNS, reference_run
from scenegems_tool.vessel_stack.calibration.repeat_analysis import DeviationSummary, TrackingSummary, TrackSamples, achieved_speedup, repeat_deviation, tracking_error
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.stack_services import is_participant_service
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_link import MavlinkLink
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_lockstep_runner import MavlinkRunResult, mavlink_instance, run_mavlink_stack
from scenegems_tool.vessel_stack.registry.catalog import build_registry
from scenegems_tool.vessel_stack.registry.resolver import StackResolver
from scenegems_tool.vessel_stack.simulation_docker_stack import build_simulation_docker_stack_artifacts
from scenegems_tool.vessel_stack.simulation_layers.ardupilot_sim.ardupilot_sim_specs import ARDUPILOT_SIM_LAYER, SITL_INTERNAL_PHYSICS
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_specs import ARDUPILOT_GAZEBO_PLUGIN, GAZEBO_LAYER, GZ_TRANSPORT_ACTUATOR
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_runner import GzRunResult, gz_custom_instance, run_gz_custom
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_transport_actuator import DEFAULT_PORT as ACTUATOR_PORT
from utils.file_system_utils import RUNTIME_ASSETS_FOLDER, RUNTIME_ASSETS_VOLUME

CONTAINER_ASSETS = "/runtime_assets"
GEOFENCE = Geofence(57.76, 16.68, 20000.0)
BASE_HOST_PORT = 15000
START_BOOT_S = 60.0  # scenario time 0 at this SITL time for every repeat, as in the Phase 2 measurements
TARGET_DISTANCE_M = 1500.0  # the Phase 0 driver sent one target this far east
GUIDED_WAIT_MS = 10_000  # SITL time allowed for the switch to GUIDED
TRACKS_SPEEDUP = 0.9  # a run tracked its request when it achieved at least this share of it
LAYERS = {"ardupilot_sim": SimulationLayerId.ARDUPILOT_SIM, "gazebo": SimulationLayerId.GAZEBO}
CONTROL_LAYERS = {"ardupilot": ControlLayerId.ARDUPILOT, "custom": ControlLayerId.CUSTOM}
ACTUATOR_ENDPOINT = "actuator"  # endpoints key of the gz-transport actuator's host:port
_LAYER_SPEC_ID = {SimulationLayerId.ARDUPILOT_SIM: ARDUPILOT_SIM_LAYER.id, SimulationLayerId.GAZEBO: GAZEBO_LAYER.id}
_PAIR_SPEC_ID = {SimulationLayerId.ARDUPILOT_SIM: SITL_INTERNAL_PHYSICS.id, SimulationLayerId.GAZEBO: ARDUPILOT_GAZEBO_PLUGIN.id}


DRIVES = ("replay", "target", "usv_navigation")


@dataclass(frozen=True)
class StackRunSpec:
    simulation_layer: SimulationLayerId
    reference: str = "straight"  # one of REFERENCE_RUNS
    scale: str = "5m"
    duration_s: int = 90
    speedup: int = 1
    repeats: int = 3
    drive: str = "replay"  # one of DRIVES
    wind: Optional[Tuple[float, float]] = None  # east, north in m/s
    from_rest: bool = False  # the reference starts at rest like the simulated vessel (tracking measurements)
    control_layer: ControlLayerId = ControlLayerId.ARDUPILOT
    waves: Optional[Tuple[float, float]] = None  # amplitude in m and period in s of regular waves travelling east

    @property
    def custom(self) -> bool:
        return self.control_layer == ControlLayerId.CUSTOM

    def label(self) -> str:
        control = "-custom" if self.custom else ""
        waves = f"-waves-{self.waves[0]:g}m-{self.waves[1]:g}s" if self.waves else ""
        return f"{self.simulation_layer.value}{control}-{self.drive}-{self.reference}{'-from-rest' if self.from_rest else ''}{waves}-{self.scale}-{self.speedup}x"


@dataclass(frozen=True)
class HullMotion:
    """Peak-to-peak hull motion over a run, from the odometry of every control step (what waves move)."""

    heave_m: float
    roll_deg: float
    pitch_deg: float

    @classmethod
    def from_odometry(cls, hulls: Sequence[Any]) -> "HullMotion":
        z = np.array([hull.z for hull in hulls])
        qx, qy, qz, qw = (np.array([getattr(hull, name) for hull in hulls]) for name in ("qx", "qy", "qz", "qw"))
        roll = np.degrees(np.arctan2(2.0 * (qw * qx + qy * qz), 1.0 - 2.0 * (qx * qx + qy * qy)))
        pitch = np.degrees(np.arcsin(np.clip(2.0 * (qw * qy - qz * qx), -1.0, 1.0)))
        return cls(heave_m=float(np.ptp(z)), roll_deg=float(np.ptp(roll)), pitch_deg=float(np.ptp(pitch)))


@dataclass
class RepeatResult:
    index: int
    track: Optional[TrackSamples] = None
    achieved_speedup: Optional[float] = None
    state_digest: Optional[str] = None
    wall_s: float = 0.0
    error: Optional[str] = None
    logs: str = ""
    tracking: Optional[TrackingSummary] = None  # replay and usv_navigation drives: how closely the vessel followed its reference
    late_commands: Optional[int] = None  # custom controller only: thrusts that missed their control step's first iteration
    motion: Optional[HullMotion] = None  # custom controller only: heave, roll and pitch from the odometry

    @property
    def ok(self) -> bool:
        return self.error is None and self.track is not None


@dataclass
class StackMeasurement:
    spec: StackRunSpec
    repeats: List[RepeatResult] = field(default_factory=list)
    deviation: Optional[DeviationSummary] = None

    @property
    def ok_repeats(self) -> List[RepeatResult]:
        return [repeat for repeat in self.repeats if repeat.ok]

    @property
    def achieved(self) -> Optional[float]:
        values = [repeat.achieved_speedup for repeat in self.ok_repeats if repeat.achieved_speedup]
        return float(min(values)) if values else None

    @property
    def tracks_request(self) -> bool:
        return self.achieved is not None and self.achieved >= TRACKS_SPEEDUP * self.spec.speedup

    @property
    def worst_tracking(self) -> Optional[TrackingSummary]:
        """The repeat that strayed furthest from the straight legs of its reference (an orbit first)."""
        summaries = [repeat.tracking for repeat in self.ok_repeats if repeat.tracking is not None]
        return max(summaries, key=lambda summary: (summary.orbited, summary.max_cross_track_m), default=None)

    @property
    def bit_identical(self) -> bool:
        """Every repeat recorded the same state digest (and, for the custom controller, no late thrust)."""
        repeats = self.ok_repeats
        digests = {repeat.state_digest for repeat in repeats}
        return len(repeats) >= 2 and len(digests) == 1 and None not in digests and all(not repeat.late_commands for repeat in repeats)

    def entries(self) -> List[MeasuredEntry]:
        """measured_capabilities.yaml entries for what this run measured (nothing when every repeat failed)."""
        if not self.ok_repeats:
            return []
        spec = self.spec
        if spec.custom:
            return [self._custom_entry()]
        layer = spec.simulation_layer
        note = evidence(
            f"{spec.drive} drive of a {spec.reference} {spec.scale} run ({spec.duration_s} s) on {layer.value} with the ardupilot control layer",
            requested=f"{spec.speedup}x",
            achieved=f"{self.achieved:.2f}x" if self.achieved else "unknown",
            repeats=len(self.ok_repeats),
            deviation_alignment=self.deviation.alignment if self.deviation else "none",
            max_deviation_m=f"{self.deviation.max_m:.3f}" if self.deviation else "n/a",
            identical_start=self.deviation.identical_prefix if self.deviation else "n/a",
        )
        entries: List[MeasuredEntry] = []
        if spec.drive in ("replay", "usv_navigation"):
            fields: Dict[str, Any] = {"evidence": note}
            if self.deviation:
                fields["deviation_bounds_m_by_layer"] = {_LAYER_SPEC_ID[layer]: {spec.speedup: self.deviation.max_m}}
            if layer == SimulationLayerId.ARDUPILOT_SIM and self.tracks_request:
                fields["max_speedup"] = float(spec.speedup)
            entries.append(MeasuredEntry(REPLAY_MAVLINK_LOCKSTEP.id if spec.drive == "replay" else USV_NAVIGATION_MAVLINK_LOCKSTEP.id, fields))
            if layer == SimulationLayerId.GAZEBO and self.tracks_request:
                entries.append(MeasuredEntry(_PAIR_SPEC_ID[layer], {"host_max_speedup": {host_label(): float(spec.speedup)}, "evidence": note}))
        else:
            fields = {"evidence": note}
            if self.deviation:
                fields["deviation_bounds_m"] = {spec.speedup: self.deviation.max_m}
            if layer == SimulationLayerId.GAZEBO and self.tracks_request:
                fields["host_max_speedup"] = {host_label(): float(spec.speedup)}
            elif layer == SimulationLayerId.ARDUPILOT_SIM and self.tracks_request:
                fields["max_speedup"] = float(spec.speedup)
            entries.append(MeasuredEntry(_PAIR_SPEC_ID[layer], fields))
        return entries

    def _custom_entry(self) -> MeasuredEntry:
        """gz_transport_actuator: the world runs as fast as the runner steps it, so the achieved pace is the host's limit."""
        spec = self.spec
        late = sum(repeat.late_commands or 0 for repeat in self.ok_repeats)
        note = evidence(
            f"{spec.drive} drive of a {spec.reference} {spec.scale} run ({spec.duration_s} s){_waves_text(spec)} on gazebo with the custom control layer",
            achieved=f"{self.achieved:.2f}x" if self.achieved else "unknown",
            repeats=len(self.ok_repeats),
            digests="identical" if self.bit_identical else "differ",
            late_commands=late,
            max_deviation_m=f"{self.deviation.max_m:.6f}" if self.deviation else "n/a",
            **self._motion_fields(),
        )
        fields: Dict[str, Any] = {"evidence": note}
        if len(self.ok_repeats) >= 2:
            fields["repeatability_tier"] = "exact" if self.bit_identical else "bounded"
            if not self.bit_identical and self.deviation:
                fields["deviation_bounds_m"] = {spec.speedup: self.deviation.max_m}
        if self.achieved:
            fields["host_max_speedup"] = {host_label(): float(self.achieved)}
        return MeasuredEntry(GZ_TRANSPORT_ACTUATOR.id, fields)

    def _motion_fields(self) -> Dict[str, str]:
        motions = [repeat.motion for repeat in self.ok_repeats if repeat.motion is not None]
        if not motions:
            return {}
        return {
            "heave_m": f"{max(motion.heave_m for motion in motions):.3f}",
            "pitch_deg": f"{max(motion.pitch_deg for motion in motions):.2f}",
            "roll_deg": f"{max(motion.roll_deg for motion in motions):.2f}",
        }


def _waves_text(spec: StackRunSpec) -> str:
    return f" in {spec.waves[0]:g} m, {spec.waves[1]:g} s waves" if spec.waves else ""


@contextmanager
def uncapped_generation() -> Iterator[StackResolver]:
    """A resolver without stored measurements, also used by the stack builder for the length of the block."""
    resolver = StackResolver(build_registry({}))
    with mock.patch("scenegems_tool.vessel_stack.simulation_docker_stack.default_resolver", lambda: resolver):
        yield resolver


def _rewrite(value: Any, replacements: Sequence[Tuple[str, str]]) -> Any:
    if isinstance(value, str):
        for old, new in replacements:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [_rewrite(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite(item, replacements) for key, item in value.items()}
    return value


def host_assets_replacements() -> List[Tuple[str, str]]:
    """Every spelling of the runtime assets folder that the generators write into files, mapped to the in-container mount."""
    spellings = [RUNTIME_ASSETS_FOLDER, RUNTIME_ASSETS_FOLDER.replace("\\", "/"), os.path.normpath(RUNTIME_ASSETS_FOLDER)]
    return [(old, CONTAINER_ASSETS) for old in sorted(set(spellings), key=len, reverse=True)]


def run_environment(spec: StackRunSpec):
    """The environment of a run: calm, with the spec's wind and its waves (travelling east, deep water)."""
    from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, WaveConfig

    environment = EnvironmentConfig.calm()
    if spec.wind is not None:
        environment.wind_vector = np.array([spec.wind[0], spec.wind[1], 0.0])
    if spec.waves is not None:
        amplitude, period = spec.waves
        phase_speed = 9.81 * period / (2.0 * math.pi)  # deep water; the direction's length is the wave speed
        environment.wave = WaveConfig(amplitude=amplitude, period=period, steepness=0.0, direction=np.array([phase_speed, 0.0]))
    return environment


def prepare_run_folder(
    spec: StackRunSpec,
    trajectories: Trajectories,
    folder: str,
    host_port: int,
    repo_entrypoints: bool = False,
) -> Tuple[str, Dict[str, str], Any]:
    """Generate the stack of one repeat under `folder`. Returns the compose file, the endpoint by agent id and the instance."""
    environment = run_environment(spec)
    asv_software = {vessel.id: AsvSoftwareId.USV_NAVIGATION for vessel in trajectories.initial_scene.vessels} if spec.drive == "usv_navigation" else None
    if spec.custom:
        instance = gz_custom_instance(trajectories, asv_software, environment=environment, speedup=spec.speedup)
    else:
        instance = mavlink_instance(trajectories, spec.simulation_layer, asv_software, environment=environment, speedup=spec.speedup)
    connection = MQttConnectionInfo(user="", password="", agent_broker="broker", client_broker="broker", port=1883, tls_connection=False, allow_certificates=False)
    pending_writes, compose = build_simulation_docker_stack_artifacts(instance, trajectories, connection, GEOFENCE, embedded_in_subsystem=True)

    replacements = host_assets_replacements()
    assets = os.path.join(folder, "runtime_assets")
    for path, content in pending_writes:
        relative = os.path.relpath(os.path.normpath(path), os.path.normpath(RUNTIME_ASSETS_FOLDER))
        target = os.path.join(assets, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as file:
            file.write(_rewrite(content, replacements))

    compose = _rewrite(copy.deepcopy(compose), replacements)
    # The measurement drives the run from this process on the host and hosts every vessel's ASV software and controller there.
    compose["services"] = {name: service for name, service in compose["services"].items() if not is_participant_service(name)}
    mount = f"{os.path.abspath(assets).replace(chr(92), '/')}:{CONTAINER_ASSETS}:ro"
    endpoints: Dict[str, str] = {}
    if spec.custom:
        endpoints[ACTUATOR_ENDPOINT] = f"127.0.0.1:{host_port}"
    else:
        for index, (agent_id, vessel) in enumerate(instance.simulated_vessels.items()):
            service = compose["services"][vessel.require_connection().agent_name]
            port_in_container = 5760 + 10 * int(agent_id)
            service["ports"] = [f"127.0.0.1:{host_port + index}:{port_in_container}"]
            endpoints[agent_id] = f"tcp:127.0.0.1:{host_port + index}"
    for service in compose["services"].values():
        service["volumes"] = [mount if volume.startswith(f"{RUNTIME_ASSETS_VOLUME}:") else volume for volume in service.get("volumes", [])]
        service.pop("container_name", None)
        if "ports" in service and service is compose["services"].get("gazebo"):
            service.pop("ports")
        if repo_entrypoints:
            _mount_repo_entrypoint(service)
    if spec.custom:
        compose["services"]["gazebo"]["ports"] = [f"127.0.0.1:{host_port}:{ACTUATOR_PORT}"]
    compose.pop("volumes", None)
    compose_file = os.path.join(folder, "compose.yml")
    with open(compose_file, "w", encoding="utf-8", newline="\n") as file:
        yaml.dump(compose, file, default_flow_style=False, sort_keys=False, width=10000)
    return compose_file, endpoints, instance


def _mount_repo_entrypoint(service: Dict[str, Any]) -> None:
    """Mount the repo's entrypoint scripts over the image copies, for images built before the scripts changed."""
    from utils.file_system_utils import GAZEBO_ENTRYPOINT_CONTAINER_PATH, GAZEBO_FOLDER, SITL_ENTRYPOINT_CONTAINER_PATH

    scripts = {"sitl": ("sitl_entrypoint.sh", SITL_ENTRYPOINT_CONTAINER_PATH), "gazebo": ("gazebo_entrypoint_prod.sh", GAZEBO_ENTRYPOINT_CONTAINER_PATH)}
    image = str(service.get("image", ""))
    key = "gazebo" if "GAZEBO_IMAGE" in image else "sitl" if "SITL_IMAGE" in image else None
    if key is None:
        return
    name, container_path = scripts[key]
    service["volumes"] = list(service.get("volumes", [])) + [f"{os.path.join(GAZEBO_FOLDER, name).replace(chr(92), '/')}:{container_path}:ro"]


class _Compose:
    def __init__(self, compose_file: str, project: str):
        self.base = ["docker", "compose", "-p", project, "-f", compose_file]

    def up(self) -> None:
        subprocess.run(self.base + ["down", "-v", "--remove-orphans"], capture_output=True)
        subprocess.run(self.base + ["up", "-d"], check=True, capture_output=True, text=True)

    def logs(self, tail: int = 40) -> str:
        return subprocess.run(self.base + ["logs", "--tail", str(tail)], capture_output=True, text=True).stdout

    def down(self) -> None:
        subprocess.run(self.base + ["down", "-v", "--remove-orphans"], capture_output=True)


def settle_time(trajectories: Trajectories) -> float:
    """Seconds after a turn before the straight-leg tracking error counts: a quarter turn at the vessel's max yaw rate, at least 20 s."""
    vessel = trajectories.initial_scene.vessels[0]
    return max(20.0, (math.pi / 2) / vessel.max_angular_speed) if vessel.max_angular_speed > 0 else 20.0


def _drive_mavlink(trajectories: Trajectories, instance, endpoints: Dict[str, str], resolver: StackResolver) -> Tuple[TrackSamples, RepeatResult]:
    result: MavlinkRunResult = run_mavlink_stack(trajectories, instance, GEOFENCE, endpoints=endpoints, start_boot_s=START_BOOT_S, resolver=resolver)
    epoch = result.epoch_boot_ms[0]
    track = TrackSamples.from_stamped([sample for sample in result.samples[0] if sample.boot_ms >= epoch], epoch)  # the run itself, not the boot
    vessel = trajectories.initial_scene.vessels[0]
    tracking = tracking_error(track, trajectories.state_list(vessel), float(trajectories.time_step), settle_time(trajectories))
    outcome = RepeatResult(index=-1, track=track, achieved_speedup=result.achieved_speedup, state_digest=result.state_digest(), wall_s=result.wall_s, tracking=tracking)
    return track, outcome


def _drive_gz_custom(trajectories: Trajectories, instance, endpoints: Dict[str, str], resolver: StackResolver) -> RepeatResult:
    host, port = endpoints[ACTUATOR_ENDPOINT].rsplit(":", 1)
    result: GzRunResult = run_gz_custom(trajectories, instance, host=host, port=int(port), resolver=resolver)
    hulls = [step[0] for step in result.odometry]
    track = TrackSamples(
        time_s=np.arange(len(hulls)) * result.control_dt,
        x=np.array([hull.x for hull in hulls]),
        y=np.array([hull.y for hull in hulls]),
        speed=np.array([hull.speed for hull in hulls]),
        wall_span_s=result.wall_s,
        heading=np.array([hull.heading for hull in hulls]),
    )
    vessel = trajectories.initial_scene.vessels[0]
    tracking = tracking_error(track, trajectories.state_list(vessel), float(trajectories.time_step), settle_time(trajectories))
    return RepeatResult(
        index=-1,
        track=track,
        achieved_speedup=result.achieved_speedup,
        state_digest=result.state_digest(),
        wall_s=result.wall_s,
        tracking=tracking,
        late_commands=result.late_commands,
        motion=HullMotion.from_odometry(hulls),
    )


def _drive_target(spec: StackRunSpec, endpoint: str) -> RepeatResult:
    """Engage the vessel, send one position target far east, and sample it against SITL time for the run's duration.

    The track starts at the target: samples streamed while the vessel booted and armed are left out, and time is
    seconds of SITL time since the target was sent.
    """
    link = MavlinkLink(endpoint, 0, GEOFENCE)
    try:
        link.connect(600.0)
        link.wait_until_ready(600.0)
        link.engage(300.0)
        # GUIDED is refused until the estimator has settled (the replay path waits for the same SITL time).
        while (link.boot_ms or 0) < START_BOOT_S * 1000:
            link.poll(1.0)
        link.send_position_target((TARGET_DISTANCE_M, 0.0), link.boot_ms or 0)
        # The switch from HOLD to GUIDED clears the target of a vessel that has just entered the mode, so the
        # target is sent again once a heartbeat reports GUIDED.
        mode_deadline = (link.boot_ms or 0) + GUIDED_WAIT_MS
        while not link.in_guided and (link.boot_ms or 0) < mode_deadline:
            link.poll(1.0)
        start_boot = link.boot_ms or 0
        link.send_position_target((TARGET_DISTANCE_M, 0.0), start_boot)
        first_sample = len(link.samples)
        wall_start = time.monotonic()
        wall_deadline = wall_start + spec.duration_s / max(spec.speedup, 1) * 4 + 420
        while link.boot_ms is None or (link.boot_ms - start_boot) / 1000.0 < spec.duration_s:
            if time.monotonic() > wall_deadline:
                return RepeatResult(index=-1, error="the run did not reach its duration before the wall-clock timeout")
            link.poll(2.0)
        wall_span = time.monotonic() - wall_start
        track = TrackSamples.from_stamped(link.samples[first_sample:], start_boot)
        track = TrackSamples(track.time_s, track.x, track.y, track.speed, wall_span_s=wall_span, heading=track.heading)
        return RepeatResult(index=-1, track=track, achieved_speedup=achieved_speedup(track), wall_s=wall_span)
    finally:
        link.close()


def _validate(spec: StackRunSpec) -> None:
    if spec.reference not in REFERENCE_RUNS:
        raise ValueError(f"Unknown reference run '{spec.reference}'; expected one of {', '.join(REFERENCE_RUNS)}")
    if spec.drive not in DRIVES:
        raise ValueError(f"Unknown drive '{spec.drive}'; expected one of {', '.join(DRIVES)}")
    if spec.simulation_layer not in (SimulationLayerId.ARDUPILOT_SIM, SimulationLayerId.GAZEBO):
        raise ValueError(f"Docker measurements need ardupilot_sim or gazebo, got {spec.simulation_layer.value}")
    if spec.custom and (spec.simulation_layer != SimulationLayerId.GAZEBO or spec.drive == "target"):
        raise ValueError("the custom controller runs on gazebo with the replay or usv_navigation drive")


def compose_project_name(spec: StackRunSpec, index: int) -> str:
    """The Compose project of one repeat: its label in the characters Compose allows (a wave amplitude of 0.5 m has a dot)."""
    return re.sub(r"[^a-z0-9-]", "-", f"calib-{spec.label()}-{index}".lower())


def _run_repeat(spec: StackRunSpec, trajectories: Trajectories, prepared: Tuple[str, Dict[str, str], Any], index: int, resolver: StackResolver, keep_stacks: bool) -> RepeatResult:
    """Start one copy of the stack, drive it, and remove it. A failure is returned as data with the container logs."""
    compose_file, endpoints, instance = prepared
    compose = _Compose(compose_file, compose_project_name(spec, index))
    try:
        compose.up()
        if spec.custom:
            outcome = _drive_gz_custom(trajectories, instance, endpoints, resolver)
        elif spec.drive in ("replay", "usv_navigation"):
            _, outcome = _drive_mavlink(trajectories, instance, endpoints, resolver)
        else:
            outcome = _drive_target(spec, endpoint=endpoints["0"])
    except Exception as error:
        outcome = RepeatResult(index=index, error=f"{type(error).__name__}: {error}", logs=compose.logs())
    outcome.index = index
    if not keep_stacks:
        compose.down()
    return outcome


def measure_stack(
    spec: StackRunSpec,
    work_folder: str,
    base_host_port: int = BASE_HOST_PORT,
    repo_entrypoints: bool = False,
    keep_stacks: bool = False,
) -> StackMeasurement:
    """Start spec.repeats copies of the stack side by side, drive each, and compare the tracks.

    work_folder receives one folder per repeat with its generated files and compose file. Containers are removed
    afterwards unless keep_stacks is set. A repeat that fails is recorded with its error and the container logs.
    """
    _validate(spec)
    trajectories = reference_run(spec.reference, spec.scale, spec.duration_s, spec.from_rest)
    measurement = StackMeasurement(spec=spec)
    with uncapped_generation() as resolver:
        prepared = []
        for index in range(spec.repeats):
            folder = os.path.join(work_folder, f"{spec.label()}-{index}")
            os.makedirs(folder, exist_ok=True)
            prepared.append(prepare_run_folder(spec, trajectories, folder, base_host_port + 10 * index, repo_entrypoints))
        results: Dict[int, RepeatResult] = {}

        def run(index: int) -> None:
            results[index] = _run_repeat(spec, trajectories, prepared[index], index, resolver, keep_stacks)

        threads = [threading.Thread(target=run, args=(index,)) for index in range(spec.repeats)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    measurement.repeats = [results[index] for index in sorted(results)]
    tracks = [repeat.track for repeat in measurement.ok_repeats if repeat.track is not None]
    if len(tracks) >= 2:
        measurement.deviation = repeat_deviation(tracks, "onset" if spec.drive == "target" else "scenario_time")
    return measurement
