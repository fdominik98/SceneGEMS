"""
WebSocket message shapes shared with the React frontend (`src/domain/simulation/wireTypes.ts`).

Copy this package into your FastAPI project and extend `SimulationSession` to call your
`concrete_level` / monitor / trajectory code.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

import numpy as np

from scenegems_tool.simulators.simulation_config import SimulatedAgentConfig, SimulationConfig, WaveConfig


class LoadScenarioFileMessage(TypedDict):
    type: Literal["load_scenario_file"]
    scenarioId: str
    fileName: str
    filePath: str
    fileContent: str


class GenerateSceneMessage(TypedDict):
    type: Literal["generate_scene"]
    requestId: str
    functionalScenarioContent: str
    colregsConstraintsContent: str
    vesselTypesContent: str
    obstacleTypesContent: str
    timeout: int


class ConnectToWARAPSMessage(TypedDict):
    type: Literal["connect_to_waraps"]
    user: str
    password: str
    agent_broker: str
    client_broker: str
    port: int
    tls_connection: bool
    allow_certificates: bool


class SimulationStatusMessage(TypedDict):
    type: Literal["simulation_status"]
    status: str


class StopSceneGenerationMessage(TypedDict):
    type: Literal["stop_scene_generation"]


class GenerateTrajectoriesMessage(TypedDict):
    type: Literal["generate_trajectories"]
    requestId: str
    scenarioContent: str
    colregsConstraintsContent: str
    params: Dict[str, Any]


class StopTrajectoryGenerationMessage(TypedDict):
    type: Literal["stop_trajectory_generation"]


class DisconnectFromWARAPSMessage(TypedDict):
    type: Literal["disconnect_from_waraps"]


class ReferenceGeofencePayload(TypedDict):
    """Circular geofence: WGS84 center and radius in meters."""

    latitude: float
    longitude: float
    radius: float


class StartSimulationMessage(TypedDict):
    type: Literal["start_simulation"]


class ResetSimulationMessage(TypedDict):
    type: Literal["reset_simulation"]


class SimulationConnectionInfo(TypedDict):
    context: str
    controlMode: str
    agentName: str
    topic: str
    port: Optional[int]
    gazeboVesselModel: Optional[str]


class WaveInfo(TypedDict):
    amplitude: float
    period: float
    steepness: float
    direction: List[float]


class SimulationModelsBody(TypedDict):
    """Shared body for initialize_simulation / generate_simulation_models / simulation_models."""

    simulatorType: str
    windVector: List[float]
    wave: WaveInfo
    simulationSpeed: int
    connectionsByAgentId: Dict[str, SimulationConnectionInfo]


class InitializeSimulationMessage(SimulationModelsBody):
    type: Literal["initialize_simulation"]


class GenerateSimulationModelsMessage(SimulationModelsBody):
    type: Literal["generate_simulation_models"]


class InitializeMonitorMessage(TypedDict):
    type: Literal["initialize_monitor"]
    scope: str
    name: str
    topic: str
    colregsConstraintsContent: str


class ShutDownMonitorMessage(TypedDict):
    type: Literal["shut_down_monitor"]


ClientMessage = Union[
    LoadScenarioFileMessage,
    ConnectToWARAPSMessage,
    DisconnectFromWARAPSMessage,
    StartSimulationMessage,
    ResetSimulationMessage,
    InitializeSimulationMessage,
    InitializeMonitorMessage,
    GenerateSceneMessage,
    StopSceneGenerationMessage,
    GenerateTrajectoriesMessage,
    StopTrajectoryGenerationMessage,
    ShutDownMonitorMessage,
    GenerateSimulationModelsMessage,
]


class InitialStateMessage(TypedDict, total=False):
    type: Literal["initial_state"]
    sessionId: str
    scenarioId: str
    timeStep: int
    trajectoryLength: int
    frame: Dict[str, Any]


class PreviewTrajectoryChunkMessage(TypedDict):
    type: Literal["preview_trajectory_chunk"]
    scenarioId: str
    fromTimestamp: int
    toTimestamp: int
    frames: List[Dict[str, Any]]


class SimulationTrajectoryChunkMessage(TypedDict):
    type: Literal["simulation_trajectory_chunk"]
    scenarioId: str
    fromTimestamp: int
    toTimestamp: int
    frames: List[Dict[str, Any]]


class GeneratedSceneMessage(TypedDict):
    type: Literal["generated_scene"]
    requestId: str
    scene: Dict[str, Any]
    evaluationData: Dict[str, Any]
    valid: bool


class TrajectoryGenerationPreviewMessage(TypedDict):
    type: Literal["trajectory_generation_preview"]
    requestId: str
    trajectoryData: Dict[str, Any]


class TrajectoryGenerationResultMessage(TypedDict, total=False):
    type: Literal["trajectory_generation_result"]
    requestId: str
    trajectoryData: Optional[Dict[str, Any]]
    valid: bool
    errorMessage: Optional[str]


class ErrorMessage(TypedDict):
    type: Literal["error"]
    message: str


class WarAPSStatusMessage(TypedDict):
    type: Literal["waraps_status"]
    status: str


class SimulationStatus(Enum):
    NOT_INITIALIZED = "not initialized"
    INITIALIZING = "initializing"
    AGENTS_ARE_PREPARING = "agents are preparing"
    READY_TO_START = "ready to start"
    STARTING = "starting"
    RUNNING = "running"


class MonitorStatusMessage(TypedDict):
    type: Literal["monitor_status"]
    status: str


class SimulationModelsMessage(SimulationModelsBody):
    type: Literal["simulation_models"]


ServerMessage = Union[
    InitialStateMessage,
    PreviewTrajectoryChunkMessage,
    SimulationTrajectoryChunkMessage,
    ErrorMessage,
    WarAPSStatusMessage,
    Dict[str, Any],
    SimulationStatusMessage,
    MonitorStatusMessage,
    GeneratedSceneMessage,
    TrajectoryGenerationPreviewMessage,
    TrajectoryGenerationResultMessage,
    SimulationModelsMessage,
]


def make_initial_state_message(
    scenario_id: str,
    time_step: int,
    trajectory_length: int,
) -> InitialStateMessage:
    message: InitialStateMessage = {"type": "initial_state"}
    message["scenarioId"] = scenario_id
    message["timeStep"] = time_step
    message["trajectoryLength"] = trajectory_length
    return message


def make_error_message(message: str) -> ErrorMessage:
    line = f"Error message: {message}"
    try:
        print(line)
    except UnicodeEncodeError:
        # Windows consoles often use cp1252; long diagnostics may contain Unicode (e.g. U+2192).
        print(line.encode("ascii", errors="replace").decode("ascii"))
    return {"type": "error", "message": message}


def make_waraps_status_message(*, status: str) -> WarAPSStatusMessage:
    return {"type": "waraps_status", "status": status}


def make_generated_scene_message(request_id: str, scene: Dict[str, Any], evaluation_data: Dict[str, Any], valid: bool) -> GeneratedSceneMessage:
    return GeneratedSceneMessage(type="generated_scene", requestId=request_id, scene=scene, evaluationData=evaluation_data, valid=valid)


def make_monitor_status_message(*, status: str) -> MonitorStatusMessage:
    return MonitorStatusMessage(type="monitor_status", status=status)


def make_trajectory_generation_preview_message(request_id: str, trajectory_data: Dict[str, Any]) -> TrajectoryGenerationPreviewMessage:
    return TrajectoryGenerationPreviewMessage(
        type="trajectory_generation_preview",
        requestId=request_id,
        trajectoryData=trajectory_data,
    )


def make_trajectory_generation_result_message(
    request_id: str,
    trajectory_data: Optional[Dict[str, Any]],
    valid: bool,
    error_message: Optional[str],
) -> TrajectoryGenerationResultMessage:
    return TrajectoryGenerationResultMessage(
        type="trajectory_generation_result",
        requestId=request_id,
        trajectoryData=trajectory_data,
        valid=bool(valid),
        errorMessage=error_message,
    )


def _parse_agent_port(connection: SimulationConnectionInfo) -> Optional[int]:
    """Parse an agent connection port. A ``real`` context agent may omit the
    port (``None``); any other context requires a concrete port value."""
    raw_port = connection.get("port", None)
    if raw_port is None:
        if connection["context"] == "real":
            return None
        raise ValueError(f"Missing port for agent with context '{connection['context']}'.")
    return int(raw_port)


def simulation_config_from_body(body: SimulationModelsBody) -> SimulationConfig:
    """Convert an inbound simulation-models body (initialize_simulation /
    generate_simulation_models / simulation_models) into a domain SimulationConfig."""
    wave = body["wave"]
    return SimulationConfig(
        simulator_type=body["simulatorType"],
        wind_vector=np.array(body["windVector"]),
        wave=WaveConfig(
            amplitude=float(wave["amplitude"]),
            period=float(wave["period"]),
            steepness=float(wave["steepness"]),
            direction=np.array(wave["direction"]),
        ),
        simulation_speed=int(body.get("simulationSpeed", 1)),
        simulated_agents={
            agent_id: SimulatedAgentConfig(
                agent_id=agent_id,
                context=connection["context"],
                control_mode=connection["controlMode"],
                agent_name=connection["agentName"],
                topic=connection["topic"],
                port=_parse_agent_port(connection),
                gazebo_vessel_model=connection.get("gazeboVesselModel", None),
            )
            for agent_id, connection in body["connectionsByAgentId"].items()
        },
    )


def make_simulation_models_body(config: SimulationConfig) -> SimulationModelsBody:
    """Convert a domain SimulationConfig into the wire simulation-models body."""
    return SimulationModelsBody(
        simulatorType=config.simulator_type,
        windVector=[float(component) for component in config.wind_vector],
        wave=WaveInfo(
            amplitude=config.wave.amplitude,
            period=config.wave.period,
            steepness=config.wave.steepness,
            direction=[float(component) for component in config.wave.direction],
        ),
        simulationSpeed=int(config.simulation_speed),
        connectionsByAgentId={
            agent_id: SimulationConnectionInfo(
                context=agent.context,
                controlMode=agent.control_mode,
                agentName=agent.agent_name,
                topic=agent.topic,
                port=agent.port,
                gazeboVesselModel=agent.gazebo_vessel_model,
            )
            for agent_id, agent in config.simulated_agents.items()
        },
    )


def make_simulation_models_message(config: SimulationConfig) -> SimulationModelsMessage:
    body = make_simulation_models_body(config)
    return SimulationModelsMessage(type="simulation_models", **body)


def make_preview_chunk_message(
    scenario_id: str,
    from_timestamp: int,
    to_timestamp: int,
    frames: List[Dict[str, Any]],
) -> PreviewTrajectoryChunkMessage:
    return PreviewTrajectoryChunkMessage(
        type="preview_trajectory_chunk",
        scenarioId=scenario_id,
        fromTimestamp=from_timestamp,
        toTimestamp=to_timestamp,
        frames=frames,
    )


def make_simulation_chunk_message(
    scenario_id: str,
    from_timestamp: int,
    to_timestamp: int,
    frames: List[Dict[str, Any]],
) -> SimulationTrajectoryChunkMessage:
    return SimulationTrajectoryChunkMessage(
        type="simulation_trajectory_chunk",
        scenarioId=scenario_id,
        fromTimestamp=from_timestamp,
        toTimestamp=to_timestamp,
        frames=frames,
    )


def make_simulation_status_message(status: SimulationStatus) -> SimulationStatusMessage:
    return SimulationStatusMessage(type="simulation_status", status=status.value)
