/** ASV software of a vessel stack (backend `AsvSoftwareId`). */
/** on_board: the vessel's own software steers it (a real vessel); SceneGEMS runs none. */
export type AsvSoftwareWire = "replay" | "usv_navigation" | "mission_planner" | "on_board";
/** Control layer of a vessel stack (backend `ControlLayerId`). */
/** real_vessel: a real vessel's own autopilot, which is also its simulation layer ("Real vessel"). */
export type ControlLayerWire = "ardupilot" | "custom" | "none" | "real_vessel";

/**
 * Per-agent connection info for `initialize_simulation` (matches server TypedDict).
 * `asvSoftware` and `controlLayer` choose the vessel's stack; `controlMode` is ArduAgent's mode
 * for the same ASV software (absent for USV Navigation, which ArduAgent cannot drive).
 */
export type SimulationConnectionInfo =
  | {
      context: "simulation";
      asvSoftware?: AsvSoftwareWire;
      controlLayer?: ControlLayerWire;
      controlMode?: "autonomous" | "external";
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
      asvSoftware?: AsvSoftwareWire;
      controlLayer?: ControlLayerWire;
      controlMode?: "autonomous" | "external";
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
  /**
   * Integer physics speed-up factor (1 = real-time). The backend casts this to
   * `int`; sub-real-time values are not supported.
   */
  simulationSpeed: number;
  /** Wind velocity [east, north, up] in m/s. The backend requires exactly 3 components. */
  windVector: [number, number, number];
  /** Sea-state wave parameters (single component). */
  wave: WaveInfoWire;
  connectionsByAgentId: Record<string, SimulationConnectionInfo>;
}

/** One (simulator, ASV software, control layer) combination of the backend's stack resolver. */
export interface StackOptionWire {
  simulatorType: string;
  asvSoftware: AsvSoftwareWire;
  controlLayer: ControlLayerWire;
  available: boolean;
  /** "available", "planned (phase n)" or "unavailable". */
  status: string;
  /** Why the combination cannot be used; empty when available. */
  reason: string;
  /** An operator drives the vessel (Mission Planner). */
  interactiveOnly: boolean;
  repeatabilityTier: "exact" | "bounded" | "none" | null;
  /** Highest measured speedup; null when unmeasured or, with `speedupUnlimited`, when there is no limit. */
  maxSpeedup: number | null;
  speedupUnlimited: boolean;
  wind: "supported" | "unmeasured" | "unsupported" | null;
  waves: "supported" | "unmeasured" | "unsupported" | null;
}

export interface StackOptionsPayload {
  simulatorTypes: string[];
  asvSoftware: AsvSoftwareWire[];
  controlLayers: ControlLayerWire[];
  combinations: StackOptionWire[];
}

/** The trajectory generators a pipeline chooses from (backend `TrajectoryGeneratorId`). */
export type TrajectoryGeneratorWire = "monitor_driven_rrt" | "straight";

/**
 * Trajectory generation values sent with `generate_trajectories`. All optional.
 * `generator` picks the generator (the monitor-guided planner when absent); the tuning
 * values are the planner's, except `timeStep`, which sets the straight generator's step too.
 */
export interface TrajectoryGenerationParamsWire {
  generator?: TrajectoryGeneratorWire;
  /** Seconds, straight generator only; the backend uses one hour when absent. */
  timespan?: number;
  timeStep?: number;
  timeout?: number;
  maxIterations?: number;
  directionThreshold?: number;
  bestRandomNodesK?: number;
  previewInterval?: number;
  /** When false, previews and the result omit `monitor_frames`. */
  includeMonitorResults?: boolean;
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
  | { type: "query_stack_options" }
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
  /*
   * Scene generation, trajectory generation and monitoring of loaded scenes are not gateway
   * messages: the workbench runs them as jobs on the active cluster (features/workbench/cluster/).
   */
  | {
      /**
       * Connect the interactive simulation to an MQTT broker. With `use_master_broker` the
       * broker is the master's own (named in `mqtt_broker_status.masterBroker`) and the
       * address, user and TLS fields are ignored.
       */
      type: "connect_to_mqtt_broker";
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
      use_master_broker?: boolean;
    }
  | { type: "disconnect_from_mqtt_broker" };

export type RunRecordingStatus = "recording" | "saved" | "failed" | "unavailable";
