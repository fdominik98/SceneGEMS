"""Payload pieces shared by the job types, and payload parsing.

Each job type defines its payload as a ProtocolModel (frozen, unknown fields rejected).
Large inputs such as trajectories travel as the dictionaries their models serialize to
and are checked by building the model once, so a bad payload fails before any container starts.

A large input may also be an ArtifactRef (cluster/protocol/artifacts.py). Validation then
runs in two places:

    validate_structure(model, payload)  the control node, at submission: a reference is checked
                                        for shape only, inline data in full
    parse_payload(model, job)           the worker node, after it resolved every reference in the
                                        job type's ARTIFACT_INPUT_FIELDS: the content of
                                        every field is checked, and a reference that is
                                        still there fails the job
"""

from typing import Annotated, Any, Dict, Mapping, Optional, Tuple, Type, TypeVar

from pydantic import AfterValidator, Field, ValidationError

from scenegems_tool.cluster.protocol.artifacts import ArtifactRef, artifact_or, find_references
from scenegems_tool.cluster.protocol.jobs import JobSpec
from scenegems_tool.cluster.protocol.model_base import ProtocolModel
from scenegems_tool.cluster.worker_node.job_report import JobFailed

PayloadModel = TypeVar("PayloadModel", bound=ProtocolModel)


def _check_trajectories(data: Dict[str, Any]) -> Dict[str, Any]:
    from concrete_level.models.trajectories import Trajectories

    try:
        trajectories = Trajectories.from_dict(data)
    except Exception as error:
        raise ValueError(f"not a serialized Trajectories ({type(error).__name__}: {error})") from error
    if not trajectories.scene_list:
        raise ValueError("the trajectories hold no scene")
    return data


TrajectoriesData = Annotated[Dict[str, Any], AfterValidator(_check_trajectories)]  # Trajectories.to_dict()
TrajectoriesInput = artifact_or(TrajectoriesData)  # inline Trajectories.to_dict() or a reference to one


class GeofencePayload(ProtocolModel):
    """The reference geofence: the local frame's origin on the map."""

    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    radius_meters: float = Field(gt=0.0)

    def to_geofence(self):
        from scenegems_tool.vessel_stack.contracts.local_frame import Geofence

        return Geofence(latitude=self.latitude, longitude=self.longitude, radius_meters=self.radius_meters)


class WavePayload(ProtocolModel):
    amplitude: float = Field(ge=0.0)
    period: float = Field(ge=0.0)
    steepness: float = Field(ge=0.0)
    direction: Tuple[float, float]  # propagation vector [east, north]; its norm is the wave speed


class EnvironmentPayload(ProtocolModel):
    """Wind and waves of a run, as a campaign run's environment section writes them; calm water when left out."""

    wind_vector: Tuple[float, float, float] = (0.0, 0.0, 0.0)  # [east, north, up] m/s
    waves: Optional[WavePayload] = None

    def to_environment(self, seed: int = 0):
        """The EnvironmentConfig of the run with this seed."""
        import numpy as np

        from scenegems_tool.vessel_stack.contracts.vessel_stack_config import EnvironmentConfig, WaveConfig

        waves = self.waves
        wave = WaveConfig(amplitude=0.0, period=0.0, steepness=0.0, direction=np.zeros(2))
        if waves is not None:
            wave = WaveConfig(amplitude=waves.amplitude, period=waves.period, steepness=waves.steepness, direction=np.array(waves.direction, dtype=float))
        return EnvironmentConfig(wind_vector=np.array(self.wind_vector, dtype=float), wave=wave, seed=seed)


def to_trajectories(data: Dict[str, Any]):
    from concrete_level.models.trajectories import Trajectories

    if isinstance(data, ArtifactRef):
        raise JobFailed(f"Artifact {data.sha256} was not resolved before the job ran", retryable=False)
    return Trajectories.from_dict(data)


def validate_structure(model: Type[PayloadModel], payload: Mapping[str, Any]) -> PayloadModel:
    """The payload as its type's model, references checked for shape only; raises ValidationError."""
    return model.model_validate(payload)


def parse_payload(model: Type[PayloadModel], job: JobSpec) -> PayloadModel:
    """The job's resolved payload as its type's model; an invalid or unresolved payload fails for good, without a retry."""
    try:
        payload = model.model_validate(job.payload)
    except ValidationError as error:
        raise JobFailed(f"Invalid {job.job_type.value} payload: {error}", retryable=False) from error
    unresolved = find_references(payload)
    if unresolved:
        paths = ", ".join(".".join(str(part) for part in path) for path, _ in unresolved)
        raise JobFailed(f"The {job.job_type.value} payload still holds artifact references ({paths}); they are resolved before the job runs", retryable=False)
    return payload
