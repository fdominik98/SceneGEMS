"""
WebSocket message shapes shared with the React frontend (`src/domain/simulation/wireTypes.ts`).

The console sends the gateway three helper requests (load_scenario_file, generate_simulation_models,
query_stack_options). The other server messages here are what the console's job driver dispatches
from the results of cluster jobs (generated_scene, trajectory_generation_preview and _result), and
SimulationModelsBody is also the setup an attended simulation job runs.
"""

from __future__ import annotations

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


class QueryStackOptionsMessage(TypedDict):
    type: Literal["query_stack_options"]


class StackOptionsMessage(TypedDict):
    """Every (simulatorType, asvSystem, controlLayer) the resolver knows, with whether the workbench can run it and why not."""

    type: Literal["stack_options"]
    simulatorTypes: List[str]
    asvSystem: List[str]
    controlLayers: List[str]
    combinations: List[Dict[str, Any]]


class SimulationConnectionInfo(TypedDict):
    context: str
    # The agent's stack: asvSystem and controlLayer (AsvSystemId and ControlLayerId values). An
    # older client sends only controlMode (autonomous or external), which names the ASV system.
    asvSystem: NotRequired[str]
    controlLayer: NotRequired[str]
    controlMode: NotRequired[str]
    agentName: str
    topic: str
    # Older setups carry a ground control station port per vessel; it is read by nothing any more (Docker assigns the port a job publishes).
    port: NotRequired[Optional[int]]
    gazeboVesselModel: Optional[str]


class WaveInfo(TypedDict):
    amplitude: float
    period: float
    steepness: float
    direction: List[float]


class SimulationModelsBody(TypedDict):
    """The workbench's setup: the body of generate_simulation_models and simulation_models, and the setup of an attended simulation job."""

    simulatorType: str
    # [east, north, up] in m/s; exactly 3 components (validated in simulation_config_from_body).
    windVector: List[float]
    wave: WaveInfo
    # Integer physics speed-up factor (1 = real-time); sub-real-time is not supported.
    simulationSpeed: int
    connectionsByAgentId: Dict[str, SimulationConnectionInfo]


class GenerateSimulationModelsMessage(SimulationModelsBody):
    type: Literal["generate_simulation_models"]


# Scene generation, trajectory generation, simulation and monitoring are not here: the workbench
# submits them as jobs to the cluster's operator API, and they run on worker nodes.
ClientMessage = Union[
    LoadScenarioFileMessage,
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


class ErrorMessage(TypedDict):
    type: Literal["error"]
    message: str


class SimulationModelsMessage(SimulationModelsBody):
    type: Literal["simulation_models"]


ServerMessage = Union[
    InitialStateMessage,
    PreviewTrajectoryChunkMessage,
    ErrorMessage,
    Dict[str, Any],
    StackOptionsMessage,
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


def _parse_agent_context(connection: SimulationConnectionInfo) -> AgentContext:
    try:
        return AgentContext(connection["context"])
    except ValueError:
        raise ValueError(f"Unknown agent context '{connection['context']}'; expected one of {', '.join(context.value for context in AgentContext)}.") from None


def simulation_config_from_body(body: SimulationModelsBody) -> SimulationInstanceConfig:
    """Convert a simulation-models body (generate_simulation_models, simulation_models, the setup of an
    attended simulation job) into a typed simulation instance.
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
                connection=AgentConnection(agent_name=connection["agentName"], topic=connection["topic"]),
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
