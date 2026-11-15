/** ASV system of a vessel stack (backend `AsvSystemId`). */
/** on_board: the vessel's own software steers it (a real vessel); SceneGEMS runs none. */
export type AsvSystemWire = "replay" | "usv_navigation" | "moos_ivp" | "mission_planner" | "on_board";
/** Control layer of a vessel stack (backend `ControlLayerId`). */
/** real_vessel: a real vessel's own autopilot, which is also its simulation layer ("Real vessel"). */
export type ControlLayerWire = "ardupilot" | "custom" | "none" | "real_vessel";

/**
 * Per-agent connection info of a simulation setup (matches server TypedDict `SimulationConnectionInfo`).
 * `asvSystem` and `controlLayer` choose the vessel's stack; `controlMode` is ArduAgent's mode
 * for the same ASV system (absent for USV Navigation and MOOS-IvP, which ArduAgent cannot drive).
 */
export type SimulationConnectionInfo =
  | {
      context: "simulation";
      asvSystem?: AsvSystemWire;
      controlLayer?: ControlLayerWire;
      controlMode?: "autonomous" | "external";
      agentName: string;
      topic: string;
      /**
       * Optional Gazebo SDF model file content for this vessel. When omitted, the
       * server generates a model automatically.
       */
      gazeboVesselModel?: string;
      /**
       * Id of the preset of the vessel model catalog chosen for this vessel; absent or null
       * means the automatic model. A `gazeboVesselModel` is used instead of either.
       */
      vesselModelPreset?: string | null;
    }
  | {
      context: "real";
      asvSystem?: AsvSystemWire;
      controlLayer?: ControlLayerWire;
      controlMode?: "autonomous" | "external";
      agentName: string;
      topic: string;
      /**
       * Optional Gazebo SDF model file content for this vessel. When omitted, the
       * server generates a model automatically.
       */
      gazeboVesselModel?: string;
      /**
       * Id of the preset of the vessel model catalog chosen for this vessel; absent or null
       * means the automatic model. A `gazeboVesselModel` is used instead of either.
       */
      vesselModelPreset?: string | null;
    };

export interface WaveInfoWire {
  amplitude: number;
  period: number;
  steepness: number;
  /** Propagation vector [east, north] in m/s (magnitude = speed). */
  direction: [number, number];
}

/**
 * A simulation setup: the payload of `generate_simulation_models`, of the `simulation_models`
 * server response, and the setup an attended simulation job runs (all carry identical fields).
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

/** One (simulator, ASV system, control layer) combination of the backend's stack resolver. */
export interface StackOptionWire {
  simulatorType: string;
  asvSystem: AsvSystemWire;
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
  asvSystem: AsvSystemWire[];
  controlLayers: ControlLayerWire[];
  combinations: StackOptionWire[];
}

/** One preset of the vessel model catalog, as the console shows it (backend `VesselModelPresetInfo`). */
export interface VesselModelPresetWire {
  id: string;
  name: string;
  /** Where the preset's numbers come from. */
  source: string;
  /** The steering type a vessel must have to take the preset (rudder, skid, vectored_thrust). */
  steeringType: string;
  /** [low, high] per bounded vessel property (length, breadth, draft, ...). */
  bounds: Record<string, [number, number]>;
  /** The source ship's own numbers. */
  particulars: Record<string, number>;
  /** What the preset does not take from its source. */
  notes: string;
}

/**
 * The presets each vessel of the loaded scenario can take (the `vessel_model_presets` answer to
 * `query_vessel_model_presets`). Every vessel has an entry; an empty list means only the automatic model.
 */
export interface VesselModelPresetsPayload {
  /** The scenario the gateway answered for (the id of its `load_scenario_file`). */
  scenarioId: string;
  presetsByAgentId: Record<string, VesselModelPresetWire[]>;
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
  | { type: "query_stack_options" }
  /** Answered for the scenario loaded with `load_scenario_file`; an `error` without one. */
  | { type: "query_vessel_model_presets" }
  | ({ type: "generate_simulation_models" } & SimulationModelsPayload);
/*
 * Nothing else is a gateway message. Scene generation, trajectory generation, monitoring and
 * simulation run as jobs on the active cluster's worker nodes (features/workbench/cluster/);
 * the control node connects to no broker and runs no simulation or monitor for the console.
 */

/** The gateway messages of the former live session: a control node of an earlier release still sends them, and the console ignores them. */
export const RETIRED_GATEWAY_MESSAGES: readonly string[] = ["mqtt_broker_status", "monitor_status", "simulation_status", "simulation_trajectory_chunk", "run_recording", "frame"];
