import type {
  AsvSoftwareWire,
  ControlLayerWire,
  StackOptionsPayload,
  StackOptionWire,
} from "../../../domain/simulation/wireTypes";
import { createActorNamer } from "../../../domain/simulation/actorNaming";

export type SimulationContext = "simulation" | "real";
export type ControlMode = "autonomous" | "external";
export type GlobalSimulatorType = "Gazebo" | "ArduPilot Sim" | "Kinematic";
export type AsvSoftware = AsvSoftwareWire;
export type ControlLayer = ControlLayerWire;

export const GLOBAL_SIMULATOR_TYPES: readonly GlobalSimulatorType[] = [
  "Gazebo",
  "ArduPilot Sim",
  "Kinematic",
];

/** The ASV software SceneGEMS runs for a simulated vessel. */
export const ASV_SOFTWARE: readonly AsvSoftware[] = ["replay", "usv_navigation", "mission_planner"];
/** The control layers of a simulated vessel; a real vessel's is its own autopilot (real_vessel). */
export const CONTROL_LAYERS: readonly ControlLayer[] = ["ardupilot", "custom", "none"];
/** What may steer a real vessel: through its ArduAgent, or its own software on board. */
export const REAL_VESSEL_ASV_SOFTWARE: readonly AsvSoftware[] = ["replay", "mission_planner", "on_board"];
/** The simulatorType of a real vessel's stacks in the stack options: it is its own control and simulation layer. */
export const REAL_VESSEL_SIMULATOR = "Real vessel";

export const ASV_SOFTWARE_LABELS: Record<AsvSoftware, string> = {
  replay: "Replay",
  usv_navigation: "USV Navigation",
  mission_planner: "Mission Planner",
  on_board: "On board (its own software)",
};
export const CONTROL_LAYER_LABELS: Record<ControlLayer, string> = {
  ardupilot: "ArduPilot",
  custom: "Custom",
  none: "None (kinematic)",
  real_vessel: "Its own autopilot",
};

/** ArduAgent's control mode for an ASV software, used when an instance has a real vessel; none for USV Navigation. */
export function controlModeOf(asvSoftware: AsvSoftware): ControlMode | undefined {
  if (asvSoftware === "replay") {
    return "autonomous";
  }
  return asvSoftware === "mission_planner" ? "external" : undefined;
}

export function asvSoftwareOfControlMode(controlMode: ControlMode): AsvSoftware {
  return controlMode === "external" ? "mission_planner" : "replay";
}

export const SIMULATION_SPEED_MIN = 1;
export const SIMULATION_SPEED_MAX = 50;
export const DEFAULT_SIMULATION_SPEED = 1;

export interface VesselDescriptor {
  id: string;
  isOwnShip: boolean;
}

export interface VesselInitConnectionDraft {
  vesselId: string;
  context: SimulationContext;
  asvSoftware: AsvSoftware;
  controlLayer: ControlLayer;
  agentName: string;
  topic: string;
  port: number;
  /** Gazebo SDF model file content; undefined means the server generates one. */
  gazeboVesselModel?: string;
}

export type SimulationConnectionWire =
  | {
      context: "simulation";
      asvSoftware: AsvSoftware;
      controlLayer: ControlLayer;
      controlMode?: ControlMode;
      agentName: string;
      topic: string;
      port: number;
      gazeboVesselModel?: string;
    }
  | {
      context: "real";
      asvSoftware: AsvSoftware;
      controlLayer: "real_vessel";
      controlMode?: ControlMode;
      agentName: string;
      topic: string;
      gazeboVesselModel?: string;
    };

export type InitializeSimulationConnectionsByAgentIdMap = Record<string, SimulationConnectionWire>;

export function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

export function toTopicSegment(context: SimulationContext): "simulation" | "real" {
  return context;
}

function toContextSuffix(context: SimulationContext): "sim" | "real" {
  return context === "simulation" ? "sim" : "real";
}

export function buildInitialVesselConnectionDrafts(
  vessels: VesselDescriptor[]
): VesselInitConnectionDraft[] {
  const nameOf = createActorNamer();
  return vessels.map((vessel, index) => {
    // The vessel's name (os, ts1) and where it runs: os_sim, ts1_sim.
    const vesselPrefix = nameOf(vessel.id, { isOwnShip: vessel.isOwnShip, isVessel: true });
    const context: SimulationContext = "simulation";
    const agentName = `${vesselPrefix}_${toContextSuffix(context)}`;
    const parsedId = Number.parseInt(vessel.id, 10);
    const hasNumericId = Number.isFinite(parsedId);
    const portOffset = hasNumericId ? parsedId : index;
    const asvSoftware: AsvSoftware = hasNumericId && parsedId === 0 ? "mission_planner" : "replay";
    return {
      vesselId: vessel.id,
      context,
      asvSoftware,
      controlLayer: "ardupilot",
      agentName,
      topic: `waraps/unit/surface/${toTopicSegment(context)}/${agentName}`,
      port: 14570 + portOffset,
    };
  });
}

function draftToWire(draft: VesselInitConnectionDraft): SimulationConnectionWire {
  const controlMode = controlModeOf(draft.asvSoftware);
  const mode = controlMode !== undefined ? { controlMode } : {};
  if (draft.context === "real") {
    // A real vessel is its own control and simulation layer and needs no Gazebo model.
    return {
      context: "real",
      asvSoftware: draft.asvSoftware,
      controlLayer: "real_vessel",
      ...mode,
      agentName: draft.agentName,
      topic: draft.topic,
    };
  }
  const hasModel = typeof draft.gazeboVesselModel === "string" && draft.gazeboVesselModel.length > 0;
  return {
    context: "simulation",
    asvSoftware: draft.asvSoftware,
    controlLayer: draft.controlLayer,
    ...mode,
    agentName: draft.agentName,
    topic: draft.topic,
    port: draft.port,
    ...(hasModel ? { gazeboVesselModel: draft.gazeboVesselModel } : {}),
  };
}

export function buildInitializeSimulationConnectionsByAgentIdMap(
  drafts: VesselInitConnectionDraft[]
): InitializeSimulationConnectionsByAgentIdMap {
  return drafts.reduce<InitializeSimulationConnectionsByAgentIdMap>((acc, draft) => {
    acc[draft.vesselId] = draftToWire(draft);
    return acc;
  }, {});
}

/** Vessel connection fields persisted across refresh (SDF model content excluded). */
export type PersistedVesselConnectionDraft = Omit<
  VesselInitConnectionDraft,
  "gazeboVesselModel"
>;

export function toPersistedVesselDrafts(
  drafts: VesselInitConnectionDraft[]
): PersistedVesselConnectionDraft[] {
  return drafts.map((draft) => {
    const rest = { ...draft };
    delete rest.gazeboVesselModel;
    return rest;
  });
}

/** Settings saved before the stack choices existed carry a controlMode instead of an ASV software. */
type LegacyPersistedDraft = Partial<PersistedVesselConnectionDraft> & { controlMode?: ControlMode };

function upgradePersistedDraft(saved: LegacyPersistedDraft): Partial<PersistedVesselConnectionDraft> {
  const { controlMode, ...rest } = saved;
  if (rest.asvSoftware === undefined && controlMode !== undefined) {
    return { ...rest, asvSoftware: asvSoftwareOfControlMode(controlMode) };
  }
  return rest;
}

/** Restore saved connection settings onto generated drafts; optional in-session SDF models only. */
export function mergePersistedVesselSettings(
  persisted: PersistedVesselConnectionDraft[],
  generated: VesselInitConnectionDraft[],
  sessionModelsByVesselId?: Map<string, string | undefined>
): VesselInitConnectionDraft[] {
  const byId = new Map(persisted.map((draft) => [draft.vesselId, draft]));
  return generated.map((draft) => {
    const saved = byId.get(draft.vesselId);
    const base = saved ? { ...draft, ...upgradePersistedDraft(saved) } : draft;
    const model = sessionModelsByVesselId?.get(draft.vesselId);
    return model != null ? { ...base, gazeboVesselModel: model } : base;
  });
}

/** Whether a stack can run, and why not; every combination counts as available until the backend has sent its options. */
export interface StackChoiceState {
  available: boolean;
  reason: string;
}

export function findStackOption(
  options: StackOptionsPayload | null,
  simulatorType: GlobalSimulatorType | typeof REAL_VESSEL_SIMULATOR,
  asvSoftware: AsvSoftware,
  controlLayer: ControlLayer
): StackOptionWire | undefined {
  return options?.combinations.find(
    (item) =>
      item.simulatorType === simulatorType &&
      item.asvSoftware === asvSoftware &&
      item.controlLayer === controlLayer
  );
}

export function controlLayerChoice(
  options: StackOptionsPayload | null,
  simulatorType: GlobalSimulatorType,
  asvSoftware: AsvSoftware,
  controlLayer: ControlLayer
): StackChoiceState {
  if (options === null) {
    return { available: true, reason: "" };
  }
  const option = findStackOption(options, simulatorType, asvSoftware, controlLayer);
  if (option === undefined) {
    return { available: false, reason: "The backend does not know this combination." };
  }
  return { available: option.available, reason: option.reason };
}

/** An ASV software is available on a simulator when some control layer runs it there. */
export function asvSoftwareChoice(
  options: StackOptionsPayload | null,
  simulatorType: GlobalSimulatorType,
  asvSoftware: AsvSoftware
): StackChoiceState {
  const states = CONTROL_LAYERS.map((layer) => controlLayerChoice(options, simulatorType, asvSoftware, layer));
  if (states.some((state) => state.available)) {
    return { available: true, reason: "" };
  }
  const reasons = [...new Set(states.map((state) => state.reason).filter((reason) => reason.length > 0))];
  return { available: false, reason: reasons.join("; ") };
}

/** Whether a real vessel can be steered by an ASV software: only the real vessel's own stacks count. */
export function realVesselSoftwareChoice(options: StackOptionsPayload | null, asvSoftware: AsvSoftware): StackChoiceState {
  if (options === null) {
    return { available: REAL_VESSEL_ASV_SOFTWARE.includes(asvSoftware), reason: "" };
  }
  const option = findStackOption(options, REAL_VESSEL_SIMULATOR, asvSoftware, "real_vessel");
  if (option === undefined) {
    return { available: false, reason: "The server does not offer real vessels." };
  }
  return { available: option.available, reason: option.reason };
}

/**
 * The draft with a stack that runs: a real vessel keeps an ASV software that can steer it (replay
 * when its own cannot), a simulated vessel gets a control layer that runs its ASV software on the
 * simulator, when its own does not and another does.
 */
export function normalizeDraftStack(
  draft: VesselInitConnectionDraft,
  simulatorType: GlobalSimulatorType,
  options: StackOptionsPayload | null
): VesselInitConnectionDraft {
  if (draft.context === "real") {
    return realVesselSoftwareChoice(options, draft.asvSoftware).available ? draft : { ...draft, asvSoftware: "replay" };
  }
  if (draft.asvSoftware === "on_board") {
    // Simulated vessels bring no software of their own.
    return normalizeDraftStack({ ...draft, asvSoftware: "replay" }, simulatorType, options);
  }
  if (controlLayerChoice(options, simulatorType, draft.asvSoftware, draft.controlLayer).available) {
    return draft;
  }
  const working = CONTROL_LAYERS.find(
    (layer) => controlLayerChoice(options, simulatorType, draft.asvSoftware, layer).available
  );
  return working === undefined ? draft : { ...draft, controlLayer: working };
}

/** "vessel 1: TCP localhost:49153" per Mission Planner vessel, ordered by vessel id: where Mission Planner connects. */
export function groundControlEndpointLabels(portsByAgentId: Record<string, number>): string[] {
  return Object.entries(portsByAgentId)
    .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
    .map(([agentId, port]) => `vessel ${agentId}: TCP localhost:${port}`);
}
