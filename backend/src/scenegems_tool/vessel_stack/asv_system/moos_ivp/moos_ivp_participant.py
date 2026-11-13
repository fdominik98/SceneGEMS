"""How a run configures the MOOS-IvP container of a vessel.

The helm itself (pHelmIvP) exists only in the component's image, so MOOS-IvP has no participant
in the caller's process: a run with it is hosted in containers (vessel_stack/hosting.py). This
module adds what belongs to SceneGEMS: the start config derived from MoosIvpParameters, the step
of the run and the lengths of the vessel's contacts.
"""

from typing import Any, Dict

from concrete_level.models.concrete_actors import ConcreteVessel
from concrete_level.models.trajectories import Trajectories
from scenegems_tool.vessel_stack.asv_system.asv_system_runtime import ParticipantRequest
from scenegems_tool.vessel_stack.asv_system.moos_ivp.moos_ivp_parameters import MoosIvpParameters, parameters_for
from scenegems_tool.vessel_stack.contracts.clock import LockstepParticipant


def moos_ivp_start_config(request: ParticipantRequest) -> Dict[str, Any]:
    """The config of the MOOS-IvP container's start message: the parameters in wire form, the step, and every other actor's length."""
    if not isinstance(request.parameters, MoosIvpParameters):
        raise ValueError(f"vessel {request.vessel.id} runs MOOS-IvP and needs MoosIvpParameters (moos_ivp_parameters.parameters_for)")
    contacts = {str(actor.id): {"length": float(actor.length)} for actor in request.trajectories.initial_scene.actors if actor.id != request.vessel.id}
    return {"dt": request.dt, **request.parameters.as_dict(), "contacts": contacts}


def moos_ivp_in_process(request: ParticipantRequest) -> LockstepParticipant:
    raise RuntimeError(f"vessel {request.vessel.id}: MOOS-IvP runs only in its container (the scenegems-moos-ivp image); host the stack in containers (vessel_stack/hosting.ContainerHosting)")


def moos_ivp_default_parameters(vessel: ConcreteVessel, trajectories: Trajectories, dt: float) -> MoosIvpParameters:
    return parameters_for(vessel, trajectories, dt)
