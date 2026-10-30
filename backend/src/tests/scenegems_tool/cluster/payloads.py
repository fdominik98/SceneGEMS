"""Small valid payloads per job type, for tests that submit through the control plane, which validates them."""

import math
from functools import lru_cache
from typing import Any, Dict

from scenegems_tool.cluster.protocol.jobs import JobType
from utils.file_system_utils import FUNCTIONAL_MODELS_FOLDER


@lru_cache(maxsize=1)
def _functional_scenario() -> str:
    with open(f"{FUNCTIONAL_MODELS_FOLDER}/all/2vessel_0obstacle_scenarios/functional_model0.problem", encoding="utf-8") as file:
        return file.read()


@lru_cache(maxsize=1)
def trajectories_data() -> Dict[str, Any]:
    """Two vessels on reciprocal straight courses for ten seconds."""
    from concrete_level.models.actor_state import ActorState
    from concrete_level.models.concrete_actors import ConcreteActor
    from concrete_level.models.concrete_scene import ConcreteScene
    from concrete_level.trajectory_generation.trajectory_builder import TrajectoryBuilder

    def vessel(vessel_id: int, is_os: bool) -> ConcreteActor:
        return ConcreteActor.from_dict(
            {
                "id": vessel_id,
                "type": "OSPassengerShip" if is_os else "PassengerShip",
                "length": 30.0,
                "breadth": 10.0,
                "safety_radius": 120.0,
                "is_vessel": True,
                "_is_os": is_os,
                "_max_speed": 20.57778,
                "_max_angular_speed": 0.05,
                "_max_acceleration": 0.4,
            }
        )

    scene = ConcreteScene({vessel(0, True): ActorState(0.0, 0.0, 8.0, 0.0), vessel(1, False): ActorState(3000.0, 0.0, 8.0, math.pi)})
    return TrajectoryBuilder.default_trajectory_from_scene(scene, 1, 10).to_dict()


ARDUPILOT_LAYERS = {JobType.SIMULATION_ARDUPILOT_SIM: "ardupilot_sim", JobType.SIMULATION_GAZEBO: "gazebo"}


def valid_payload(job_type: JobType, **fields: Any) -> Dict[str, Any]:
    """A payload the job type's model accepts, with `fields` set on top."""
    if job_type == JobType.SCENE_GENERATION:
        base: Dict[str, Any] = {"functional_scenario_content": _functional_scenario(), "colregs_constraints_content": "", "vessel_types_content": "", "obstacle_types_content": ""}
    elif job_type == JobType.TRAJECTORY_GENERATION:
        base = {"scenario_content": "{}", "colregs_constraints_content": ""}
    elif job_type in ARDUPILOT_LAYERS:
        geofence = {"latitude": 57.7, "longitude": 11.9, "radius_meters": 2000.0}
        base = {"simulation_layer": ARDUPILOT_LAYERS[job_type], "trajectories": trajectories_data(), "geofence": geofence}
    elif job_type == JobType.CALIBRATION_DEVIATION:
        base = {"trajectories": [trajectories_data(), trajectories_data()], "reference": "head_on"}
    else:
        base = {"trajectories": trajectories_data()}
    return {**base, **fields}
