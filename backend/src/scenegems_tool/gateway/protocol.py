"""
WebSocket message shapes shared with the React frontend (`src/domain/simulation/wireTypes.ts`).

Copy this package into your FastAPI project and extend `SimulationSession` to call your
`concrete_level` / monitor / trajectory code.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, NotRequired, Optional, Required, TypedDict, Union

import numpy as np

from scenegems_tool.gateway.workbench_stack_mapping import control_mode_label, simulation_layer_from_simulator_type, simulator_type_label, workbench_adapter_ids, workbench_stack
from scenegems_tool.vessel_stack.contracts.vessel_stack_config import AgentConnection, AgentContext, EnvironmentConfig, SimulationInstanceConfig, VesselConfig, WaveConfig


class LoadScenarioFileMessage(TypedDict):
    type: Literal["load_scenario_file"]
    scenarioId: str
    fileName: str
    filePath: str
    fileContent: str


class GeofencePayload(TypedDict):
    """Circular reference geofence: WGS84 center and radius in meters.

    Matches the frontend `wireTypes.ts` `connect_to_mqtt_broker.geofence` shape and the
    keys read in `socket_message_processor.py`.
    """

    latitude: float
    longitude: float
    radius_meters: float


class ConnectToMqttBrokerMessage(TypedDict):
    """Connect the workbench's interactive simulation to an MQTT broker.

    With use_control_node_broker the broker is the control node's own cluster broker (mqtt_broker_status
    names it in controlNodeBroker) and the address, user and TLS fields are ignored.
    """

    type: Literal["connect_to_mqtt_broker"]
    user: str
    password: str
    agent_broker: str
    client_broker: str
    port: int
    tls_connection: bool
    allow_certificates: bool
    geofence: GeofencePayload
    use_control_node_broker: NotRequired[bool]


class SimulationStatusMessage(TypedDict):
    type: Literal["simulation_status"]
    status: str
    # Host port of each Mission Planner vessel's ground control station endpoint (TCP on localhost), by agent id.
    groundControlPortsByAgentId: NotRequired[Dict[str, int]]


class QueryStackOptionsMessage(TypedDict):
    type: Literal["query_stack_options"]


class StackOptionsMessage(TypedDict):
    """Every (simulatorType, asvSystem, controlLayer) the resolver knows, with whether the workbench can run it and why not."""

    type: Literal["stack_options"]
    simulatorTypes: List[str]
    asvSystem: List[str]
    controlLayers: List[str]
    combinations: List[Dict[str, Any]]


class DisconnectFromMqttBrokerMessage(TypedDict):
    type: Literal["disconnect_from_mqtt_broker"]


class StartSimulationMessage(TypedDict):
    type: Literal["start_simulation"]


class ResetSimulationMessage(TypedDict):
    type: Literal["reset_simulation"]


class SimulationConnectionInfo(TypedDict):
    context: str
    # The agent's stack: asvSystem and controlLayer (AsvSystemId and ControlLayerId values). An
    # older client sends only controlMode (autonomous or external), which names the ASV system.
    asvSystem: NotRequired[str]
    controlLayer: NotRequired[str]
    controlMode: NotRequired[str]
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
    # [east, north, up] in m/s; exactly 3 components (validated in simulation_config_from_body).
    windVector: List[float]
    wave: WaveInfo
    # Integer physics speed-up factor (1 = real-time); sub-real-time is not supported.
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


# Scene generation, trajectory generation and monitoring of loaded scenes are not here: the
# workbench submits them as jobs to the cluster's operator API.
ClientMessage = Union[
    LoadScenarioFileMessage,
    ConnectToMqttBrokerMessage,
    DisconnectFromMqttBrokerMessage,
    StartSimulationMessage,
    ResetSimulationMessage,
    InitializeSimulationMessage,
    InitializeMonitorMessage,
    ShutDownMonitorMessage,
    GenerateSimulationModelsMessage,
    QueryStackOptionsMessage,
]


class InitialStateMessage(TypedDict, total=False):
    # `type` and `scenarioId` are always sent (see make_initial_state_message);
    # the frontend relies on `scenarioId` to route the trajectory chunks that
    # immediately follow this message.
    type: Required[Literal["initial_state"]]
    scenarioId: Required[str]
    timeStep: int
    trajectoryLength: int


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
    # Present when the subsystem sent it: false for the best partial path of a search that ended without a complete one.
    complete: bool
    errorMessage: Optional[str]


class ErrorMessage(TypedDict):
    type: Literal["error"]
    message: str


class MqttBrokerStatusMessage(TypedDict):
    type: Literal["mqtt_broker_status"]
    status: str
    # The control node's own broker as this server dials it ("host:port"), None when it has none.
    controlNodeBroker: Optional[str]


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


RunRecordingStatus = Literal["recording", "saved", "failed", "unavailable"]


class RunRecordingMessage(TypedDict):
    """Whether the live session's run is recorded as a workbench entry (design doc 6.4)."""

    type: Literal["run_recording"]
    status: RunRecordingStatus
    # The workbench entry the run is recorded as, and its case once the run is recorded; None before they exist.
    campaignId: Optional[str]
    caseId: Optional[int]
    message: Optional[str]


ServerMessage = Union[
    InitialStateMessage,
    PreviewTrajectoryChunkMessage,
    SimulationTrajectoryChunkMessage,
    ErrorMessage,
    MqttBrokerStatusMessage,
    Dict[str, Any],
    SimulationStatusMessage,
    StackOptionsMessage,
    MonitorStatusMessage,
    GeneratedSceneMessage,
    TrajectoryGenerationPreviewMessage,
    TrajectoryGenerationResultMessage,
    SimulationModelsMessage,
    RunRecordingMessage,
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


def make_mqtt_broker_status_message(*, status: str, control_node_broker: Optional[str]) -> MqttBrokerStatusMessage:
    return {"type": "mqtt_broker_status", "status": status, "controlNodeBroker": control_node_broker}


def make_generated_scene_message(request_id: str, scene: Dict[str, Any], evaluation_data: Dict[str, Any], valid: bool) -> GeneratedSceneMessage:
    return GeneratedSceneMessage(type="generated_scene", requestId=request_id, scene=scene, evaluationData=evaluation_data, valid=valid)


def make_monitor_status_message(*, status: str) -> MonitorStatusMessage:
    return MonitorStatusMessage(type="monitor_status", status=status)


def make_run_recording_message(status: RunRecordingStatus, campaign_id: Optional[str] = None, case_id: Optional[int] = None, message: Optional[str] = None) -> RunRecordingMessage:
    return RunRecordingMessage(type="run_recording", status=status, campaignId=campaign_id, caseId=case_id, message=message)


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
    complete: Optional[bool] = None,
) -> TrajectoryGenerationResultMessage:
    message = TrajectoryGenerationResultMessage(
        type="trajectory_generation_result",
        requestId=request_id,
        trajectoryData=trajectory_data,
        valid=bool(valid),
        errorMessage=error_message,
    )
    if complete is not None:
        message["complete"] = bool(complete)
    return message


def _parse_agent_port(connection: SimulationConnectionInfo) -> Optional[int]:
    """Parse an agent connection port. A ``real`` context agent may omit the
    port (``None``); any other context requires a concrete port value."""
    raw_port = connection.get("port", None)
    if raw_port is None:
        if connection["context"] == "real":
            return None
        raise ValueError(f"Missing port for agent with context '{connection['context']}'.")
    return int(raw_port)


def _parse_agent_context(connection: SimulationConnectionInfo) -> AgentContext:
    try:
        return AgentContext(connection["context"])
    except ValueError:
        raise ValueError(f"Unknown agent context '{connection['context']}'; expected one of {', '.join(context.value for context in AgentContext)}.") from None


def simulation_config_from_body(body: SimulationModelsBody) -> SimulationInstanceConfig:
    """Convert an inbound simulation-models body (initialize_simulation /
    generate_simulation_models / simulation_models) into a typed simulation instance.
    simulatorType and each agent's asvSystem and controlLayer (or controlMode) become one
    stack triple per vessel; a real agent's stack is on its own layers (real_vessel), and an
    instance with a real vessel selects the ArduAgent adapters (see gateway.workbench_stack_mapping)."""
    wave = body["wave"]
    wind_vector = list(body["windVector"])
    if len(wind_vector) != 3:
        raise ValueError(f"windVector must have 3 components [east, north, up]; got {len(wind_vector)}.")
    simulator_type = body["simulatorType"]
    connections = body["connectionsByAgentId"]
    contexts = {agent_id: _parse_agent_context(connection) for agent_id, connection in connections.items()}
    has_real_vessel = any(context == AgentContext.REAL for context in contexts.values())
    stacks = {
        agent_id: workbench_stack(
            simulator_type,
            connection.get("asvSystem"),
            connection.get("controlLayer"),
            connection.get("controlMode"),
            real_vessel=contexts[agent_id] == AgentContext.REAL,
        )
        for agent_id, connection in connections.items()
    }
    return SimulationInstanceConfig(
        simulation_layer=simulation_layer_from_simulator_type(simulator_type),
        environment=EnvironmentConfig(
            wind_vector=np.array(wind_vector, dtype=float),
            wave=WaveConfig(
                amplitude=float(wave["amplitude"]),
                period=float(wave["period"]),
                steepness=float(wave["steepness"]),
                direction=np.array(wave["direction"]),
            ),
        ),
        speedup=int(body.get("simulationSpeed", 1)),
        vessels={
            agent_id: VesselConfig(
                agent_id=agent_id,
                stack=stacks[agent_id],
                context=contexts[agent_id],
                connection=AgentConnection(agent_name=connection["agentName"], topic=connection["topic"], port=_parse_agent_port(connection)),
                gazebo_vessel_model=connection.get("gazeboVesselModel", None),
                adapter_ids=workbench_adapter_ids(stacks[agent_id], has_real_vessel),
            )
            for agent_id, connection in connections.items()
        },
    )


def _connection_info(vessel: VesselConfig) -> SimulationConnectionInfo:
    info = SimulationConnectionInfo(
        context=vessel.context.value,
        asvSystem=vessel.stack.asv_system.value,
        controlLayer=vessel.stack.control_layer.value,
        agentName=vessel.require_connection().agent_name,
        topic=vessel.require_connection().topic,
        port=vessel.require_connection().port,
        gazeboVesselModel=vessel.gazebo_vessel_model,
    )
    control_mode = control_mode_label(vessel.stack.asv_system)
    if control_mode is not None:
        info["controlMode"] = control_mode
    return info


def make_simulation_models_body(config: SimulationInstanceConfig) -> SimulationModelsBody:
    """Convert a typed simulation instance into the wire simulation-models body."""
    environment = config.environment
    return SimulationModelsBody(
        simulatorType=simulator_type_label(config.simulation_layer),
        windVector=[float(component) for component in environment.wind_vector],
        wave=WaveInfo(
            amplitude=environment.wave.amplitude,
            period=environment.wave.period,
            steepness=environment.wave.steepness,
            direction=[float(component) for component in environment.wave.direction],
        ),
        simulationSpeed=int(config.speedup),
        connectionsByAgentId={agent_id: _connection_info(vessel) for agent_id, vessel in config.vessels.items()},
    )


def make_simulation_models_message(config: SimulationInstanceConfig) -> SimulationModelsMessage:
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


def make_simulation_status_message(status: SimulationStatus, ground_control_ports: Optional[Dict[str, int]] = None) -> SimulationStatusMessage:
    message = SimulationStatusMessage(type="simulation_status", status=status.value)
    if ground_control_ports:
        message["groundControlPortsByAgentId"] = {agent_id: int(port) for agent_id, port in sorted(ground_control_ports.items())}
    return message
