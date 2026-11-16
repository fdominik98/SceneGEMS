"""MOOS-IvP as a plug and play ASV system component: pHelmIvP behind the lockstep wire protocol.

The image of this component (deploy/images/moos_ivp) holds MOOS-IvP's MOOSDB and pHelmIvP, the
bridge client (scenegems_moos_bridge), this file and contracts/lockstep_wire.py, and nothing else
of SceneGEMS. So this file imports only the wire protocol and the standard library. Everything
it needs about the vessel and the scenario arrives in the start message; the config is
MoosIvpParameters in wire form with the step and the contacts' lengths
(moos_ivp_participant.moos_ivp_start_config):

    "config": {"dt": 1.0, "goal": [x, y], "speed": v, "max_speed": .., "avoidance": "colregs",
               "min_util_cpa_dist": .., "max_util_cpa_dist": .., "pwt_outer_dist": .., "pwt_inner_dist": ..,
               "completed_dist": .., "capture_radius": .., "behaviour_options": [["name", "value"], ..],
               "contacts": {"<actor id>": {"length": ..}}}

Its report holds the behaviours' life events, when the goal was reached, the steps without a
decision and the MOOS-IvP commit of the image. Entry point:

    python3 -m scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_server --port 12000 --moosdb-port 12400

--port is where the runner connects, --moosdb-port the first port of the vessel's MOOSDB (the stack gives
every vessel ports of its own, since the containers of a run may share a network namespace).
What runs, per run, in the container (HelmProcesses): a MOOSDB, the bridge and pHelmIvP, with a
mission file and a behaviour file written from the config. MoosIvpNavigator is the navigation
step around them; the tests run it against a helm of their own, since MOOS-IvP exists only in
the image.

Time. MOOS has no simulated clock of its own: its time is the wall clock. The image builds a
libMOOS that reads its time from a file this server writes (MOOS_EXTERNAL_CLOCK), and whose apps
run one mail-and-iterate pass per tick and acknowledge it (MOOS_EXTERNAL_TICK). A step is: set
the clock to the step's time, post the own ship's state and the contacts' reports, post the
tick, wait for the helm's acknowledgement, read its decision. The helm therefore sees the same
mail at the same time in every run, and a run is a function of the requests alone. MOOS time is
BASE_TIME + LEAD_IN_S + simulated time: a fixed base so that runs repeat, and a lead-in because
the helm decides nothing in its first second.

Frame mapping:

- Position: NAV_X and NAV_Y are the SceneGEMS local frame unchanged (x east, y north, meters),
  as are the X and Y of a contact's report.
- Heading: MOOS headings are degrees clockwise from north, SceneGEMS headings radians
  counterclockwise from east: compass = (90 - degrees(heading)) mod 360, both ways.
- Speed: meters per second, unchanged.
- Decision: the helm decides on a grid, the course in whole degrees and the speed in steps of a
  twentieth of the transit speed, so the transit speed itself is on the grid.
- Contacts: one NODE_REPORT per other actor every step, with the step's time. The helm keeps
  the reports in its own ledger and does not extrapolate them. A contact within completed_dist
  gets its avoidance behaviour (the helm spawns it on CONTACT_INFO, which pContactMgrV20 would
  post in a MOOS-IvP mission); the behaviour ends beyond 1.1 times that distance, and the
  contact gets a new one when it comes back. Static obstacles are contacts with speed 0.
- After the goal: the waypoint behaviour completes and the helm has nothing left to decide, so
  the navigator holds heading and speed for the rest of the run, as USV Navigation does.
"""

import argparse
import math
import os
import shutil
import struct
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Set, Tuple, Union

from scenegems_tool.vessel_stack.contracts.lockstep_wire import ROLE_ASV_SYSTEM, Message, Session, WireError, serve_component

IMPLEMENTATION = "moos_ivp"
# What contracts/stack_services.py gives vessel 0, which this file cannot import; a test keeps them equal. The stack's generator sets both ports per vessel.
DEFAULT_PORT = 12000
DEFAULT_MOOSDB_PORT = 12400
MOOSDB_PORTS_PER_VESSEL = 16  # a server process takes a new MOOSDB port per run, counting up within this many ports from its first

BASE_TIME = 1_000_000_000.0  # MOOS time of the helm's start, the same in every run
LEAD_IN_S = 2.0  # MOOS time between the helm's start and simulated time 0: the helm decides nothing in its first second
TICK_VARIABLE = "SG_TICK"
ARRIVED_VARIABLE = "SG_ARRIVED"
OWN_SHIP_NAME = "own"  # the MOOS community, which is the helm's name for its own vessel
COURSE_DOMAIN = "course:0:359:360"
SPEED_STEPS_TO_TRANSIT = 20  # the helm's speed grid has this many steps up to the transit speed
AVOIDANCE_BEHAVIOURS = {"colregs": "BHV_AvdColregsV22", "cpa": "BHV_AvoidCollision"}
RELEASE_FACTOR = 1.1  # an avoidance behaviour ends beyond this many times completed_dist (upstream's own factor)
ALLSTOP_CLEAR = "clear"
# The waypoint behaviour retracts this warning once it has its waypoint, and the helm posts the retraction as the warning's own text.
RETRACTED_WARNINGS = ("No waypts given. Set val to empty if intentional",)
# The local frame's origin on the globe for the helm's ledger, which also keeps every contact in latitude and longitude.
# No behaviour reads them, but the helm does not start without an origin.
LATITUDE_ORIGIN, LONGITUDE_ORIGIN = 43.825300, -70.330400

State = Tuple[float, float, float, float]  # x, y, speed, heading
Post = Tuple[str, Union[float, str]]  # a MOOS variable and the double or the string posted to it


def participant_id(vessel_id: int) -> str:
    return f"{IMPLEMENTATION}/{vessel_id}"


def compass_degrees(heading: float) -> float:
    """A SceneGEMS heading (radians counterclockwise from east) as a MOOS heading (degrees clockwise from north) in [0, 360)."""
    compass = math.fmod(90.0 - math.degrees(heading), 360.0)
    if compass < 0.0:
        compass += 360.0
    return 0.0 if compass >= 360.0 else compass


def heading_radians(compass: float) -> float:
    """A MOOS heading as a SceneGEMS heading within [-pi, pi]."""
    angle = math.radians(90.0 - compass)
    return math.atan2(math.sin(angle), math.cos(angle))


def contact_name(actor_id: int) -> str:
    return f"c{actor_id}"


def speed_domain(speed: float, max_speed: float) -> str:
    """The helm's speed grid: from 0 in steps of a twentieth of the transit speed, up to the last step within max_speed."""
    step = speed / SPEED_STEPS_TO_TRANSIT
    count = int(max_speed / step + 1e-9) + 1
    return f"speed:0:{step * (count - 1)!r}:{count}"


def mission_text(port: int, dt: float, speed: float, max_speed: float) -> str:
    """The mission file of the run: the MOOSDB's address and the helm's block."""
    # Two passes per step would fit in the period, but the clock only moves once a step, so the helm runs one.
    app_tick = 2.0 / dt
    return (
        f"ServerHost = localhost\nServerPort = {port}\nCommunity = {OWN_SHIP_NAME}\nMOOSTimeWarp = 1\n"
        f"LatOrigin = {LATITUDE_ORIGIN}\nLongOrigin = {LONGITUDE_ORIGIN}\n\n"
        "ProcessConfig = pHelmIvP\n{\n"
        f"  AppTick = {app_tick!r}\n  CommsTick = {app_tick!r}\n"
        f"  behaviors = {BEHAVIOUR_FILE}\n  domain = {COURSE_DOMAIN}\n  domain = {speed_domain(speed, max_speed)}\n"
        # The helm steers from its first pass, does not seed rand() with the time, and takes mail of any age.
        "  start_in_drive = true\n  seed_random = false\n  ok_skew = any\n}\n"
    )


def behaviour_text(config: Mapping[str, Any]) -> str:
    """The behaviour file of the run: the transit to the goal, and the template of the avoidance behaviour of a contact."""
    avoidance = AVOIDANCE_BEHAVIOURS.get(config["avoidance"])
    if avoidance is None:
        raise WireError(f"unknown avoidance {config['avoidance']!r}; known: {', '.join(sorted(AVOIDANCE_BEHAVIOURS))}")
    goal_x, goal_y = config["goal"]
    capture_radius = float(config["capture_radius"])
    distances = "".join(f"  {name} = {float(config[name])!r}\n" for name in ("pwt_outer_dist", "pwt_inner_dist", "completed_dist", "min_util_cpa_dist", "max_util_cpa_dist"))
    options = "".join(f"  {name} = {value}\n" for name, value in config.get("behaviour_options") or ())
    return (
        "initialize DEPLOY = true\n\n"
        "Behavior = BHV_Waypoint\n{\n  name = transit\n  pwt = 100\n  condition = DEPLOY = true\n"
        f"  endflag = {ARRIVED_VARIABLE} = true\n"
        f"  speed = {float(config['speed'])!r}\n  capture_radius = {capture_radius!r}\n  slip_radius = {2.0 * capture_radius!r}\n"
        f"  point = {float(goal_x):.4f},{float(goal_y):.4f}\n  repeat = 0\n}}\n\n"
        f"Behavior = {avoidance}\n{{\n  name = avd_\n  pwt = 200\n  condition = DEPLOY = true\n"
        # One instance per contact, spawned by the navigator's CONTACT_INFO: no contact manager runs, so the template asks for no alerts.
        "  updates = CONTACT_INFO\n  templating = spawn\n  contact = to-be-set\n  on_no_contact_ok = true\n  no_alert_request = true\n"
        f"{distances}{options}}}\n"
    )


def node_report(name: str, moos_time: float, state: State, length: float) -> str:
    """A contact's report as the helm's ledger reads it. Fixed notation: the ledger refuses numbers with an exponent."""
    x, y, speed, heading = state
    return f"NAME={name},TYPE=ship,TIME={moos_time:.3f},X={x:.4f},Y={y:.4f},SPD={speed:.4f},HDG={compass_degrees(heading):.4f},LENGTH={length:.2f},MODE=DRIVE"


def life_event(text: str) -> Tuple[str, str]:
    """(event, behaviour name) of the helm's IVPHELM_LIFE_EVENT, such as ("spawn", "avd_c1")."""
    fields = dict(part.strip().split("=", 1) for part in text.split(",") if "=" in part)
    return fields.get("event", ""), fields.get("bname", "")


@dataclass
class HelmPass:
    """What one pass of the helm gave."""

    heading: Optional[float] = None  # decided in this pass, degrees clockwise from north; None without a decision
    speed: Optional[float] = None
    allstop: str = ALLSTOP_CLEAR  # the helm's all-stop state after the pass: clear, or why it decides nothing
    arrived: bool = False  # the waypoint behaviour has completed
    life_events: List[str] = field(default_factory=list)  # IVPHELM_LIFE_EVENT posts of the pass
    warnings: List[str] = field(default_factory=list)  # behaviour warnings and errors of the pass


class Helm(Protocol):
    def start(self, mission: Callable[[int], str], behaviours: str) -> None:
        """Start the helm on the mission (written for the MOOSDB port it is given) and the behaviour file, at BASE_TIME."""

    def run_pass(self, moos_time: float, posts: Sequence[Post]) -> HelmPass:
        """Move the clock to moos_time, post, and let the helm run one pass on it."""

    def close(self) -> None:
        """End the helm's processes."""


MISSION_FILE = "own.moos"
BEHAVIOUR_FILE = "own.bhv"
BRIDGE_PROGRAM = "scenegems_moos_bridge"
SHARED_MEMORY_FOLDER = "/dev/shm"
START_TIMEOUT_S = 60.0
PASS_TIMEOUT_MS = 30000
LATEST_VARIABLES = ("DESIRED_HEADING", "DESIRED_SPEED", "IVPHELM_STATE", "IVPHELM_ALLSTOP", ARRIVED_VARIABLE, f"{TICK_VARIABLE}_ACK")
QUEUED_VARIABLES = ("IVPHELM_LIFE_EVENT", "BHV_WARNING", "BHV_ERROR", "IVPHELM_BHVSET_WARNING")


class HelmProcesses:
    """The helm of one run: a MOOSDB, the bridge and pHelmIvP in a folder of their own, on a clock this object steps.

    The bridge (deploy/images/moos_ivp/bridge) is a MOOS client that takes tab-separated commands on its
    standard input and answers queries with one line: it writes the clock, posts, and waits for mail.
    """

    first_port = DEFAULT_MOOSDB_PORT  # the process's MOOSDB ports start here: --moosdb-port
    _runs = 0  # every run gets a MOOSDB port of its own, so a run never meets the socket of the one before

    def __init__(self) -> None:
        self._folder: Optional[str] = None
        self._clock_path: Optional[str] = None
        self._processes: Dict[str, subprocess.Popen] = {}
        self._logs: List[Any] = []
        self._bridge: Optional[subprocess.Popen] = None

    @classmethod
    def take_port(cls) -> int:
        """The MOOSDB port of the next run: the process's first port, then the ones after it, round again after MOOSDB_PORTS_PER_VESSEL runs."""
        port = cls.first_port + cls._runs % MOOSDB_PORTS_PER_VESSEL
        cls._runs += 1
        return port

    def start(self, mission: Callable[[int], str], behaviours: str) -> None:
        port = HelmProcesses.take_port()
        self._folder = tempfile.mkdtemp(prefix="moos_ivp_")
        self._clock_path = os.path.join(SHARED_MEMORY_FOLDER if os.path.isdir(SHARED_MEMORY_FOLDER) else self._folder, f"moos_ivp_clock_{os.getpid()}_{port}")
        with open(self._clock_path, "wb") as clock:
            clock.write(struct.pack("<d", BASE_TIME))
        for name, text in ((MISSION_FILE, mission(port)), (BEHAVIOUR_FILE, behaviours)):
            with open(os.path.join(self._folder, name), "w", encoding="utf-8", newline="\n") as file:
                file.write(text)
        environment = {**os.environ, "MOOS_EXTERNAL_CLOCK": self._clock_path, "MOOS_EXTERNAL_TICK": TICK_VARIABLE}
        # The server first: a MOOS client that finds none retries in MOOS time, which does not move yet.
        self._spawn("MOOSDB", ["MOOSDB", MISSION_FILE, "--moos_timeout=1000000"], environment)
        self._wait_for_log("MOOSDB", "Connect to this server", START_TIMEOUT_S)
        self._bridge = subprocess.Popen(
            [BRIDGE_PROGRAM, "localhost", str(port), "sgBridge", self._clock_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8", env=environment, cwd=self._folder
        )
        self._expect_ok(self._ask("CONNECTED", str(int(START_TIMEOUT_S * 1000))), "the bridge did not reach the MOOSDB")
        for name in LATEST_VARIABLES:
            self._expect_ok(self._ask("REG", name), f"registering for {name}")
        for name in QUEUED_VARIABLES:
            self._expect_ok(self._ask("QREG", name), f"registering for {name}")
        self._spawn("pHelmIvP", ["pHelmIvP", MISSION_FILE], environment)
        # The helm's first pass runs at the base time whenever it has connected, so its start time is the same in every run.
        self._tick(BASE_TIME, int(START_TIMEOUT_S * 1000))
        state = self._latest("IVPHELM_STATE")[2]
        if state != "DRIVE":
            raise WireError(f"pHelmIvP is in state {state!r}, not DRIVE: {self._log_tail('pHelmIvP')}")

    def run_pass(self, moos_time: float, posts: Sequence[Post]) -> HelmPass:
        self._expect_ok(self._ask("CLOCK", repr(moos_time)), "setting the clock")
        for name, value in posts:
            if isinstance(value, str):
                self._send("S", name, value)
            else:
                self._send("D", name, repr(float(value)))
        self._tick(moos_time, PASS_TIMEOUT_MS)
        result = HelmPass(life_events=self._drain("IVPHELM_LIFE_EVENT"))
        for name in ("BHV_WARNING", "BHV_ERROR", "IVPHELM_BHVSET_WARNING"):
            result.warnings.extend(self._drain(name))
        _, heading_time, heading = self._latest("DESIRED_HEADING")
        _, speed_time, speed = self._latest("DESIRED_SPEED")
        if heading_time == moos_time and speed_time == moos_time:  # posted in this pass: the helm posts both whenever it decides
            result.heading, result.speed = float(heading), float(speed)
        allstop_count, _, allstop = self._latest("IVPHELM_ALLSTOP")
        result.allstop = str(allstop) if allstop_count else ALLSTOP_CLEAR
        result.arrived = self._latest(ARRIVED_VARIABLE)[0] > 0
        return result

    def close(self) -> None:
        # The processes are ended, not asked to close: a MOOS client's own close waits in MOOS time.
        for process in ([self._bridge] if self._bridge is not None else []) + list(self._processes.values()):
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        self._bridge = None
        self._processes = {}
        for log in self._logs:
            log.close()
        self._logs = []
        if self._clock_path is not None and os.path.exists(self._clock_path):
            os.remove(self._clock_path)
        if self._folder is not None:
            shutil.rmtree(self._folder, ignore_errors=True)
        self._folder = self._clock_path = None

    def _spawn(self, name: str, command: List[str], environment: Mapping[str, str]) -> None:
        assert self._folder is not None
        log = open(os.path.join(self._folder, f"{name}.log"), "w", encoding="utf-8")
        self._logs.append(log)
        self._processes[name] = subprocess.Popen(command, cwd=self._folder, env=dict(environment), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)

    def _wait_for_log(self, name: str, text: str, timeout_s: float) -> None:
        deadline = time.monotonic() + timeout_s
        while text not in self._log(name):
            if self._processes[name].poll() is not None or time.monotonic() > deadline:
                raise WireError(f"{name} did not start: {self._log_tail(name)}")
            time.sleep(0.05)

    def _tick(self, moos_time: float, timeout_ms: int) -> None:
        stamp = repr(moos_time)
        self._send("D", TICK_VARIABLE, stamp)
        reply = self._ask("WAITVAL", f"{TICK_VARIABLE}_ACK", stamp, str(timeout_ms))
        if reply[0] != "OK":
            ended = self._processes["pHelmIvP"].poll()
            state = f"pHelmIvP ended with code {ended}" if ended is not None else "pHelmIvP did not acknowledge the tick"
            raise WireError(f"{state} at MOOS time {stamp}: {self._log_tail('pHelmIvP')}")

    def _send(self, *parts: str) -> None:
        assert self._bridge is not None and self._bridge.stdin is not None
        self._bridge.stdin.write("\t".join(parts) + "\n")

    def _read(self) -> str:
        assert self._bridge is not None and self._bridge.stdin is not None and self._bridge.stdout is not None
        self._bridge.stdin.flush()
        line = self._bridge.stdout.readline()
        if not line:
            raise WireError("the MOOS bridge ended")
        return line.rstrip("\n")

    def _ask(self, *parts: str) -> List[str]:
        self._send(*parts)
        return self._read().split("\t")

    def _expect_ok(self, reply: List[str], what: str) -> None:
        if reply[0] != "OK":
            raise WireError(f"MOOS bridge: {what}: {' '.join(reply)}")

    def _latest(self, name: str) -> Tuple[int, float, Union[float, str]]:
        """(times received, MOOS time of the latest post, its value) of a registered variable."""
        self._send("GET", name)
        count, stamp, kind, value = self._read().split("\t", 3)
        return int(count), float(stamp), (float(value) if kind == "D" else value)

    def _drain(self, name: str) -> List[str]:
        """Every post of a queued variable since the last drain, in order."""
        count = int(self._ask("DRAIN", name)[0])
        return [self._read() for _ in range(count)]

    def _log(self, name: str) -> str:
        assert self._folder is not None
        with open(os.path.join(self._folder, f"{name}.log"), encoding="utf-8", errors="replace") as file:
            return file.read()

    def _log_tail(self, name: str, characters: int = 1500) -> str:
        return " | ".join(line.strip() for line in self._log(name)[-characters:].splitlines() if line.strip())


class MoosIvpNavigator:
    """Runs one helm pass per simulation step and returns the heading and speed to command.

    Once the helm's waypoint behaviour has completed, the navigator holds heading and speed for
    the rest of the run. A step in which the helm decides nothing (its all-stop is not clear)
    holds the heading and the last decided speed, and is counted.
    """

    def __init__(self, helm: Helm, vessel: Mapping[str, Any], config: Mapping[str, Any]):
        self.helm = helm
        self.config = dict(config)
        self.dt = float(config["dt"])
        self.speed = float(config["speed"])
        self.max_speed = float(config["max_speed"])
        self.completed_dist = float(config["completed_dist"])
        self.own_length = float(vessel["length"])
        self.contact_lengths = {int(actor_id): float(contact["length"]) for actor_id, contact in (config.get("contacts") or {}).items()}
        self.behaviours = behaviour_text(config)
        self._alerted: Set[int] = set()
        self._last_speed = self.speed
        self._allstop = ALLSTOP_CLEAR
        self.events: List[List[Any]] = []  # [simulated time, event, behaviour]
        self.allstops: List[List[Any]] = []  # [simulated time, the helm's all-stop state] at every change
        self.warnings: List[str] = []
        self.goal_reached_at: Optional[float] = None
        self.no_decision_steps = 0

    def start(self) -> None:
        self.helm.start(lambda port: mission_text(port, self.dt, self.speed, self.max_speed), self.behaviours)

    def step(self, time_s: float, own: State, targets: Mapping[int, State]) -> Tuple[float, float]:
        """The (heading, speed) command for the step that starts at time_s. targets are the other actors' states by actor id."""
        own_x, own_y, own_speed, own_heading = own
        if self.goal_reached_at is not None:
            return own_heading, self.speed
        moos_time = BASE_TIME + LEAD_IN_S + time_s
        posts: List[Post] = [("NAV_X", own_x), ("NAV_Y", own_y), ("NAV_HEADING", compass_degrees(own_heading)), ("NAV_SPEED", own_speed)]
        for actor_id, state in sorted(targets.items()):
            name = contact_name(actor_id)
            posts.append(("NODE_REPORT", node_report(name, moos_time, state, self.contact_lengths.get(actor_id, self.own_length))))
            distance = math.hypot(state[0] - own_x, state[1] - own_y)
            if actor_id not in self._alerted and distance <= self.completed_dist:
                posts.append(("CONTACT_INFO", f"name={name} # contact={name}"))
                self._alerted.add(actor_id)
            elif actor_id in self._alerted and distance >= RELEASE_FACTOR * self.completed_dist:
                self._alerted.discard(actor_id)  # its behaviour has ended; it gets a new one when it is back within completed_dist
        result = self.helm.run_pass(moos_time, posts)
        self.events.extend([time_s, *life_event(text)] for text in result.life_events)
        self.warnings.extend(warning for warning in result.warnings if warning not in self.warnings and not warning.endswith(RETRACTED_WARNINGS))
        if result.allstop != self._allstop:
            self._allstop = result.allstop
            self.allstops.append([time_s, result.allstop])
        if result.arrived:
            self.goal_reached_at = time_s
            return own_heading, self.speed
        if result.heading is None or result.speed is None or result.allstop != ALLSTOP_CLEAR:
            self.no_decision_steps += 1
            return own_heading, self._last_speed
        self._last_speed = result.speed
        return heading_radians(result.heading), result.speed

    def report(self) -> Dict[str, Any]:
        return {
            "moos_ivp_commit": os.environ.get("MOOS_IVP_COMMIT"),
            "avoidance_behaviour": AVOIDANCE_BEHAVIOURS[self.config["avoidance"]],
            "events": self.events,
            "allstops": self.allstops,
            "goal_reached_at": self.goal_reached_at,
            "no_decision_steps": self.no_decision_steps,
            "warnings": self.warnings,
        }

    def close(self) -> None:
        self.helm.close()


class MoosIvpSession(Session):
    helm_factory: Callable[[], Helm] = HelmProcesses  # what a session's helm is; the tests give one that needs no MOOS-IvP

    def __init__(self) -> None:
        self._navigator: Optional[MoosIvpNavigator] = None

    def on_start(self, request: Message) -> Message:
        self.close()
        vessel = request["vessel"]
        navigator = MoosIvpNavigator(type(self).helm_factory(), vessel, request["config"])
        self._navigator = navigator
        navigator.start()
        return {"op": "started", "participant_id": participant_id(int(vessel["id"]))}

    def on_step(self, request: Message) -> Message:
        navigator = self._started()
        targets = {int(actor_id): tuple(row) for actor_id, row in request["targets"].items()}
        heading, speed = navigator.step(float(request["time"]), tuple(request["own"]), targets)
        return {"op": "command", "heading": heading, "speed": speed}

    def on_report(self, request: Message) -> Message:
        del request
        return {"op": "report", "report": self._started().report()}

    def close(self) -> None:
        """End the run's helm; the server calls it when the runner's connection ends."""
        if self._navigator is not None:
            self._navigator.close()
            self._navigator = None

    def _started(self) -> MoosIvpNavigator:
        if self._navigator is None:
            raise WireError("step before start")
        return self._navigator


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--moosdb-port", type=int, default=DEFAULT_MOOSDB_PORT)
    arguments, rest = parser.parse_known_args(argv)
    HelmProcesses.first_port = arguments.moosdb_port
    serve_component(ROLE_ASV_SYSTEM, IMPLEMENTATION, MoosIvpSession, rest, default_port=DEFAULT_PORT)


if __name__ == "__main__":
    main()
