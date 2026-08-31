import type { GeneratedSceneData, SimulationFrame } from "./types";

/** Per-agent connection info for `initialize_simulation` (matches server TypedDict). */
export type SimulationConnectionInfo =
  | {
      context: "simulation";
      controlMode: "autonomous" | "external";
      agentName: string;
      topic: string;
      port: number;
      /**
       * Optional Gazebo SDF model file content for this vessel. When omitted, the
       * server generates a model automatically.
       */
      gazeboVesselModel?: string;
    }
  | {
      context: "real";
      controlMode: "autonomous" | "external";
      agentName: string;
      topic: string;
      /**
       * Optional Gazebo SDF model file content for this vessel. When omitted, the
       * server generates a model automatically.
       */
      gazeboVesselModel?: string;
    };

export interface WaveInfoWire {
  amplitude: number;
  period: number;
  steepness: number;
  /** Propagation vector [east, north] in m/s (magnitude = speed). */
  direction: [number, number];
}

/**
 * Shared payload fields for `initialize_simulation`, `generate_simulation_models`
 * and the `simulation_models` server response (all carry identical fields).
 *
 * The Gazebo world is always generated/abstracted server-side, so it is not part
 * of this payload.
 */
export interface SimulationModelsPayload {
  simulatorType: string;
  /** Physics time multiplier sent to the simulator (1 = real-time). */
  simulationSpeed: number;
  windVector: number[];
  /** Sea-state wave parameters (single component). */
  wave: WaveInfoWire;
  /** Same as `wave`, wrapped for backends that expect a list. */
  waves: [WaveInfoWire];
  connectionsByAgentId: Record<string, SimulationConnectionInfo>;
}

/** Advanced RRT tuning values sent with `generate_trajectories`. All optional. */
export interface TrajectoryGenerationParamsWire {
  timeStep?: number;
  timeout?: number;
  maxIterations?: number;
  goalSampleRate?: number;
  bestLeafSampleRate?: number;
  maxLeafs?: number;
  directionThreshold?: number;
  bestRandomNodesK?: number;
  previewInterval?: number;
}

export type ClientToServerMessage =
  | {
      type: "load_scenario_file";
      /** Session key for this scenario load; backend must echo on trajectory chunks. */
      scenarioId: string;
      fileName: string;
      filePath: string;
      fileContent: string;
    }
  | { type: "start_simulation" }
  | ({ type: "initialize_simulation" } & SimulationModelsPayload)
  | ({ type: "generate_simulation_models" } & SimulationModelsPayload)
  | { type: "reset_simulation" }
  | {
      type: "initialize_monitor";
      scope: "internal" | "external";
      name: string;
      topic: string;
      colregsConstraintsContent: string;
    }
  | { type: "shut_down_monitor" }
  | {
      type: "generate_scene";
      requestId: string;
      functionalScenarioContent: string;
      colregsConstraintsContent: string;
      vesselTypesContent: string;
      obstacleTypesContent: string;
      /** Scene generation time limit in seconds. */
      timeout: number;
    }
  | { type: "stop_scene_generation" }
  | {
      type: "generate_trajectories";
      requestId: string;
      /** Initial-scene scenario JSON (evaluation-data shape with `best_scene`). */
      scenarioContent: string;
      colregsConstraintsContent: string;
      /** Advanced RRT parameters; omitted keys fall back to backend defaults. */
      params: TrajectoryGenerationParamsWire;
    }
  | { type: "stop_trajectory_generation" }
  | {
      type: "connect_to_waraps";
      user: string;
      password: string;
      agent_broker: string;
      client_broker: string;
      port: number;
      tls_connection: boolean;
      allow_certificates: boolean;
      geofence: {
        latitude: number;
        longitude: number;
        radius_meters: number;
      };
    }
  | { type: "disconnect_from_waraps" };

export type ServerToClientMessage =
  | {
      type: "initial_state";
      /**
       * Reset/start signal; may include trajectory horizon for playback UI.
       * When set, `scenarioId` is the authoritative scenario id for this session (may replace client-proposed id).
       */
      scenarioId?: string;
      timeStep?: number;
      totalTrajectoryLength?: number;
    }
  | {
      type: "preview_trajectory_chunk";
      scenarioId: string;
      /** Inclusive range of timestamps covered by `frames` (for UI/debug). */
      fromTimestamp: number;
      toTimestamp: number;
      frames: SimulationFrame[];
    }
  | {
      type: "simulation_trajectory_chunk";
      scenarioId: string;
      fromTimestamp: number;
      toTimestamp: number;
      frames: SimulationFrame[];
    }
  /** Optional live push stream (same shape as before). */
  | ({ type: "frame" } & SimulationFrame)
  | { type: "error"; message: string }
  | { type: "ack"; action: string }
  | ({
      type: "generated_scene";
      requestId?: string | null;
      valid: boolean;
    } & GeneratedSceneData)
  | {
      type: "trajectory_generation_preview";
      requestId: string;
      /** Serialized `TrajectoryData` with a full `trajectories.scene_list`. */
      trajectoryData: Record<string, unknown>;
    }
  | {
      type: "trajectory_generation_result";
      requestId: string;
      trajectoryData: Record<string, unknown> | null;
      valid: boolean;
      errorMessage?: string | null;
    }
  | {
      type: "simulation_status";
      status:
        | "running"
        | "starting"
        | "ready to start"
        | "agents are preparing"
        | "initializing"
        | "not initialized"
        | "offline";
    }
  | { type: "waraps_status"; status: "connected" | "disconnected" }
  | { type: "monitor_status"; status: "connected" | "disconnected" }
  /**
   * Response to `generate_simulation_models`. Same fields as the request, but with
   * per-vessel `gazeboVesselModel` attributes filled in.
   */
  | ({ type: "simulation_models" } & SimulationModelsPayload);
