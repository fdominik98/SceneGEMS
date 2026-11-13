"""How each ASV system runs as a lockstep participant: in the runner's process, or in its own container.

An ASV system that SceneGEMS steps has two ways to run, and both give the same commands:

- in process: a LockstepParticipant built in the caller's process (tests, calibration);
- in its container: the software's server answers the lockstep wire protocol, and the runner
  holds an AsvSystemLink to it. The start config it gets is the software's own.

To add an ASV system: write its participant (or its server, for software that lives only in
its image, as MOOS-IvP does), give it a ContainerSpec and a service generator, and add one
AsvSystemRuntime to _RUNTIME_LOADERS here. The hosting (vessel_stack/hosting.py) needs no change.
The lockstep runners take the parameters of software that has any through RunParameters, which
asks the runtime for a vessel's defaults.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional

from concrete_level.models.actor_state import ActorState
from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.trajectories import Trajectories
from scenegems_tool.vessel_stack.contracts.adapter_spec import AdapterSpec
from scenegems_tool.vessel_stack.contracts.clock import LockstepParticipant
from scenegems_tool.vessel_stack.contracts.ports import Port
from scenegems_tool.vessel_stack.contracts.roles import AsvSystemId


@dataclass(frozen=True)
class ParticipantRequest:
    """One vessel's ASV system in one run."""

    vessel: ConcreteVessel
    agent_name: str  # names the vessel's services on the stack network (contracts/stack_services.py)
    asv_system: AsvSystemId
    adapter: AdapterSpec  # from the ASV system to the vessel's control layer
    trajectories: Trajectories
    dt: float
    parameters: Optional[Any] = None  # the software's own parameters, where it has any (UsvNavigationParameters, MoosIvpParameters)

    @property
    def participant_id(self) -> str:
        return f"{self.asv_system.value}/{self.vessel.id}"

    @property
    def reference_states(self) -> List[ActorState]:
        return self.trajectories.state_list(self.vessel)

    @property
    def hands_over_mission(self) -> bool:
        """The software gives its controller a waypoint mission to follow, instead of a command every step."""
        return Port.WAYPOINT_MISSION in self.adapter.provides_ports


@dataclass(frozen=True)
class AsvSystemRuntime:
    in_process: Callable[[ParticipantRequest], LockstepParticipant]
    start_config: Callable[[ParticipantRequest], Dict[str, Any]]  # the config of the wire protocol's start message
    # The software's parameters for a vessel when the caller gave none (vessel, trajectories, dt); None for software without parameters.
    default_parameters: Optional[Callable[[ConcreteVessel, Trajectories, float], Any]] = None


def vessel_limits(vessel: ConcreteVessel) -> Dict[str, Any]:
    """The vessel block of the wire protocol's start message: what any ASV system may need to know about its vessel."""
    return {
        "id": vessel.id,
        "length": float(vessel.length),
        "max_speed": float(vessel.max_speed),
        "max_acceleration": float(vessel.max_acceleration),
        "max_angular_speed": float(vessel.max_angular_speed),
    }


# Loaders import on first use, so naming a software never imports the code that runs it.
def _replay() -> AsvSystemRuntime:
    from scenegems_tool.vessel_stack.asv_system.replay.replay_server import replay_in_process, replay_start_config

    return AsvSystemRuntime(in_process=replay_in_process, start_config=replay_start_config)


def _usv_navigation() -> AsvSystemRuntime:
    from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_parameters import parameters_for
    from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_participant import usv_navigation_in_process, usv_navigation_start_config

    return AsvSystemRuntime(in_process=usv_navigation_in_process, start_config=usv_navigation_start_config, default_parameters=parameters_for)


def _moos_ivp() -> AsvSystemRuntime:
    from scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_participant import moos_ivp_default_parameters, moos_ivp_in_process, moos_ivp_start_config

    return AsvSystemRuntime(in_process=moos_ivp_in_process, start_config=moos_ivp_start_config, default_parameters=moos_ivp_default_parameters)


_RUNTIME_LOADERS: Dict[AsvSystemId, Callable[[], AsvSystemRuntime]] = {
    AsvSystemId.REPLAY: _replay,
    AsvSystemId.USV_NAVIGATION: _usv_navigation,
    AsvSystemId.MOOS_IVP: _moos_ivp,
}


def asv_system_runtime(asv_system: AsvSystemId) -> AsvSystemRuntime:
    loader = _RUNTIME_LOADERS.get(asv_system)
    if loader is None:
        raise LookupError(f"{asv_system.value} is not stepped by a lockstep runner")
    return loader()


class RunParameters:
    """The parameters of the ASV systems of one run's vessels: the caller's where it gave any, else the software's defaults.

    given holds, per ASV system, the parameters the caller chose by vessel id. A lockstep runner
    resolves every simulated vessel once, hands the result to the vessel's ParticipantRequest and
    writes record() into its run record.
    """

    def __init__(self, given: Optional[Mapping[AsvSystemId, Optional[Mapping[int, Any]]]] = None):
        self._given = {asv_system: dict(parameters) for asv_system, parameters in (given or {}).items() if parameters}
        self._chosen: Dict[int, Any] = {}
        self._asv_system: Dict[int, AsvSystemId] = {}

    def resolve(self, asv_system: AsvSystemId, vessel: ConcreteVessel, trajectories: Trajectories, dt: float) -> Optional[Any]:
        """The parameters of the vessel's ASV system in this run; None for software that has none (replay)."""
        default_parameters = asv_system_runtime(asv_system).default_parameters if asv_system in _RUNTIME_LOADERS else None
        if default_parameters is None:
            return None
        parameters = self._given.get(asv_system, {}).get(vessel.id) or default_parameters(vessel, trajectories, dt)
        self._chosen[vessel.id] = parameters
        self._asv_system[vessel.id] = asv_system
        return parameters

    @property
    def by_vessel(self) -> Dict[int, Any]:
        """The resolved parameters by vessel id, of the vessels whose software has parameters."""
        return dict(self._chosen)

    def record(self) -> Dict[str, Dict[str, Any]]:
        """The run record's part: per ASV system (its id is the key), each vessel's parameters by vessel id."""
        record: Dict[str, Dict[str, Any]] = {}
        for vessel_id, parameters in sorted(self._chosen.items()):
            record.setdefault(self._asv_system[vessel_id].value, {})[str(vessel_id)] = parameters.as_dict()
        return record
