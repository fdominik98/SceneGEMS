"""Lockstep runner for ArduPilot stacks: ASV system stepped by SITL time, its commands sent over MAVLink.

Every vessel has a MavlinkLink to its SITL instance and a participant: the ReplayFollower for
replay (replay_mavlink_lockstep) or USV Navigation (usv_navigation_mavlink_lockstep), in this
process or in the vessel's ASV system container (vessel_stack/hosting.py). The runner keeps the step index in a LockstepClock and acts on
step k once every vessel's SITL time has reached its boundary: the observation is the state
interpolated to the boundary between the samples around it (MavlinkLink.state_at), each
participant computes its command, acknowledges the step, and the command is sent.

SITL is free-running, so the acknowledgement does not hold the physics: a command arrives a
wall-clock latency (times the speedup) after its boundary. That is why the tier is bounded.
The runner reads the wall clock only for timeouts and to report the achieved pace.

An optional step observer sees each step's observed states, keyed by vessel id, as soon as
they are recorded (a live observation forwards them). It must return quickly: SITL does not
wait for the runner.

In an attended run a vessel can be passive: an operator flies it from a ground control
station (mission_planner_gcs_port). The runner reads its state on SERIAL0 like any other
vessel's, so every participant observes it, but never arms it, switches its mode or
commands it.
"""

import dataclasses
import hashlib
import math
import select
import struct
import time
from dataclasses import dataclass
from typing import AbstractSet, Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.trajectories import Trajectories
from scenegems_tool.vessel_stack.asv_system.asv_system_runtime import ParticipantRequest
from scenegems_tool.vessel_stack.asv_system.mission_planner.mission_planner_specs import MISSION_PLANNER_GCS_PORT
from scenegems_tool.vessel_stack.asv_system.replay.replay_specs import REPLAY_MAVLINK_LOCKSTEP
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_parameters import UsvNavigationParameters, parameters_for
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_specs import USV_NAVIGATION_MAVLINK_LOCKSTEP
from scenegems_tool.vessel_stack.contracts.clock import LockstepClock, LockstepParticipant, StepAck, derive_seed
from scenegems_tool.vessel_stack.contracts.local_frame import Geofence
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand, VesselStateObservation
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.stack_services import vessel_stack_name
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentConnection, EnvironmentConfig, SimulationInstanceConfig, VesselConfig, VesselStackConfig
from scenegems_tool.vessel_stack.control_layers.ardupilot.mavlink_link import GUIDED_TARGET_TIMEOUT_S, MavlinkLink, MavlinkLinkError, StampedState, sitl_mavlink_endpoint
from scenegems_tool.vessel_stack.hosting import InProcessHosting, StackHosting
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.vessel_stack.registry.resolver import StackResolver, StackUnavailableError

START_QUANTUM_S = 5.0  # scenario time 0 is put on a multiple of this SITL time, so repeats share it
START_MARGIN_S = 1.0  # at least this much SITL time between arming and scenario time 0
GUIDED_CHECK_MS = 2500  # scenario time by which every vessel must report GUIDED
MAVLINK_LOCKSTEP_ADAPTERS = {AsvSystemId.REPLAY: REPLAY_MAVLINK_LOCKSTEP.id, AsvSystemId.USV_NAVIGATION: USV_NAVIGATION_MAVLINK_LOCKSTEP.id}
DEFAULT_LOCKSTEP_DT_S = 1.0  # the step of a run that names none when Rover cannot take the trajectories' time step (generated ones are 15 s)

StepObserver = Callable[[int, Mapping[int, StampedState]], None]  # (step index, the observed sample of each vessel id)


@dataclass(frozen=True)
class MavlinkRunResult:
    vessel_ids: Tuple[int, ...]
    dt: float
    run_seed: int
    participant_seeds: Tuple[Tuple[str, int], ...]
    epoch_boot_ms: Tuple[int, ...]  # SITL time of scenario time 0, per vessel in vessel_ids order
    states: Tuple[Tuple[StampedState, ...], ...]  # per step from t = 0: the observed sample of each vessel
    samples: Tuple[Tuple[StampedState, ...], ...]  # every streamed sample of each vessel
    wall_s: float  # wall time from scenario time 0 to the last step, for the achieved pace only
    run_record: Mapping[str, Any]

    @property
    def steps(self) -> int:
        return len(self.states) - 1

    @property
    def achieved_speedup(self) -> Optional[float]:
        return self.steps * self.dt / self.wall_s if self.wall_s > 0 else None

    def state_digest(self) -> str:
        """SHA-256 over the scenario-time stamps and the exact float64 bits of every observed state."""
        digest = hashlib.sha256()
        for step_states in self.states:
            for epoch_ms, sample in zip(self.epoch_boot_ms, step_states):
                state = sample.state
                digest.update(struct.pack("<q4d", sample.boot_ms - epoch_ms, float(state.x), float(state.y), float(state.speed), float(state.heading)))
        return digest.hexdigest()


def is_lockstep_dt(dt: float) -> bool:
    """Whether Rover can take dt as a lockstep step: a whole number of milliseconds below its GUIDED target timeout."""
    dt_ms = int(round(dt * 1000))
    return dt_ms > 0 and abs(dt_ms - dt * 1000) <= 1e-6 and dt < GUIDED_TARGET_TIMEOUT_S


def lockstep_dt(time_step: float) -> float:
    """The step of a run that names none: the trajectories' time step when Rover can take it, else DEFAULT_LOCKSTEP_DT_S."""
    return float(time_step) if is_lockstep_dt(float(time_step)) else DEFAULT_LOCKSTEP_DT_S


def run_mavlink_lockstep(
    links: Mapping[int, MavlinkLink],
    participants: Mapping[int, LockstepParticipant],
    vessels: Mapping[int, ConcreteVessel],
    dt: float,
    steps: int,
    run_seed: int,
    *,
    start_boot_s: Optional[float] = None,
    ready_timeout_s: float = 600.0,
    step_timeout_s: float = 120.0,
    on_step: Optional[StepObserver] = None,
    passive: AbstractSet[int] = frozenset(),
) -> MavlinkRunResult:
    """Connect, wait for readiness, arm in HOLD, then run `steps` steps of dt seconds of SITL time.

    The first command of each vessel switches it to GUIDED. links, participants and vessels are keyed by vessel id; the passive
    vessels have a link and no participant, and are only observed. Scenario time 0 is start_boot_s of
    SITL time on the lowest vessel id when given, else the first multiple of START_QUANTUM_S
    at least START_MARGIN_S after every vessel is armed; the other vessels start at the same
    instant of their own SITL clock as measured at that moment.
    """
    vessel_ids = tuple(sorted(links))
    active_ids = tuple(vessel_id for vessel_id in vessel_ids if vessel_id not in passive)
    if tuple(sorted(participants)) != active_ids or not set(passive) <= set(vessel_ids) or not set(vessel_ids) <= set(vessels):
        raise ValueError(f"links {vessel_ids}, participants {tuple(sorted(participants))} plus passive vessels {tuple(sorted(passive))}, and vessels must name the same vessels")
    clock = LockstepClock(dt, (participants[vessel_id].participant_id for vessel_id in active_ids))
    seeds: Dict[str, int] = {}
    for vessel_id in active_ids:
        participant = participants[vessel_id]
        seeds[participant.participant_id] = derive_seed(run_seed, participant.participant_id)
        participant.start(seeds[participant.participant_id])
    if not is_lockstep_dt(dt):
        raise ValueError(f"dt must be a whole number of milliseconds below Rover's {GUIDED_TARGET_TIMEOUT_S:g} s GUIDED target timeout, got {dt}")
    dt_ms = int(round(dt * 1000))
    _engage(links, vessel_ids, active_ids, ready_timeout_s)
    epochs = _epochs(links, vessel_ids, start_boot_s)
    recorded: List[Tuple[StampedState, ...]] = []
    wall_start: Optional[float] = None
    for index in range(steps + 1):
        boundaries = {vessel_id: epochs[vessel_id] + index * dt_ms for vessel_id in vessel_ids}
        observed = _wait_for_boundaries(links, boundaries, step_timeout_s)
        if wall_start is None:
            wall_start = time.monotonic()
        if index * dt_ms >= GUIDED_CHECK_MS and index * dt_ms < GUIDED_CHECK_MS + dt_ms:
            # Heartbeats come once a second, so two seconds after the first command every vessel must report GUIDED.
            not_guided = [vessel_id for vessel_id in active_ids if not links[vessel_id].in_guided]
            if not_guided:
                raise MavlinkLinkError(f"vessels {not_guided} did not switch from HOLD to GUIDED with their first command")
        _record(recorded, index, observed, vessel_ids, on_step)
        if index == steps:
            break
        commands = _step_commands(clock, participants, vessels, observed)
        for vessel_id in active_ids:
            links[vessel_id].send_heading_speed(commands[vessel_id], boundaries[vessel_id])
    wall_s = time.monotonic() - wall_start if wall_start is not None else 0.0
    return MavlinkRunResult(
        vessel_ids=vessel_ids,
        dt=dt,
        run_seed=run_seed,
        participant_seeds=tuple(sorted(seeds.items())),
        epoch_boot_ms=tuple(epochs[vessel_id] for vessel_id in vessel_ids),
        states=tuple(recorded),
        samples=tuple(tuple(links[vessel_id].samples) for vessel_id in vessel_ids),
        wall_s=wall_s,
        run_record={},
    )


def mavlink_instance(
    trajectories: Trajectories,
    simulation_layer: SimulationLayerId,
    asv_system: Optional[Mapping[int, AsvSystemId]] = None,
    *,
    environment: Optional[EnvironmentConfig] = None,
    speedup: int = 1,
) -> SimulationInstanceConfig:
    """A simulation instance where every vessel runs its ASV system through a lockstep MAVLink adapter.

    Replay unless asv_system names USV Navigation per vessel id. Agent names (and so SITL
    service names) are vessel_<id>. Feed the instance to build_simulation_docker_stack_artifacts
    for the stack and to run_mavlink_stack for the run.
    """
    asv_system = dict(asv_system or {})
    vessels = {}
    for vessel in trajectories.initial_scene.vessels:
        software = asv_system.get(vessel.id, AsvSystemId.REPLAY)
        if software not in MAVLINK_LOCKSTEP_ADAPTERS:
            raise ValueError(f"Vessel {vessel.id}: {software.value} has no lockstep MAVLink adapter")
        vessels[str(vessel.id)] = VesselConfig(
            agent_id=str(vessel.id),
            stack=VesselStackConfig(asv_system=software, control_layer=ControlLayerId.ARDUPILOT, simulation_layer=simulation_layer),
            connection=AgentConnection(agent_name=vessel_stack_name(vessel.id), topic=""),
            adapter_ids=(MAVLINK_LOCKSTEP_ADAPTERS[software],),
        )
    return SimulationInstanceConfig(simulation_layer=simulation_layer, environment=environment or EnvironmentConfig.calm(), speedup=speedup, vessels=vessels)


def mavlink_replay_instance(
    trajectories: Trajectories,
    simulation_layer: SimulationLayerId,
    *,
    environment: Optional[EnvironmentConfig] = None,
    speedup: int = 1,
) -> SimulationInstanceConfig:
    """mavlink_instance with every vessel on replay."""
    return mavlink_instance(trajectories, simulation_layer, environment=environment, speedup=speedup)


def run_mavlink_stack(
    trajectories: Trajectories,
    simulation: SimulationInstanceConfig,
    reference_geofence: Geofence,
    *,
    endpoints: Optional[Mapping[str, str]] = None,
    dt: Optional[float] = None,
    steps: Optional[int] = None,
    start_boot_s: Optional[float] = None,
    host: Optional[str] = None,
    resolver: Optional[StackResolver] = None,
    on_step: Optional[StepObserver] = None,
    usv_navigation_parameters: Optional[Mapping[int, UsvNavigationParameters]] = None,
    attended: bool = False,
    hosting: Optional[StackHosting] = None,
) -> MavlinkRunResult:
    """Run every simulated vessel on a running ArduPilot stack (ardupilot_sim or gazebo) through the registry.

    The instance is validated as an unattended run, and every simulated vessel must resolve to a
    lockstep MAVLink adapter: replay_mavlink_lockstep (the ReplayFollower on its trajectory) or
    usv_navigation_mavlink_lockstep (USV Navigation, parameters from its trajectory unless
    given). hosting decides where that ASV system runs: in this process by default, in the
    vessel's ASV system container with ContainerHosting; this runner sends its commands to SITL
    either way. endpoints maps agent ids to MAVLink endpoints; by default each is SERIAL0 of the
    vessel's SITL service inside the stack network. dt defaults to the trajectory time step when
    Rover can take it, else to DEFAULT_LOCKSTEP_DT_S (lockstep_dt), and steps to its timespan. The run seed is environment.seed. on_step sees every step's observed states.
    An attended run (an operator is watching, as in the workbench) may also hold Mission Planner
    vessels on their ground control station port (mission_planner_gcs_port), which it observes
    and leaves to the operator.
    """
    resolver = resolver or default_resolver()
    resolution = resolver.require_instance(simulation, attended=attended, host=host)
    lockstep_ids = set(MAVLINK_LOCKSTEP_ADAPTERS.values())
    passive_ids = {MISSION_PLANNER_GCS_PORT.id} if attended else set()
    wrong = [
        f"vessel {agent_id} runs through {chain.asv_adapter.id if chain.asv_adapter else 'no adapter'}"
        for agent_id, chain in resolution.chains.items()
        if chain.asv_adapter is None or chain.asv_adapter.id not in lockstep_ids | passive_ids
    ]
    if wrong:
        accepted = " or ".join(sorted(lockstep_ids | passive_ids))
        raise StackUnavailableError([f"run_mavlink_stack needs {accepted} for every simulated vessel: {', '.join(wrong)}"])
    dt = lockstep_dt(trajectories.time_step) if dt is None else dt
    scene = trajectories.initial_scene

    hosting = hosting or InProcessHosting()
    links: Dict[int, MavlinkLink] = {}
    requests: Dict[int, ParticipantRequest] = {}
    vessels: Dict[int, ConcreteVessel] = {}
    navigation_parameters: Dict[int, UsvNavigationParameters] = {}
    passive = set()
    for agent_id, vessel_config in simulation.simulated_vessels.items():
        vessel = scene.get_by_id(agent_id)
        if not isinstance(vessel, ConcreteVessel):
            raise ValueError(f"Vessel {vessel} is not a ConcreteVessel.")
        adapter = resolution.chains[agent_id].asv_adapter
        endpoint = (endpoints or {}).get(agent_id) or sitl_mavlink_endpoint(vessel_config.require_connection().agent_name, vessel.id)
        if adapter.id in passive_ids:
            links[vessel.id] = resolver.registry.runtime(REPLAY_MAVLINK_LOCKSTEP.id)(endpoint, vessel.id, reference_geofence)
            passive.add(vessel.id)
            vessels[vessel.id] = vessel
            continue
        links[vessel.id] = resolver.registry.runtime(adapter.id)(endpoint, vessel.id, reference_geofence)
        software = vessel_config.stack.asv_system
        if software == AsvSystemId.USV_NAVIGATION:
            navigation_parameters[vessel.id] = parameters_for(vessel, trajectories, dt, usv_navigation_parameters)
        requests[vessel.id] = ParticipantRequest(
            vessel=vessel,
            agent_name=vessel_config.require_connection().agent_name,
            asv_system=software,
            adapter=adapter,
            trajectories=trajectories,
            dt=dt,
            parameters=navigation_parameters.get(vessel.id),
        )
        vessels[vessel.id] = vessel
    steps = steps if steps is not None else int(round(trajectories.timespan / dt))
    try:
        participants = {vessel_id: hosting.asv_system(request) for vessel_id, request in requests.items()}
        result = run_mavlink_lockstep(links, participants, vessels, dt, steps, simulation.environment.seed, start_boot_s=start_boot_s, on_step=on_step, passive=frozenset(passive))
    finally:
        for link in links.values():
            link.close()
        hosting.close()

    tier = resolution.repeatability_tier
    run_record = {
        "stack": sorted({str(vessel.stack) for vessel in simulation.simulated_vessels.values()}),
        "specs": list(dict.fromkeys(spec.id for chain in resolution.chains.values() for spec in chain.specs)),
        "dt": dt,
        "steps": result.steps,
        "speedup": simulation.speedup,
        "achieved_speedup": result.achieved_speedup,
        "epoch_boot_ms": dict(zip(result.vessel_ids, result.epoch_boot_ms)),
        "run_seed": simulation.environment.seed,
        "participant_seeds": dict(result.participant_seeds),
        "repeatability_tier": tier.value if tier is not None else None,
        "environment": resolution.effective_environment(),
        "state_digest": result.state_digest(),
    }
    if navigation_parameters:
        run_record["usv_navigation"] = {str(vessel_id): parameters.as_dict() for vessel_id, parameters in sorted(navigation_parameters.items())}
    if passive:
        run_record["operator_vessels"] = sorted(passive)
    return dataclasses.replace(result, run_record=run_record)


def _record(recorded: List[Tuple[StampedState, ...]], index: int, observed: Mapping[int, StampedState], vessel_ids: Tuple[int, ...], on_step: Optional[StepObserver]) -> None:
    """Records a step's observed samples in vessel order and shows them to the step observer."""
    recorded.append(tuple(observed[vessel_id] for vessel_id in vessel_ids))
    if on_step is not None:
        on_step(index, {vessel_id: observed[vessel_id] for vessel_id in vessel_ids})


def _engage(links: Mapping[int, MavlinkLink], vessel_ids: Tuple[int, ...], active_ids: Tuple[int, ...], timeout_s: float) -> None:
    """Connect and wait for readiness of every vessel, and arm the active ones in HOLD (an operator arms a passive one)."""
    # SITL boots only once its SERIAL0 client connects, so connect every vessel before waiting on any.
    for vessel_id in vessel_ids:
        links[vessel_id].connect(timeout_s)
    for vessel_id in vessel_ids:
        links[vessel_id].wait_until_ready(timeout_s)
    for vessel_id in active_ids:
        links[vessel_id].begin_engagement()
    deadline = time.monotonic() + timeout_s
    while not all([links[vessel_id].advance_engagement() for vessel_id in active_ids]):
        if time.monotonic() > deadline:
            raise MavlinkLinkError(f"vessels {[vessel_id for vessel_id in active_ids if links[vessel_id].engaged_boot_ms is None]} not armed in HOLD within {timeout_s:g} s")
        _read_available(links, vessel_ids, 0.5)


def _step_commands(
    clock: LockstepClock, participants: Mapping[int, LockstepParticipant], vessels: Mapping[int, ConcreteVessel], observed: Mapping[int, StampedState]
) -> Dict[int, HeadingSpeedCommand]:
    """Every participant's command for the clock's current step, acknowledged; the clock then moves to the next step."""
    request = clock.request()
    commands = {}
    acks = []
    for vessel_id in sorted(participants):
        participant = participants[vessel_id]
        observation = VesselStateObservation(
            sim_time=request.time,
            vessel=vessels[vessel_id],
            own_state=observed[vessel_id].state,
            target_states={other: sample.state for other, sample in observed.items() if other != vessel_id},
        )
        commands[vessel_id] = participant.on_step(request, observation)
        acks.append(StepAck(participant_id=participant.participant_id, index=request.index))
    clock.advance(acks)
    return commands


def _epochs(links: Mapping[int, MavlinkLink], vessel_ids: Iterable[int], start_boot_s: Optional[float]) -> Dict[int, int]:
    """SITL time of scenario time 0 per vessel, aligned on one reading of every link's clock."""
    vessel_ids = tuple(vessel_ids)
    for vessel_id in vessel_ids:
        links[vessel_id].drain()
    now = {vessel_id: int(links[vessel_id].boot_ms or 0) for vessel_id in vessel_ids}
    reference = vessel_ids[0]
    if start_boot_s is not None:
        reference_epoch = int(round(start_boot_s * 1000))
        if reference_epoch < now[reference] + int(START_MARGIN_S * 1000):
            raise MavlinkLinkError(f"start_boot_s {start_boot_s:g} is too early: vessel {reference} is armed at SITL time {now[reference] / 1000:g} s")
    else:
        # Every vessel is armed by now, so the margin counts from this reading.
        reference_epoch = int(round(math.ceil((now[reference] / 1000.0 + START_MARGIN_S) / START_QUANTUM_S) * START_QUANTUM_S * 1000))
    return {vessel_id: reference_epoch + now[vessel_id] - now[reference] for vessel_id in vessel_ids}


def _read_available(links: Mapping[int, MavlinkLink], vessel_ids: Iterable[int], timeout_s: float) -> None:
    """Wait up to timeout_s until a link has data, then handle what every readable link received."""
    vessel_ids = tuple(vessel_ids)
    readable, _, _ = select.select([links[vessel_id].fileno() for vessel_id in vessel_ids], [], [], timeout_s)
    for vessel_id in vessel_ids:
        if links[vessel_id].fileno() in readable:
            links[vessel_id].drain()


def _wait_for_boundaries(links: Mapping[int, MavlinkLink], boundaries: Mapping[int, int], timeout_s: float) -> Dict[int, StampedState]:
    """Read every link until each has a sample at or after its boundary."""
    deadline = time.monotonic() + timeout_s
    observed: Dict[int, StampedState] = {}
    while True:
        for vessel_id, boundary in boundaries.items():
            if vessel_id not in observed:
                sample = links[vessel_id].state_at(boundary)
                if sample is not None:
                    observed[vessel_id] = sample
        pending = [vessel_id for vessel_id in boundaries if vessel_id not in observed]
        if not pending:
            return observed
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MavlinkLinkError(f"no state at SITL times {[boundaries[vessel_id] for vessel_id in pending]} ms from vessels {pending} within {timeout_s:g} s")
        _read_available(links, pending, min(remaining, 1.0))
