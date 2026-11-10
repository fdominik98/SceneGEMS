"""How each ASV system runs as a lockstep participant: in the runner's process, or in its own container.

An ASV system that SceneGEMS steps has two ways to run, and both give the same commands:

- in process: a LockstepParticipant built in the caller's process (tests, calibration);
- in its container: the software's server answers the lockstep wire protocol, and the runner
  holds an AsvSystemLink to it. The start config it gets is the software's own.

To add an ASV system: write its participant (or its server, for software that lives only in
its image), give it a ContainerSpec and a service generator, and add one AsvSystemRuntime to
_RUNTIME_LOADERS here. The lockstep runners and the hosting (vessel_stack/hosting.py) need no change.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

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
    parameters: Optional[Any] = None  # the software's own parameters, where it has any (UsvNavigationParameters)

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
    from scenegems_tool.vessel_stack.asv_system.usv_navigation.usv_navigation_participant import usv_navigation_in_process, usv_navigation_start_config

    return AsvSystemRuntime(in_process=usv_navigation_in_process, start_config=usv_navigation_start_config)


_RUNTIME_LOADERS: Dict[AsvSystemId, Callable[[], AsvSystemRuntime]] = {
    AsvSystemId.REPLAY: _replay,
    AsvSystemId.USV_NAVIGATION: _usv_navigation,
}


def asv_system_runtime(asv_system: AsvSystemId) -> AsvSystemRuntime:
    loader = _RUNTIME_LOADERS.get(asv_system)
    if loader is None:
        raise LookupError(f"{asv_system.value} is not stepped by a lockstep runner")
    return loader()
