"""The custom control layer on the real Gazebo image: the autopilot holds a speed and turns onto new headings through the actuator, for each steering type.

Three 30 m vessels, skid steered, with a rudder and with vectored thrust, lie side by side in one flat world. The
Gazebo container starts as a job's does (gazebo_entrypoint_prod.sh: the world paused, the gz-transport actuator
listening), and this process is the runner: run_gz_lockstep steps the world through GzLockstepLink, with a
TwinThrustAutopilot per vessel and a heading schedule in place of an ASV system. Each vessel speeds up from rest
on its heading, turns 60 degrees to port and turns back to starboard.

The image holds the gz_transport_actuator.py it was built with. The test mounts the source file of this checkout
over it (/scripts/gz_transport_actuator.py), so it checks the actuator as it is here without a rebuild of the image.

Needs Docker and the Gazebo image (./build.sh --simulation): pytest -m docker.
"""

import contextlib
import dataclasses
import math
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

import numpy as np
import pytest

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from scenegems_tool.vessel_stack.calibration.reference_scenarios import VESSEL_SCALES, scaled_vessel
from scenegems_tool.vessel_stack.contracts.clock import StepRequest
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand, VesselStateObservation
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
from scenegems_tool.vessel_stack.control_layers.custom.twin_thrust_autopilot import AutopilotGains, TwinThrustAutopilot
from scenegems_tool.vessel_stack.simulation_layers.gazebo import gz_transport_actuator
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_specs import GAZEBO_CONTAINER
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import VesselDynamics, derive_vessel_dynamics
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_generator import generate_hull_mesh, generate_vessel_model, hull_mesh_filename
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.world_generator import generate_world
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_link import GzLockstepLink, HullOdometry
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_runner import CONTROL_DT_S, GzRunResult, run_gz_lockstep, thruster_constants
from utils.math_utils import heading_diff

pytestmark = [pytest.mark.docker, pytest.mark.slow]

IMAGE = GAZEBO_CONTAINER.default_image
ACTUATOR_SOURCE = Path(gz_transport_actuator.__file__)
ACTUATOR_IN_IMAGE = "/scripts/gz_transport_actuator.py"
ENTRYPOINT_IN_IMAGE = "/scripts/entrypoint.sh"
MOUNT = "/w"
SCALE = "30m"
STEERING_TYPES = ("skid", "rudder", "vectored_thrust")
CRUISE = VESSEL_SCALES[SCALE].cruise_speed
TURN = math.radians(60.0)
STRAIGHT_S, TURN_S = 60, 150  # speeding up on the first heading; each of the two turns and the run on the new heading
LEGS = ((0.0, 0.0), (float(STRAIGHT_S), TURN), (float(STRAIGHT_S + TURN_S), 0.0))  # (start time, heading)
STEPS = STRAIGHT_S + 2 * TURN_S
SETTLED_DEG = 2.0  # a turn counts as settled from the last time the heading is farther than this from the commanded one
CONNECT_TIMEOUT_S = 240.0


class HeadingSchedule:
    """Lockstep participant that commands the heading of the current leg and the cruise speed."""

    def __init__(self, vessel: ConcreteVessel):
        self.participant_id = f"schedule/{vessel.id}"

    def start(self, seed: int) -> None:
        del seed

    def on_step(self, request: StepRequest, observation: VesselStateObservation) -> HeadingSpeedCommand:
        return HeadingSpeedCommand(heading=[heading for start, heading in LEGS if start <= request.time][-1], speed=CRUISE)


@dataclass(frozen=True)
class Leg:
    """What one vessel did on one leg, from the odometry of every control step."""

    heading_error_deg: float  # at the leg's end, mean of its last 10 s
    overshoot_deg: float  # how far the heading went past the commanded one
    settle_s: float  # from the leg's start to the last time the heading was SETTLED_DEG off
    speed_error: float  # m/s at the leg's end, mean of its last 10 s
    heading_span_deg: float  # how much the heading still moved in the leg's last 30 s
    peak_turn_rate: float  # rad/s


@dataclass(frozen=True)
class Run:
    folder: Path
    result: GzRunResult
    dynamics: Dict[str, VesselDynamics]  # by steering type
    legs: Dict[str, Tuple[Leg, ...]]  # by steering type
    log: str


def docker_is_available() -> bool:
    return shutil.which("docker") is not None and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def leg_of(track: List[HullOdometry], start_s: float, end_s: float, heading: float, previous_heading: float) -> Leg:
    per_second = int(round(1.0 / CONTROL_DT_S))
    samples = track[int(start_s * per_second) : int(end_s * per_second) + 1]
    errors = [math.degrees(heading_diff(heading, sample.heading)) for sample in samples]  # positive: the commanded heading is to port of the hull
    direction = 1.0 if heading_diff(heading, previous_heading) >= 0.0 else -1.0  # the way of the turn onto this leg
    unsettled = [index for index, error in enumerate(errors) if abs(error) > SETTLED_DEG]
    last = samples[-10 * per_second :]
    span = errors[-30 * per_second :]
    return Leg(
        heading_error_deg=sum(errors[-10 * per_second :]) / (10 * per_second),
        overshoot_deg=max(0.0, max(-direction * error for error in errors)),
        settle_s=(unsettled[-1] + 1) / per_second if unsettled else 0.0,
        speed_error=sum(sample.surge for sample in last) / len(last) - CRUISE,
        heading_span_deg=max(span) - min(span),
        peak_turn_rate=max(abs(sample.yaw_rate) for sample in samples),
    )


def write_world(folder: Path, steering_types: Tuple[str, ...]) -> Tuple[Dict[int, ConcreteVessel], Dict[int, str], Dict[int, VesselDynamics]]:
    """The models, hull meshes and world of one vessel per steering type, side by side at rest heading east; (vessels, model names, dynamics) by vessel id."""
    vessels: Dict[int, ConcreteVessel] = {}
    models: Dict[int, str] = {}
    dynamics: Dict[int, VesselDynamics] = {}
    includes = []
    for index, steering in enumerate(steering_types):
        vessel = dataclasses.replace(scaled_vessel(SCALE, vessel_id=index, is_os=index == 0), _steering_type=steering)
        name = f"agent_{index}"
        vessels[index], models[index], dynamics[index] = vessel, name, derive_vessel_dynamics(vessel, 0.0, {})
        (folder / f"{name}_model.sdf").write_text(generate_vessel_model(vessel, name, ControlLayerId.CUSTOM, overrides={}), encoding="utf-8", newline="\n")
        (folder / hull_mesh_filename(name)).write_text(generate_hull_mesh(vessel, name, overrides={}), encoding="utf-8", newline="\n")
        includes.append((f"{MOUNT}/{name}_model.sdf", ActorState(x=0.0, y=index * 40.0 * vessel.length, speed=0.0, heading=0.0)))
    calm = EnvironmentConfig.calm()
    world = generate_world(np.array([58.0, 10.0]), includes, calm.wind_vector, calm.wave, 1, headless=True, wave_forces=False, externally_stepped=True)
    (folder / "ocean_world.sdf").write_text(world, encoding="utf-8", newline="\n")
    return vessels, models, dynamics


@contextlib.contextmanager
def gazebo_with_actuator(folder: Path) -> Iterator[GzLockstepLink]:
    """A Gazebo container on the folder's world, paused, with this checkout's actuator; yields the connected link. gazebo.log gets the container's output."""
    container = f"scenegems-custom-control-{uuid.uuid4().hex[:12]}"
    # As the stack's Gazebo service starts it: the entrypoint with its line ends cleaned, the world paused, the actuator listening.
    start = f"tr -d '\\r' < {ENTRYPOINT_IN_IMAGE} > /tmp/entrypoint.sh && chmod +x /tmp/entrypoint.sh && exec /tmp/entrypoint.sh"
    command = ["docker", "run", "-d", "--name", container, "-p", f"127.0.0.1::{gz_transport_actuator.DEFAULT_PORT}"]
    command += ["-v", f"{folder}:{MOUNT}", "-v", f"{ACTUATOR_SOURCE}:{ACTUATOR_IN_IMAGE}:ro"]
    command += ["-e", "GZ_HEADLESS=1", "-e", "GZ_VERBOSE=2", "-e", "GZ_START_PAUSED=1", "-e", f"GZ_ACTUATOR_PORT={gz_transport_actuator.DEFAULT_PORT}", "-e", f"WORLD_SDF={MOUNT}/ocean_world.sdf"]
    # A gz-transport partition of its own: on Docker's default network another Gazebo container (another test's, with the
    # same world and model names) would otherwise answer this one's requests and publish into its topics.
    command += ["-e", f"GZ_PARTITION={container}"]
    command += [IMAGE, "bash", "-c", start]
    started = subprocess.run(command, capture_output=True, text=True)
    if started.returncode != 0:
        pytest.fail(f"docker run of {IMAGE} failed: {started.stderr[-2000:]}")
    try:
        published = subprocess.run(["docker", "port", container, str(gz_transport_actuator.DEFAULT_PORT)], capture_output=True, text=True, check=True).stdout
        link = GzLockstepLink("127.0.0.1", int(published.strip().splitlines()[0].rsplit(":", 1)[1]))
        try:
            link.connect(CONNECT_TIMEOUT_S)
            yield link
        finally:
            link.close()
    finally:
        logs = subprocess.run(["docker", "logs", container], capture_output=True, text=True, errors="replace")
        (folder / "gazebo.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
        subprocess.run(["docker", "rm", "-f", container], capture_output=True)


@pytest.fixture(scope="module")
def run(tmp_path_factory) -> Run:
    if not docker_is_available():
        pytest.skip("Docker is not available")
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode != 0:
        pytest.skip(f"the Gazebo image {IMAGE} is not built (./build.sh --simulation)")

    folder = tmp_path_factory.mktemp("custom_control")
    vessels, models, dynamics = write_world(folder, STEERING_TYPES)
    with gazebo_with_actuator(folder) as link:
        participants = {index: HeadingSchedule(vessel) for index, vessel in vessels.items()}
        autopilots = {index: TwinThrustAutopilot(AutopilotGains.from_dynamics(dynamics[index], vessel, CONTROL_DT_S)) for index, vessel in vessels.items()}
        thrusters = {index: thruster_constants(dynamics[index]) for index in vessels}
        result = run_gz_lockstep(link, models, participants, autopilots, vessels, thrusters, 1.0, STEPS, run_seed=1)
    log = (folder / "gazebo.log").read_text(encoding="utf-8")

    legs: Dict[str, Tuple[Leg, ...]] = {}
    bounds = [start for start, _ in LEGS] + [float(STEPS)]
    for index, steering in enumerate(STEERING_TYPES):
        track = [step[index] for step in result.odometry]
        legs[steering] = tuple(leg_of(track, bounds[leg], bounds[leg + 1], heading, LEGS[leg - 1][1] if leg else 0.0) for leg, (_, heading) in enumerate(LEGS))
    print(f"\nCustom control in {IMAGE} (files in {folder}): {result.steps} s at {result.achieved_speedup:.1f} times real time, {result.late_commands} late commands")
    for steering, vessel_legs in legs.items():
        for label, leg in zip(("straight from rest", "60 degrees to port", "60 degrees to starboard"), vessel_legs):
            print(
                f"  {steering:15s} {label:23s}: heading error {leg.heading_error_deg:+.3f} deg, overshoot {leg.overshoot_deg:.3f} deg, within {SETTLED_DEG:g} deg after {leg.settle_s:5.1f} s,"
                f" speed error {leg.speed_error:+.3f} m/s, heading span of the last 30 s {leg.heading_span_deg:.3f} deg, peak turn rate {leg.peak_turn_rate:.4f} rad/s"
            )
    return Run(folder, result, {steering: dynamics[index] for index, steering in enumerate(STEERING_TYPES)}, legs, log)


def test_the_run_covers_the_three_steering_types(run):
    assert list(run.legs) == list(STEERING_TYPES)
    assert run.result.steps == STEPS and len(run.result.odometry) == STEPS * int(round(1.0 / CONTROL_DT_S)) + 1


def test_next_to_no_thrust_command_was_late(run):
    """The barrier before each step holds for one thruster and a helm as for two thrusters.

    None is late on an idle machine. On a loaded one a thrust message now and then reaches gz sim after the
    barrier (one in a run was seen with other containers at work), so the bound is not zero.
    """
    assert (
        run.result.late_commands <= 3
    ), f"{run.result.late_commands} late thrusts in {STEPS * 10} control steps of {sum(len(thruster_constants(d)['thrusters']) for d in run.dynamics.values())} thrusters"


@pytest.mark.parametrize("steering", STEERING_TYPES)
def test_the_vessel_reaches_the_commanded_speed_on_its_heading(run, steering):
    leg = run.legs[steering][0]
    assert abs(leg.speed_error) < 0.02 * CRUISE
    assert abs(leg.heading_error_deg) < 0.2 and leg.heading_span_deg < 0.2, "nothing turns a hull that is told to go straight"


@pytest.mark.parametrize("steering", STEERING_TYPES)
@pytest.mark.parametrize("leg_index,label", [(1, "to port"), (2, "to starboard")])
def test_the_vessel_turns_onto_the_new_heading_and_holds_it(run, steering, leg_index, label):
    leg = run.legs[steering][leg_index]
    assert abs(leg.heading_error_deg) < 0.5, f"{steering} {label}"
    assert leg.overshoot_deg < 3.0, f"{steering} {label}"
    assert leg.settle_s < TURN_S - 30.0, f"{steering} {label}: within {SETTLED_DEG} degrees well before the leg ends"
    assert leg.heading_span_deg < 1.0, f"{steering} {label}: no oscillation left at the end of the leg"
    assert abs(leg.speed_error) < 0.03 * CRUISE, f"{steering} {label}"
    assert leg.peak_turn_rate < 1.25 * VESSEL_SCALES[SCALE].max_angular_speed, f"{steering} {label}"


def test_the_helm_types_turn_the_way_the_skid_steered_hull_does(run):
    """Port is port for all three: after the first turn every hull heads 60 degrees counterclockwise of east."""
    per_second = int(round(1.0 / CONTROL_DT_S))
    for index, steering in enumerate(STEERING_TYPES):
        heading = run.result.odometry[(STRAIGHT_S + TURN_S) * per_second][index].heading
        assert math.degrees(heading) == pytest.approx(60.0, abs=1.0), steering


def test_gazebo_reports_no_error(run):
    errors = [line for line in run.log.splitlines() if "[Err]" in line or "Traceback" in line]
    assert errors == [], f"errors in {run.folder / 'gazebo.log'}"
