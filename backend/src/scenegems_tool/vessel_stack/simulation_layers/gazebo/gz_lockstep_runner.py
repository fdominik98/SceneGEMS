"""Lockstep runner of the custom control layer on Gazebo: ASV system, autopilot and physics on one clock.

Every vessel has an ASV participant (the line-of-sight waypoint follower for replay, USV
Navigation for usv_navigation) and a TwinThrustAutopilot with gains from its generated hull.
Both come from a hosting (vessel_stack/hosting.py): built in this process, or the vessel's ASV
system and controller containers, which this runner then carries the messages between.
The world is paused and advances only through the gz-transport actuator (gz_transport_actuator.py):

    for every scenario step of dt:
        the participants compute heading and speed commands from the states at the step's start
        for every control step of control_dt within it:
            each autopilot turns its command and its hull's latest odometry into two thrusts
            the actuator applies the thrusts and steps the world control_dt / PHYSICS_STEP_S iterations

Nothing reads the wall clock except the timeouts and the reported pace, so a run is a function of
its inputs and Gazebo's physics. A thrust that reached gz sim only after the first iteration of
its control step is counted (late_commands); a run with none is repeatable by construction.

Scenario time 0 is the end of settle_s of floating without thrust after the world loads. The
vessels start at rest, at their initial positions and headings.

An optional step observer sees each scenario step's states, keyed by vessel id, when recorded.
"""

import dataclasses
import hashlib
import struct
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import numpy as np

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.trajectories import Trajectories
from scenegems_tool.vessel_stack.asv_system.asv_system_runtime import ParticipantRequest
from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_parameters import UsvNavigationParameters, parameters_for
from scenegems_tool.vessel_stack.contracts.clock import LockstepClock, LockstepParticipant, StepAck, derive_seed
from scenegems_tool.vessel_stack.contracts.ports import HeadingSpeedCommand, VesselStateObservation
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentConnection, EnvironmentConfig, SimulationInstanceConfig, VesselConfig, VesselStackConfig
from scenegems_tool.vessel_stack.control_layers.custom.twin_thrust_autopilot import AutopilotGains, TwinThrustAutopilot
from scenegems_tool.vessel_stack.hosting import InProcessHosting, StackHosting
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.vessel_stack.registry.resolver import StackResolver, StackUnavailableError
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics import VesselDynamics, derive_vessel_dynamics
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_dynamics_overrides import load_vessel_dynamics_overrides
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.vessel_model_generator import sdf_value
from scenegems_tool.vessel_stack.simulation_layers.gazebo.generators.world_generator import PHYSICS_STEP_S
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_lockstep_link import GzLockstepLink, HullOdometry
from scenegems_tool.vessel_stack.simulation_layers.gazebo.gz_transport_actuator import DEFAULT_PORT

CONTROL_DT_S = 0.1  # autopilot step; a multiple of the odometry period (generators/vessel_model_generator.ODOMETRY_RATE_HZ)
SETTLE_S = 2.0  # floating without thrust before scenario time 0, so the hull has found its draft
FLUID_DENSITY = 1025.0

StepObserver = Callable[[int, Mapping[int, ActorState]], None]  # (step index, the state of each vessel id)


@dataclass(frozen=True)
class GzRunResult:
    vessel_ids: Tuple[int, ...]
    dt: float
    control_dt: float
    run_seed: int
    participant_seeds: Tuple[Tuple[str, int], ...]
    states: Tuple[Tuple[ActorState, ...], ...]  # per scenario step from t = 0, one state per vessel in vessel_ids order
    odometry: Tuple[Tuple[HullOdometry, ...], ...]  # per control step from t = 0, every vessel's odometry
    late_commands: int  # thrusters whose command was not in effect from their control step's first iteration
    epoch_sim_time_ns: int  # Gazebo time of scenario time 0
    wall_s: float
    run_record: Mapping[str, Any]

    @property
    def steps(self) -> int:
        return len(self.states) - 1

    @property
    def achieved_speedup(self) -> Optional[float]:
        return self.steps * self.dt / self.wall_s if self.wall_s > 0 else None

    def state_digest(self) -> str:
        """SHA-256 over the exact float64 bits of every recorded odometry (every control step)."""
        digest = hashlib.sha256()
        for step in self.odometry:
            for odometry in step:
                digest.update(struct.pack("<13d", *dataclasses.astuple(odometry)))
        return digest.hexdigest()


def hull_dynamics(vessel: ConcreteVessel, environment: EnvironmentConfig) -> VesselDynamics:
    """The dynamics of the vessel's generated model, as vessel_model_generator.generate_vessel_model derives them."""
    wind_speed = float(np.linalg.norm(environment.wind_vector))
    return derive_vessel_dynamics(vessel, wind_speed, load_vessel_dynamics_overrides().for_vessel(vessel))


def thruster_constants(dynamics: VesselDynamics) -> Dict[str, float]:
    """The Thruster system's constants as the SDF gives them to gz sim (rounded), for the actuator's check of applied thrust."""
    return {
        "thrust_coefficient": sdf_value(dynamics.thrust_coefficient),
        "propeller_diameter": sdf_value(dynamics.propeller_diameter),
        "fluid_density": FLUID_DENSITY,
        "max_thrust": sdf_value(dynamics.max_thrust),
    }


def run_gz_lockstep(
    link: GzLockstepLink,
    models: Mapping[int, str],
    participants: Mapping[int, LockstepParticipant],
    autopilots: Mapping[int, TwinThrustAutopilot],
    vessels: Mapping[int, ConcreteVessel],
    thrusters: Mapping[int, Mapping[str, float]],
    dt: float,
    steps: int,
    run_seed: int,
    *,
    control_dt: float = CONTROL_DT_S,
    settle_s: float = SETTLE_S,
    on_step: Optional[StepObserver] = None,
) -> GzRunResult:
    """Start the actuator on the models, let them settle, then run `steps` scenario steps of dt. Everything is keyed by vessel id."""
    vessel_ids = tuple(sorted(models))
    sub_steps = int(round(dt / control_dt))
    iterations = int(round(control_dt / PHYSICS_STEP_S))
    if sub_steps < 1 or abs(sub_steps * control_dt - dt) > 1e-9 or abs(iterations * PHYSICS_STEP_S - control_dt) > 1e-9:
        raise ValueError(f"dt {dt} must be a whole number of control steps of {control_dt} s, and each a whole number of {PHYSICS_STEP_S} s physics steps")
    clock = LockstepClock(dt, (participants[vessel_id].participant_id for vessel_id in vessel_ids))
    seeds: Dict[str, int] = {}
    for vessel_id in vessel_ids:
        participant = participants[vessel_id]
        seeds[participant.participant_id] = derive_seed(run_seed, participant.participant_id)
        participant.start(seeds[participant.participant_id])
        autopilots[vessel_id].reset()

    step_ns = int(round(PHYSICS_STEP_S * 1e9))
    latest = link.start({models[vessel_id]: thrusters[vessel_id] for vessel_id in vessel_ids}, step_ns, int(round(settle_s / PHYSICS_STEP_S)))
    epoch = latest.sim_time_ns
    odometry_log: List[Tuple[HullOdometry, ...]] = [tuple(latest.odometry[models[vessel_id]] for vessel_id in vessel_ids)]
    recorded: List[Tuple[ActorState, ...]] = []
    late = 0
    wall_start = time.monotonic()
    for index in range(steps + 1):
        states = {vessel_id: latest.odometry[models[vessel_id]].actor_state() for vessel_id in vessel_ids}
        recorded.append(tuple(states[vessel_id] for vessel_id in vessel_ids))
        if on_step is not None:
            on_step(index, dict(states))
        if index == steps:
            break
        commands = _step_commands(clock, participants, vessels, states)
        for _ in range(sub_steps):
            thrust = {}
            for vessel_id in vessel_ids:
                hull = latest.odometry[models[vessel_id]]
                command = autopilots[vessel_id].command(commands[vessel_id].heading, commands[vessel_id].speed, hull.observation(), control_dt)
                thrust[models[vessel_id]] = (command.port, command.starboard)
            latest = link.step(iterations, thrust)
            late += len(latest.late)
            odometry_log.append(tuple(latest.odometry[models[vessel_id]] for vessel_id in vessel_ids))
    return GzRunResult(
        vessel_ids=vessel_ids,
        dt=dt,
        control_dt=control_dt,
        run_seed=run_seed,
        participant_seeds=tuple(sorted(seeds.items())),
        states=tuple(recorded),
        odometry=tuple(odometry_log),
        late_commands=late,
        epoch_sim_time_ns=epoch,
        wall_s=time.monotonic() - wall_start,
        run_record={},
    )


def _step_commands(clock: LockstepClock, participants: Mapping[int, LockstepParticipant], vessels: Mapping[int, ConcreteVessel], states: Mapping[int, ActorState]) -> Dict[int, HeadingSpeedCommand]:
    request = clock.request()
    commands = {}
    acks = []
    for vessel_id in sorted(states):
        participant = participants[vessel_id]
        observation = VesselStateObservation(
            sim_time=request.time,
            vessel=vessels[vessel_id],
            own_state=states[vessel_id],
            target_states={other: state for other, state in states.items() if other != vessel_id},
        )
        commands[vessel_id] = participant.on_step(request, observation)
        acks.append(StepAck(participant_id=participant.participant_id, index=request.index))
    clock.advance(acks)
    return commands


def gz_custom_instance(
    trajectories: Trajectories,
    asv_system: Optional[Mapping[int, AsvSystemId]] = None,
    *,
    environment: Optional[EnvironmentConfig] = None,
    speedup: int = 1,
) -> SimulationInstanceConfig:
    """A Gazebo instance where every vessel runs on the custom control layer; replay unless asv_system names another per vessel id.

    Agent names (and so model names) are vessel_<id>. Feed it to build_simulation_docker_stack_artifacts
    for the stack and to run_gz_custom for the run.
    """
    asv_system = dict(asv_system or {})
    return SimulationInstanceConfig(
        simulation_layer=SimulationLayerId.GAZEBO,
        environment=environment or EnvironmentConfig.calm(),
        speedup=speedup,
        vessels={
            str(vessel.id): VesselConfig(
                agent_id=str(vessel.id),
                stack=VesselStackConfig(asv_system.get(vessel.id, AsvSystemId.REPLAY), ControlLayerId.CUSTOM, SimulationLayerId.GAZEBO),
                connection=AgentConnection(agent_name=f"vessel_{vessel.id}", topic="", port=None),
            )
            for vessel in trajectories.initial_scene.vessels
        },
    )


def run_gz_custom(
    trajectories: Trajectories,
    simulation: SimulationInstanceConfig,
    *,
    host: str = "gazebo",
    port: int = DEFAULT_PORT,
    dt: Optional[float] = None,
    steps: Optional[int] = None,
    control_dt: float = CONTROL_DT_S,
    usv_navigation_parameters: Optional[Mapping[int, UsvNavigationParameters]] = None,
    machine: Optional[str] = None,
    resolver: Optional[StackResolver] = None,
    connect_timeout_s: float = 600.0,
    on_step: Optional[StepObserver] = None,
    hosting: Optional[StackHosting] = None,
) -> GzRunResult:
    """Run every simulated vessel on a running Gazebo stack with the custom controller, through the registry.

    The instance is validated as an unattended run (machine names the host for per-host limits).
    hosting decides where each vessel's ASV system and autopilot run: in this process by default,
    in the vessel's ASV system and controller containers with ContainerHosting. Replay hands the
    controller its trajectory as a waypoint mission, which the controller's line-of-sight follower
    steers; USV Navigation (parameters from its trajectory unless given) sets the autopilot's
    heading and speed every step. host and port reach the gz-transport actuator in the Gazebo
    container. dt defaults to the trajectory time step and steps to its timespan. The run seed is
    environment.seed.
    """
    resolver = resolver or default_resolver()
    resolution = resolver.require_instance(simulation, attended=False, host=machine)
    wrong = [f"vessel {agent_id} runs on {chain.stack.control_layer.value}" for agent_id, chain in resolution.chains.items() if chain.stack.control_layer != ControlLayerId.CUSTOM]
    if wrong:
        raise StackUnavailableError([f"run_gz_custom needs the custom control layer for every simulated vessel: {', '.join(wrong)}"])
    hosting = hosting or InProcessHosting()
    dt = float(trajectories.time_step) if dt is None else dt
    scene = trajectories.initial_scene
    models: Dict[int, str] = {}
    participants: Dict[int, LockstepParticipant] = {}
    autopilots: Dict[int, TwinThrustAutopilot] = {}
    vessels: Dict[int, ConcreteVessel] = {}
    thrusters: Dict[int, Dict[str, float]] = {}
    navigation_parameters: Dict[int, UsvNavigationParameters] = {}
    link = GzLockstepLink(host, port)
    try:
        for agent_id, vessel_config in simulation.simulated_vessels.items():
            vessel = scene.get_by_id(agent_id)
            if not isinstance(vessel, ConcreteVessel):
                raise ValueError(f"Vessel {vessel} is not a ConcreteVessel.")
            software = vessel_config.stack.asv_system
            if software == AsvSystemId.USV_NAVIGATION:
                navigation_parameters[vessel.id] = parameters_for(vessel, trajectories, dt, usv_navigation_parameters)
            agent_name = vessel_config.require_connection().agent_name
            request = ParticipantRequest(
                vessel=vessel,
                agent_name=agent_name,
                asv_system=software,
                adapter=resolution.chains[agent_id].asv_adapter,
                trajectories=trajectories,
                dt=dt,
                parameters=navigation_parameters.get(vessel.id),
            )
            dynamics = hull_dynamics(vessel, simulation.environment)
            participants[vessel.id], autopilots[vessel.id] = hosting.custom_control(request, AutopilotGains.from_dynamics(dynamics, vessel, control_dt))
            thrusters[vessel.id] = thruster_constants(dynamics)
            models[vessel.id] = agent_name
            vessels[vessel.id] = vessel
        steps = steps if steps is not None else int(round(trajectories.timespan / dt))
        link.connect(connect_timeout_s)
        result = run_gz_lockstep(link, models, participants, autopilots, vessels, thrusters, dt, steps, simulation.environment.seed, control_dt=control_dt, on_step=on_step)
    finally:
        link.close()
        hosting.close()

    tier = resolution.repeatability_tier
    run_record = {
        "stack": sorted({str(vessel.stack) for vessel in simulation.simulated_vessels.values()}),
        "specs": list(dict.fromkeys(spec.id for chain in resolution.chains.values() for spec in chain.specs)),
        "dt": dt,
        "control_dt": control_dt,
        "physics_step_s": PHYSICS_STEP_S,
        "steps": result.steps,
        "speedup": simulation.speedup,
        "achieved_speedup": result.achieved_speedup,
        "epoch_sim_time_ns": result.epoch_sim_time_ns,
        "late_commands": result.late_commands,
        "run_seed": simulation.environment.seed,
        "participant_seeds": dict(result.participant_seeds),
        "repeatability_tier": tier.value if tier is not None else None,
        "environment": resolution.effective_environment(),
        "state_digest": result.state_digest(),
    }
    if navigation_parameters:
        run_record["usv_navigation"] = {str(vessel_id): parameters.as_dict() for vessel_id, parameters in sorted(navigation_parameters.items())}
    return dataclasses.replace(result, run_record=run_record)
