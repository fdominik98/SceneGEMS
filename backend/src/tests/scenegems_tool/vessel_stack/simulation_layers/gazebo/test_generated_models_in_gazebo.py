"""The generated vessel models in the real Gazebo image: one hull with each steering type floats, runs straight and turns as derived.

The three vessels are the 30 m own ship of the shipped vessel types, skid steered, with a rudder and with vectored
thrust, side by side in one flat world on the custom control layer (thrust and helm commands on gz-transport topics).
generated_model_check.py runs inside the image: it steps the paused world and samples each hull every second. The
vessels lie at rest, run straight on the thrust that holds the steering speed, turn with the helm hard over to port
(the skid steered one with full differential thrust), and then with the helm hard over to starboard.

Needs Docker and the Gazebo image (./build.sh --simulation): pytest -m docker.
"""

import json
import math
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import numpy as np
import pytest

from concrete_level.models.actor_state import ActorState
from logical_level.mapping.vessel_type import VesselTypeMap
from scenegems_tool.vessel_stack.contracts.roles import ControlLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gazebo_specs import GAZEBO_CONTAINER
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import VesselDynamics, derive_vessel_dynamics
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_generator import (
    generate_hull_mesh,
    generate_vessel_model,
    hull_mesh_filename,
    steering_topic,
    thrust_topic,
    thruster_names,
)
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.world_generator import generate_world
from tests.scenegems_tool.vessel_stack.sdf import parse_sdf
from tests.scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessels import STEERING_TYPES, steered, vessel_of_type

pytestmark = [pytest.mark.docker, pytest.mark.slow]

IMAGE = GAZEBO_CONTAINER.default_image
CHECK_SCRIPT = Path(__file__).with_name("generated_model_check.py")
MOUNT = "/w"
STEP_S = 0.005  # the world's max_step_size
REST_S, STRAIGHT_S, TURN_S, REVERSE_S = 20, 150, 150, 120
RUN_TIMEOUT_S = 900
VESSEL_TYPE, LENGTH = "OSPassengerShip", 30.0
# The model floats on an even keel: its origin, with the hull link's center of mass, lies over the center of buoyancy of
# the buoyant boxes (VesselDynamics.hull_x). With the origin amidships this vessel trimmed 1.37 degrees by the bow, and the
# heave damping then pushed the moving hull down and back: it ran 0.15 m deeper at 9.7 m/s and 5.5 percent slower than
# its surge damping lets it. What is left of the speed is the air drag of the windage link on the hull's own motion,
# which the thrust does not count (about 0.7 percent of the thrust at this speed).
MAX_TRIM_DEG = 0.2
SPEED_TOLERANCE = 0.02
MAX_SINKAGE_UNDER_WAY_M = 0.05


@dataclass(frozen=True)
class Run:
    folder: Path
    dynamics: Dict[str, VesselDynamics]  # by model name
    straight_thrust: float  # N in total, on every hull
    samples: Dict[str, Dict[str, List[Dict[str, float]]]]  # phase, model, one sample a second
    valid: Dict[str, str]
    log: str

    def last(self, phase: str, model: str, seconds: int = 1) -> List[Dict[str, float]]:
        return self.samples[phase][model][-seconds:]


def docker_is_available() -> bool:
    return shutil.which("docker") is not None and subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def speed_held_by(dynamics: VesselDynamics, thrust: float) -> float:
    """The speed at which the surge damping takes the thrust: |xU| u + |xUabsU| u^2 = thrust."""
    linear, quadratic = abs(dynamics.xU), abs(dynamics.xUabsU)
    return (-linear + math.sqrt(linear**2 + 4.0 * quadratic * thrust)) / (2.0 * quadratic)


def mean(samples: List[Dict[str, float]], key: str) -> float:
    return sum(sample[key] for sample in samples) / len(samples)


def helm_trace(samples: List[Dict[str, float]]) -> str:
    """Angle in rad and, in brackets, speed in rad/s of the steering joint, sample by sample."""
    return ", ".join(f"{sample['helm']:+.3f} ({sample['helm_velocity']:+.3f})" for sample in samples)


@pytest.fixture(scope="module")
def run(tmp_path_factory) -> Run:
    if not docker_is_available():
        pytest.skip("Docker is not available")
    if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode != 0:
        pytest.skip(f"the Gazebo image {IMAGE} is not built (./build.sh --simulation)")

    folder = tmp_path_factory.mktemp("generated_models")
    vessel_type = VesselTypeMap()[VESSEL_TYPE]
    dynamics: Dict[str, VesselDynamics] = {}
    includes = []
    model_files = []
    for index, steering_type in enumerate(STEERING_TYPES):
        vessel = steered(vessel_of_type(vessel_type, LENGTH, vessel_id=index), steering_type)
        name = f"agent_{index}"
        dynamics[name] = derive_vessel_dynamics(vessel, 0.0, {})
        model_files.append(f"{name}_model.sdf")
        (folder / model_files[-1]).write_text(generate_vessel_model(vessel, name, ControlLayerId.CUSTOM, overrides={}), encoding="utf-8", newline="\n")
        (folder / hull_mesh_filename(name)).write_text(generate_hull_mesh(vessel, name, overrides={}), encoding="utf-8", newline="\n")
        includes.append((f"{MOUNT}/{model_files[-1]}", ActorState(x=0.0, y=index * 20.0 * LENGTH, speed=0.0, heading=0.0)))
    calm = EnvironmentConfig.calm()
    world_text = generate_world(np.array([58.0, 10.0]), includes, calm.wind_vector, calm.wave, 1, headless=True, wave_forces=False, externally_stepped=True)
    (folder / "ocean_world.sdf").write_text(world_text, encoding="utf-8", newline="\n")
    world = parse_sdf(world_text).find("world").get("name")

    # Every hull runs straight on the thrust that holds the steering speed of the two with a helm.
    straight_thrust = next(d.steering_thrust for d in dynamics.values() if d.steering_type != "skid")
    rest, straight, turn, reverse = {}, {}, {}, {}
    for name, d in dynamics.items():
        thrusters = [thrust_topic(name, thruster) for thruster in thruster_names(d.steering_type)]
        rest.update({topic: 0.0 for topic in thrusters})
        straight.update({topic: straight_thrust / len(thrusters) for topic in thrusters})
        if d.steering_type == "skid":
            port, starboard = thrusters
            turn.update({port: -d.max_thrust, starboard: d.max_thrust})  # full differential thrust, counterclockwise
            reverse.update({port: d.max_thrust, starboard: -d.max_thrust})
        else:
            (center,) = thrusters
            turn[center] = reverse[center] = straight_thrust
            rest[steering_topic(name)] = straight[steering_topic(name)] = 0.0
            turn[steering_topic(name)] = -d.steering_max_angle  # hard over to port: the vessel turns counterclockwise
            reverse[steering_topic(name)] = d.steering_max_angle  # and from there hard over to starboard
    plan = {
        "world_file": "ocean_world.sdf",
        "world": world,
        "step_s": STEP_S,
        "model_files": model_files,
        "models": {name: {"odometry": f"/model/{name}/odometry", "joint_state": f"/world/{world}/model/{name}/joint_state"} for name in dynamics},
        "phases": [
            {"label": "rest", "seconds": REST_S, "commands": rest},
            {"label": "straight", "seconds": STRAIGHT_S, "commands": straight},
            {"label": "turn", "seconds": TURN_S, "commands": turn},
            {"label": "reverse", "seconds": REVERSE_S, "commands": reverse},
        ],
    }
    (folder / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
    shutil.copyfile(CHECK_SCRIPT, folder / CHECK_SCRIPT.name)

    # A gz-transport partition of its own: on Docker's default network every container of the image shares the image's
    # partition, so two worlds running at the same time would take each other's commands and odometry (seen in a run next
    # to another Gazebo container: the skid steered model reported the angle of a steering joint it does not have).
    # A login shell, so that the image's profile puts the gz bindings and plugins on their paths.
    partition = f"scenegems-test-{uuid.uuid4().hex[:12]}"
    script = f"cd {MOUNT} && timeout {RUN_TIMEOUT_S} python3 {CHECK_SCRIPT.name}"
    command = ["docker", "run", "--rm", "-e", f"GZ_PARTITION={partition}", "-v", f"{folder}:{MOUNT}", "--entrypoint", "bash", IMAGE, "-lc", script]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=RUN_TIMEOUT_S + 120)
    log_file, result_file = folder / "gz_server.log", folder / "result.json"
    log = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""
    if completed.returncode != 0 or not result_file.exists():
        pytest.fail(f"the check in {IMAGE} ended with code {completed.returncode} (files in {folder}):\n{completed.stdout[-2000:]}\n{completed.stderr[-2000:]}\n{log[-2000:]}")
    result = json.loads(result_file.read_text(encoding="utf-8"))
    measured = Run(folder, dynamics, straight_thrust, result["phases"], result["valid"], log)
    print(f"\nGenerated models in {IMAGE} (files in {folder}):")
    for name, d in dynamics.items():
        at_rest, running, turning = measured.last("rest", name, 5), measured.last("straight", name, 5), measured.last("turn", name, 20)
        print(
            f"  {name} {d.steering_type:15s} at rest z {mean(at_rest, 'z'):+.3f} m, pitch {math.degrees(mean(at_rest, 'pitch')):+.2f} deg, roll {math.degrees(mean(at_rest, 'roll')):+.3f} deg; "
            f"straight {mean(running, 'u'):.3f} m/s (expected {speed_held_by(d, straight_thrust):.3f}) at z {mean(running, 'z'):+.3f} m; "
            f"turn {mean(turning, 'r'):+.5f} rad/s (expected {d.max_steady_yaw_rate:+.5f}, design {d.design_yaw_rate:+.5f}) at {mean(turning, 'u'):.2f} m/s; "
            f"reversed {mean(measured.last('reverse', name, 20), 'r'):+.5f} rad/s"
        )
        if d.steering_type != "skid":
            print(
                f"    helm after the order to reverse, from {measured.last('turn', name)[0]['helm']:+.4f} rad to {d.steering_max_angle:+.4f} at {d.steering_rate:.4f} rad/s: {helm_trace(measured.samples['reverse'][name][:14])}"
            )
    return measured


def test_the_models_and_the_world_are_valid_sdf(run):
    assert set(run.valid) == {"ocean_world.sdf", "agent_0_model.sdf", "agent_1_model.sdf", "agent_2_model.sdf"}
    assert set(run.valid.values()) == {"Valid."}, run.valid


def test_the_three_steering_types_are_in_the_world(run):
    assert [d.steering_type for d in run.dynamics.values()] == list(STEERING_TYPES)
    for phase, seconds in (("rest", REST_S), ("straight", STRAIGHT_S), ("turn", TURN_S), ("reverse", REVERSE_S)):
        assert {name: len(samples) for name, samples in run.samples[phase].items()} == {name: seconds for name in run.dynamics}


def test_every_hull_floats_at_its_design_draft(run):
    """The model's origin is at the design waterline, so it stays at the height of the water within a few centimetres."""
    for name, d in run.dynamics.items():
        at_rest = run.last("rest", name, 5)
        assert abs(mean(at_rest, "z")) < 0.05, f"{name} ({d.steering_type}) floats {mean(at_rest, 'z'):+.3f} m off its draft of {d.draft} m"
        assert max(sample["z"] for sample in at_rest) - min(sample["z"] for sample in at_rest) < 0.01, f"{name} still heaves"
        assert abs(mean(at_rest, "u")) < 0.02 and abs(mean(at_rest, "r")) < 1e-4, f"{name} does not lie still"


def test_every_hull_floats_upright(run):
    """No list and no trim: the center of buoyancy of the boxes lies under the center of mass."""
    for name, d in run.dynamics.items():
        at_rest = run.last("rest", name, 5)
        assert abs(math.degrees(mean(at_rest, "roll"))) < 0.2, f"{name} ({d.steering_type}) lists"
        assert abs(math.degrees(mean(at_rest, "pitch"))) < MAX_TRIM_DEG, f"{name} ({d.steering_type}) trims by {math.degrees(mean(at_rest, 'pitch')):+.2f} deg"


def test_the_straight_run_reaches_the_speed_the_thrust_holds(run):
    for name, d in run.dynamics.items():
        running = run.last("straight", name, 5)
        expected = speed_held_by(d, run.straight_thrust)
        if d.steering_type != "skid":
            assert expected == pytest.approx(d.steering_speed), "the steering thrust is the thrust of the steering speed"
        assert mean(running, "u") == pytest.approx(expected, rel=SPEED_TOLERANCE), f"{name} ({d.steering_type})"
        assert abs(mean(running, "v")) < 0.01 * expected, f"{name} drifts sideways"


def test_the_hull_keeps_its_draft_and_its_trim_under_way(run):
    """A trimmed hull would be pushed down by its heave damping as it moves."""
    for name, d in run.dynamics.items():
        running = run.last("straight", name, 5)
        assert abs(mean(running, "z")) < MAX_SINKAGE_UNDER_WAY_M, f"{name} ({d.steering_type}) runs {mean(running, 'z'):+.3f} m off its draft"
        assert abs(math.degrees(mean(running, "pitch"))) < MAX_TRIM_DEG, f"{name} ({d.steering_type}) trims by {math.degrees(mean(running, 'pitch')):+.2f} deg under way"


def test_the_straight_run_stays_on_its_heading(run):
    for name, d in run.dynamics.items():
        running = run.samples["straight"][name]
        assert max(abs(sample["r"]) for sample in running) < 0.02 * d.max_steady_yaw_rate, f"{name} ({d.steering_type}) turns without a helm order"
        assert abs(math.degrees(running[-1]["yaw"])) < 0.5, f"{name} ({d.steering_type}) left its heading"


def test_the_helm_hard_over_gives_the_max_steady_yaw_rate(run):
    """Hard over to port, or full differential thrust: counterclockwise, within 10 percent of the derived rate."""
    for name, d in run.dynamics.items():
        turning = run.last("turn", name, 20)
        assert mean(turning, "r") > 0, f"{name} ({d.steering_type}) turns to starboard on a port helm"
        assert mean(turning, "r") == pytest.approx(d.max_steady_yaw_rate, rel=0.10), f"{name} ({d.steering_type})"
        assert max(sample["r"] for sample in turning) - min(sample["r"] for sample in turning) < 0.02 * d.max_steady_yaw_rate, f"{name} has not settled in its turn"


def test_the_turn_makes_the_hull_slide_outward_and_slows_it(run):
    for name, d in run.dynamics.items():
        if d.steering_type == "skid":
            continue  # it turns on the spot, with no thrust ahead
        turning, running = run.last("turn", name, 20), run.last("straight", name, 5)
        assert mean(turning, "v") < 0, f"{name} ({d.steering_type}) turns to port, so it slides to starboard"
        assert 0 < mean(turning, "u") < mean(running, "u")


def test_the_helm_travels_at_its_speed_and_stops_hard_over(run):
    for name, d in run.dynamics.items():
        samples = run.samples["turn"][name]
        if d.steering_type == "skid":
            assert all("helm" not in sample for sample in samples), "a skid steered model has no steering joint"
            continue
        assert all(abs(sample["helm"]) < 1e-3 for sample in run.samples["straight"][name]), "amidships on the straight run"
        assert d.steering_rate < d.steering_max_angle, "the first second of travel ends before hard over"
        assert samples[0]["helm"] == pytest.approx(-d.steering_rate, rel=0.05), f"{name} ({d.steering_type}) one second after the helm order"
        assert samples[-1]["helm"] == pytest.approx(-d.steering_max_angle, abs=2e-3), f"{name} ({d.steering_type}) hard over to port"
        assert all(-d.steering_max_angle - 2e-3 <= sample["helm"] <= 1e-3 for sample in samples), "never beyond hard over"


def test_the_helm_comes_back_from_hard_over(run):
    """Ordered from hard over to port to hard over to starboard, the helm leaves its angle at once and arrives in the time its speed allows.

    A velocity commanded joint that reaches its stop stays on it; the stops lie beyond hard over, so the helm never does.
    """
    for name, d in run.dynamics.items():
        if d.steering_type == "skid":
            continue
        samples = run.samples["reverse"][name]  # one a second, the first a second after the order
        trace = f"{name} ({d.steering_type}), angle (speed) each second: {helm_trace(samples[:20])}"
        assert run.last("turn", name)[0]["helm"] == pytest.approx(-d.steering_max_angle, abs=2e-3), "it starts hard over to port"
        assert samples[0]["helm"] == pytest.approx(-d.steering_max_angle + d.steering_rate, abs=0.05 * d.steering_rate), f"it leaves at once, at its speed: {trace}"
        assert samples[0]["helm_velocity"] == pytest.approx(d.steering_rate, rel=0.05), trace
        travel_s = 2.0 * d.steering_max_angle / d.steering_rate
        arrived = samples[math.ceil(travel_s) :]  # from the first sample a full second after the travel time
        assert all(sample["helm"] == pytest.approx(d.steering_max_angle, abs=2e-3) for sample in arrived), f"hard over to starboard after {travel_s:.1f} s: {trace}"
        assert all(abs(sample["helm_velocity"]) < 0.01 * d.steering_rate for sample in arrived), f"and at rest there: {trace}"
        assert all(later["helm"] >= earlier["helm"] - 1e-6 for earlier, later in zip(samples, samples[1:])), f"without turning back: {trace}"
        assert all(abs(sample["helm"]) <= d.steering_max_angle + 2e-3 for sample in samples), f"never beyond hard over, short of its stops: {trace}"


def test_the_yaw_rate_changes_sign_after_the_helm_is_reversed(run):
    """And settles at the same rate the other way: to starboard, clockwise."""
    for name, d in run.dynamics.items():
        reversed_turn = run.last("reverse", name, 20)
        assert mean(run.last("turn", name, 20), "r") > 0 > mean(reversed_turn, "r"), f"{name} ({d.steering_type})"
        assert mean(reversed_turn, "r") == pytest.approx(-d.max_steady_yaw_rate, rel=0.10), f"{name} ({d.steering_type})"
        if d.steering_type != "skid":
            assert mean(reversed_turn, "v") > 0, f"{name} ({d.steering_type}) turns to starboard, so it slides to port"


def test_gazebo_reports_no_error(run):
    errors = [line for line in run.log.splitlines() if "[Err]" in line or "Error" in line]
    assert errors == [], f"errors in {run.folder / 'gz_server.log'}"
