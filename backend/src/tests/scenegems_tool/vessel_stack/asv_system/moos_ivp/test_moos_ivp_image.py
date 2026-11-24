"""The real helm: the scenegems-moos-ivp image stepped by the kinematic runner over the wire protocol.

The container holds MOOS-IvP's MOOSDB and pHelmIvP, built from the pinned fork, and the component's server. The
kinematic simulator and the target's replay run on the loopback interface of the test (loopback_stack.py), so the
run is the kinematic job's run with one container in the place of a stack.

Needs Docker and the image (./build.sh --simulation): pytest -m docker.
"""

import math
import subprocess
from pathlib import Path
from typing import Iterator, Optional

import pytest

from scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_specs import MOOS_IVP_CONTAINER
from scenegems_tool.vessel_stack.contracts.lockstep_wire import Endpoint
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId
from scenegems_tool.vessel_stack.contracts.stack_services import asv_system_port
from scenegems_tool.vessel_stack.hosting import ContainerHosting
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_runner import KinematicInstanceRun, kinematic_instance, run_kinematic_instance
from tests.scenegems_tool.vessel_stack.loopback_stack import loopback_endpoints
from tests.scenegems_tool.vessel_stack.scenarios import encounter_trajectories

pytestmark = [pytest.mark.docker, pytest.mark.slow]

REPO_ROOT = Path(__file__).resolve().parents[7]
SAFETY_RADIUS_M = 120.0  # of the encounters' 30 m vessels


def pinned_commit() -> str:
    pins = (REPO_ROOT / "deploy" / "images" / "upstream_pins.env").read_text(encoding="utf-8")
    return next(line.split("=", 1)[1].strip() for line in pins.splitlines() if line.startswith("MOOS_IVP_COMMIT="))


@pytest.fixture(scope="module")
def helm_container() -> Iterator[Endpoint]:
    """One MOOS-IvP container, as the own ship's ASV system service of a stack is (its default ports are vessel 0's), with its port on the loopback interface."""
    started = subprocess.run(["docker", "run", "-d", "--rm", "-p", f"127.0.0.1::{asv_system_port(0)}", MOOS_IVP_CONTAINER.default_image], capture_output=True, text=True)
    if started.returncode != 0:
        pytest.fail(f"could not start {MOOS_IVP_CONTAINER.default_image} (build it with ./build.sh --simulation): {started.stderr.strip()}")
    container = started.stdout.strip()
    try:
        published = subprocess.run(["docker", "port", container, f"{asv_system_port(0)}/tcp"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
        yield Endpoint("127.0.0.1", int(published.rsplit(":", 1)[1]))
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)


def run_encounter(helm: Endpoint, name: str, timespan: int, dt: Optional[float] = None) -> KinematicInstanceRun:
    """The own ship on the container's helm against the encounter's replaying target, at the trajectories' time step or at dt."""
    trajectories = encounter_trajectories(name, timespan)
    with loopback_endpoints(kinematic_instance(trajectories)) as endpoints:  # the simulator and the target's replay
        endpoints["os-asv-system"] = helm
        return run_kinematic_instance(trajectories, kinematic_instance(trajectories, {0: AsvSystemId.MOOS_IVP}), dt=dt, hosting=ContainerHosting(endpoints, connect_timeout_s=60.0))


def closest_approach(run: KinematicInstanceRun) -> float:
    return min(math.hypot(own.x - target.x, own.y - target.y) for own, target in run.result.states)


@pytest.fixture(scope="module")
def head_on(helm_container) -> KinematicInstanceRun:
    return run_encounter(helm_container, "head_on", 600)


def test_the_helm_decides_every_step_and_reports_its_run(head_on):
    report = head_on.reports[0]
    assert head_on.result.steps == 600 and report["no_decision_steps"] == 0
    assert report["moos_ivp_commit"] == pinned_commit(), "the image was built from the pinned fork commit"
    assert report["avoidance_behaviour"] == "BHV_AvdColregsV22"
    assert [0.0, "spawn", "avd_c1"] in report["events"], "the target is within completed_dist from the start, so it has its avoidance behaviour from the first step"
    assert report["warnings"] == []


def test_head_on_the_helm_gives_way_to_starboard_and_stays_out_of_the_safety_domain(head_on):
    own_track = [states[0] for states in head_on.result.states]
    assert min(state.y for state in own_track) < -SAFETY_RADIUS_M, "the own ship heads east, so starboard is south"
    assert max(state.y for state in own_track) < 1.0, "and it never turns to port of its course"
    assert closest_approach(head_on) > SAFETY_RADIUS_M


def test_a_run_repeats_bit_for_bit(helm_container, head_on):
    """The helm runs one pass per step on the clock the server steps, so the same requests give the same run."""
    again = run_encounter(helm_container, "head_on", 600)
    assert again.result.state_digest() == head_on.result.state_digest()
    assert again.reports[0] == head_on.reports[0]


def test_the_helm_runs_at_a_step_longer_than_the_lead_in(helm_container):
    """The helm is due on the first step, LEAD_IN_S after its start, whatever the step is: with a period of half a 5 s step it never was."""
    run = run_encounter(helm_container, "head_on", 600, dt=5.0)
    assert run.result.steps == 120 and run.reports[0]["no_decision_steps"] == 0
    assert closest_approach(run) > SAFETY_RADIUS_M


@pytest.mark.parametrize("name", ["crossing_from_starboard", "overtaking"])
def test_the_other_encounters_keep_clear_and_repeat(helm_container, name):
    first, second = run_encounter(helm_container, name, 400), run_encounter(helm_container, name, 400)
    assert first.result.state_digest() == second.result.state_digest()
    assert first.reports[0]["no_decision_steps"] == 0
    assert closest_approach(first) > SAFETY_RADIUS_M
