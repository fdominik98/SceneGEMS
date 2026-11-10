"""Lockstep runner for the kinematic layer, with a replay run of generated trajectories and a
closed-loop run of USV Navigation against replaying targets.

The runner owns no time of its own: every step it takes the simulation's step request,
collects one command and one acknowledgement per participant, and lets the simulation
advance. A run is bit-identical across repeats and processes for the same inputs.

The simulation and the participants come from a hosting (vessel_stack/hosting.py): built in this
process, or the kinematic simulator's container and every vessel's ASV software container. The
run is the same either way, digest included.

An optional step observer sees the recorded states after the start and after every step,
and may end the run there (the live monitor's early stop). Without one, the loop is the
same as before it existed.
"""

import dataclasses
import hashlib
import struct
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteActor, ConcreteVessel
from concrete_level.models.trajectories import Trajectories
from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder
from scenegems_tool.vessel_stack.asv_software.asv_software_runtime import ParticipantRequest
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_parameters import UsvNavigationParameters, parameters_for
from scenegems_tool.vessel_stack.asv_software.usv_navigation.usv_navigation_specs import COLAV_AUTOMATON_COMMIT
from scenegems_tool.vessel_stack.contracts.clock import LockstepParticipant, StepAck, derive_seed
from scenegems_tool.vessel_stack.contracts.roles import AsvSoftwareId, ControlLayerId, SimulationLayerId
from scenegems_tool.vessel_stack.contracts.stack_services import stack_agent_name
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, SimulationInstanceConfig, VesselConfig, VesselStackConfig
from scenegems_tool.vessel_stack.hosting import InProcessHosting, StackHosting, participant_reports
from scenegems_tool.vessel_stack.registry.catalog import default_resolver
from scenegems_tool.vessel_stack.registry.resolver import InstanceResolution, StackResolver
from scenegems_tool.vessel_stack.simulation_layers.kinematic.kinematic_simulation import KinematicSimulation

KINEMATIC_REPLAY_STACK = VesselStackConfig(asv_software=AsvSoftwareId.REPLAY, control_layer=ControlLayerId.NONE, simulation_layer=SimulationLayerId.KINEMATIC)
KINEMATIC_USV_NAVIGATION_STACK = VesselStackConfig(asv_software=AsvSoftwareId.USV_NAVIGATION, control_layer=ControlLayerId.NONE, simulation_layer=SimulationLayerId.KINEMATIC)
_KINEMATIC_STACKS = {AsvSoftwareId.REPLAY: KINEMATIC_REPLAY_STACK, AsvSoftwareId.USV_NAVIGATION: KINEMATIC_USV_NAVIGATION_STACK}

# Called with the step index (0 for the initial states) and the states in actor order after
# that step; returning True ends the run after the step.
StepObserver = Callable[[int, Tuple[ActorState, ...]], bool]


@dataclass(frozen=True)
class KinematicRunResult:
    actors: Tuple[ConcreteActor, ...]
    dt: float
    run_seed: int
    participant_seeds: Tuple[Tuple[str, int], ...]
    states: Tuple[Tuple[ActorState, ...], ...]  # per step from t = 0, one state per actor in `actors` order
    run_record: Mapping[str, Any]

    @property
    def steps(self) -> int:
        return len(self.states) - 1

    def state_digest(self) -> str:
        """SHA-256 over the exact float64 bits of every recorded state."""
        digest = hashlib.sha256()
        for step_states in self.states:
            for state in step_states:
                digest.update(struct.pack("<4d", float(state.x), float(state.y), float(state.speed), float(state.heading)))
        return digest.hexdigest()

    def to_trajectories(self) -> Trajectories:
        if not float(self.dt).is_integer():
            raise ValueError(f"Trajectories need an integer time step; this run used dt={self.dt}")
        builder = TrajectoryBuilder(time_step=int(self.dt))
        for step_states in self.states:
            builder.add_scene_as_dict(dict(zip(self.actors, step_states)))
        return builder.build()


@dataclass(frozen=True)
class KinematicInstanceRun:
    """One run of a kinematic instance, with what its run record is written from."""

    result: KinematicRunResult
    resolution: InstanceResolution
    parameters: Mapping[int, UsvNavigationParameters]  # of the vessels on USV Navigation, by vessel id
    reports: Mapping[int, Mapping[str, Any]]  # what each ASV software reported, by vessel id

    @property
    def stacks(self) -> Dict[str, str]:
        """Every vessel's stack, by agent id in vessel order."""
        return {agent_id: str(vessel.stack) for agent_id, vessel in sorted(self.resolution.instance.vessels.items(), key=lambda item: int(item[0]))}

    @property
    def spec_ids(self) -> List[str]:
        return _unique_ids(spec.id for chain in self.resolution.chains.values() for spec in chain.specs)

    def record(self, dt: float, **entries: Any) -> Dict[str, Any]:
        """The run record: the caller's entries first, then what every kinematic run records."""
        tier = self.resolution.repeatability_tier
        return {
            **entries,
            "dt": dt,
            "steps": self.result.steps,
            "run_seed": self.result.run_seed,
            "participant_seeds": dict(self.result.participant_seeds),
            "repeatability_tier": tier.value if tier is not None else None,
            "environment": self.resolution.effective_environment(),
            "state_digest": self.result.state_digest(),
        }


def run_lockstep(simulation: KinematicSimulation, participants: Mapping[int, LockstepParticipant], steps: int, run_seed: int, on_step: Optional[StepObserver] = None) -> KinematicRunResult:
    """Run `steps` lockstep steps, fewer when on_step ends the run. `participants` maps a vessel id to the participant that commands it.

    simulation is a KinematicSimulation or anything with its interface (the link to the simulator's container).
    """
    ordered = sorted(participants.items())
    participant_ids = tuple(sorted(participant.participant_id for _, participant in ordered))
    if participant_ids != simulation.clock.participant_ids:
        raise ValueError(f"Participants {participant_ids} do not match the clock participants {simulation.clock.participant_ids}")
    seeds: Dict[str, int] = {}
    for _, participant in ordered:
        seeds[participant.participant_id] = derive_seed(run_seed, participant.participant_id)
        participant.start(seeds[participant.participant_id])

    recorded = [simulation.snapshot()]
    stopped = on_step is not None and on_step(0, recorded[0])
    for _ in range(0 if stopped else steps):
        request = simulation.step_request()
        commands = {}
        acks = []
        for vessel_id, participant in ordered:
            commands[vessel_id] = participant.on_step(request, simulation.observe(vessel_id))
            acks.append(StepAck(participant_id=participant.participant_id, index=request.index))
        simulation.step(commands, acks)
        recorded.append(simulation.snapshot())
        if on_step is not None and on_step(len(recorded) - 1, recorded[-1]):
            break
    return KinematicRunResult(
        actors=simulation.actors,
        dt=simulation.dt,
        run_seed=run_seed,
        participant_seeds=tuple(sorted(seeds.items())),
        states=tuple(recorded),
        run_record={},
    )


def kinematic_instance(trajectories: Trajectories, asv_software: Optional[Mapping[int, AsvSoftwareId]] = None, *, environment: Optional[EnvironmentConfig] = None) -> SimulationInstanceConfig:
    """A kinematic instance of every vessel of the trajectories; replay unless asv_software names another per vessel id."""
    asv_software = dict(asv_software or {})
    return SimulationInstanceConfig(
        simulation_layer=SimulationLayerId.KINEMATIC,
        environment=environment or EnvironmentConfig.calm(),
        vessels={str(vessel.id): VesselConfig(agent_id=str(vessel.id), stack=_KINEMATIC_STACKS[asv_software.get(vessel.id, AsvSoftwareId.REPLAY)]) for vessel in trajectories.initial_scene.vessels},
    )


def run_kinematic_instance(
    trajectories: Trajectories,
    instance: SimulationInstanceConfig,
    *,
    dt: Optional[float] = None,
    steps: Optional[int] = None,
    usv_navigation_parameters: Optional[Mapping[int, UsvNavigationParameters]] = None,
    hosting: Optional[StackHosting] = None,
    resolver: Optional[StackResolver] = None,
    attended: bool = False,
    on_step: Optional[StepObserver] = None,
) -> KinematicInstanceRun:
    """Run every simulated vessel of a kinematic instance in lockstep, each on the ASV software of its stack.

    The instance and its environment are validated by the resolver first, so wind or waves are
    rejected with a reason. hosting decides where the simulator and the ASV software run: in this
    process by default, in the stack's containers with ContainerHosting. A vessel on USV Navigation
    takes its parameters from usv_navigation_parameters (by vessel id), else from its generated
    trajectory. dt defaults to the trajectory time step and steps to its timespan. The run seed is
    the environment's. on_step observes every step and may end the run early.
    """
    resolver = resolver or default_resolver()
    resolution = resolver.require_instance(instance, attended=attended)
    hosting = hosting or InProcessHosting()
    dt = float(trajectories.time_step) if dt is None else dt
    scene = trajectories.initial_scene
    parameters: Dict[int, UsvNavigationParameters] = {}
    participants: Dict[int, LockstepParticipant] = {}
    try:
        for agent_id, vessel_config in instance.simulated_vessels.items():
            vessel = scene.get_by_id(agent_id)
            if not isinstance(vessel, ConcreteVessel):
                raise ValueError(f"Vessel {vessel} is not a ConcreteVessel.")
            software = vessel_config.stack.asv_software
            if software == AsvSoftwareId.USV_NAVIGATION:
                parameters[vessel.id] = parameters_for(vessel, trajectories, dt, usv_navigation_parameters)
            participants[vessel.id] = hosting.asv_software(
                ParticipantRequest(
                    vessel=vessel,
                    agent_name=stack_agent_name(vessel_config),
                    asv_software=software,
                    adapter=resolution.chains[agent_id].asv_adapter,
                    trajectories=trajectories,
                    dt=dt,
                    parameters=parameters.get(vessel.id),
                )
            )
        simulation = hosting.kinematic_simulation(scene, dt, [participant.participant_id for participant in participants.values()])
        result = run_lockstep(simulation, participants, steps if steps is not None else int(round(trajectories.timespan / dt)), instance.environment.seed, on_step)
        reports = participant_reports(participants)
    finally:
        hosting.close()
    return KinematicInstanceRun(result=result, resolution=resolution, parameters=parameters, reports=reports)


def run_kinematic_replay(
    trajectories: Trajectories,
    *,
    environment: Optional[EnvironmentConfig] = None,
    dt: Optional[float] = None,
    steps: Optional[int] = None,
    resolver: Optional[StackResolver] = None,
    on_step: Optional[StepObserver] = None,
    hosting: Optional[StackHosting] = None,
) -> KinematicRunResult:
    """Replay every vessel of a generated trajectory on the kinematic layer, through the registry.

    Every vessel runs (replay, none, kinematic). See run_kinematic_instance for the arguments.
    """
    dt = float(trajectories.time_step) if dt is None else dt
    run = run_kinematic_instance(trajectories, kinematic_instance(trajectories, environment=environment), dt=dt, steps=steps, hosting=hosting, resolver=resolver, on_step=on_step)
    return dataclasses.replace(run.result, run_record=run.record(dt, stack=str(KINEMATIC_REPLAY_STACK), specs=run.spec_ids))


def run_kinematic_closed_loop(
    trajectories: Trajectories,
    *,
    own_ship_id: Optional[int] = None,
    usv_navigation_parameters: Optional[UsvNavigationParameters] = None,
    environment: Optional[EnvironmentConfig] = None,
    dt: Optional[float] = None,
    steps: Optional[int] = None,
    resolver: Optional[StackResolver] = None,
    on_step: Optional[StepObserver] = None,
    hosting: Optional[StackHosting] = None,
) -> KinematicRunResult:
    """Close the loop around USV Navigation on the own ship while every other vessel replays its trajectory.

    The own ship (the scene's OS unless own_ship_id names another vessel) runs (usv_navigation,
    none, kinematic) and the other vessels run (replay, none, kinematic), all in one simulation
    and clock. The USV Navigation parameters default to UsvNavigationParameters.from_reference on
    the own ship's generated trajectory. See run_kinematic_instance for the other arguments.
    """
    dt = float(trajectories.time_step) if dt is None else dt
    scene = trajectories.initial_scene
    own = scene.os if own_ship_id is None else next((vessel for vessel in scene.vessels if vessel.id == own_ship_id), None)
    if own is None:
        raise ValueError(f"No vessel with id {own_ship_id} in the scene")
    instance = kinematic_instance(trajectories, {own.id: AsvSoftwareId.USV_NAVIGATION}, environment=environment)
    given = {own.id: usv_navigation_parameters} if usv_navigation_parameters is not None else None
    run = run_kinematic_instance(trajectories, instance, dt=dt, steps=steps, usv_navigation_parameters=given, hosting=hosting, resolver=resolver, on_step=on_step)
    navigation = run.reports.get(own.id, {})
    record = run.record(
        dt,
        stacks=run.stacks,
        specs=run.spec_ids,
        usv_navigation={
            "vessel": own.id,
            "colav_automaton_commit": COLAV_AUTOMATON_COMMIT,
            "parameters": run.parameters[own.id].as_dict(),
            "transitions": [list(transition) for transition in navigation.get("transitions", [])],
            "goal_reached_at": navigation.get("goal_reached_at"),
        },
    )
    return dataclasses.replace(run.result, run_record=record)


def _unique_ids(ids: Iterable[str]) -> List[str]:
    return list(dict.fromkeys(ids))
