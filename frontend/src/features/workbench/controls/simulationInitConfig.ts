import type {
  AsvSystemWire,
  ControlLayerWire,
  StackOptionsPayload,
  StackOptionWire,
  VesselModelPresetWire,
} from "../../../domain/simulation/wireTypes";
import { createActorNamer } from "../../../domain/simulation/actorNaming";

export type SimulationContext = "simulation" | "real";
export type ControlMode = "autonomous" | "external";
export type GlobalSimulatorType = "Gazebo" | "ArduPilot Sim" | "Kinematic";
export type AsvSystem = AsvSystemWire;
export type ControlLayer = ControlLayerWire;

export const GLOBAL_SIMULATOR_TYPES: readonly GlobalSimulatorType[] = [
  "Gazebo",
  "ArduPilot Sim",
  "Kinematic",
];

/** The ASV system SceneGEMS runs for a simulated vessel. */
export const ASV_SYSTEM: readonly AsvSystem[] = ["replay", "usv_navigation", "moos_ivp", "mission_planner"];
/** The control layers of a simulated vessel; a real vessel's is its own autopilot (real_vessel). */
export const CONTROL_LAYERS: readonly ControlLayer[] = ["ardupilot", "custom", "none"];
/** What may steer a real vessel: through its ArduAgent, or its own software on board. */
export const REAL_VESSEL_ASV_SYSTEM: readonly AsvSystem[] = ["replay", "mission_planner", "on_board"];
/** The simulatorType of a real vessel's stacks in the stack options: it is its own control and simulation layer. */
export const REAL_VESSEL_SIMULATOR = "Real vessel";

export const ASV_SYSTEM_LABELS: Record<AsvSystem, string> = {
  replay: "Replay",
  usv_navigation: "USV Navigation",
  moos_ivp: "MOOS-IvP",
  mission_planner: "Mission Planner",
  on_board: "On board (its own software)",
};
export const CONTROL_LAYER_LABELS: Record<ControlLayer, string> = {
  ardupilot: "ArduPilot",
  custom: "Custom",
  none: "None (kinematic)",
  real_vessel: "Its own autopilot",
};

/** ArduAgent's control mode for an ASV system, used when an instance has a real vessel; none for USV Navigation and MOOS-IvP. */
export function controlModeOf(asvSystem: AsvSystem): ControlMode | undefined {
  if (asvSystem === "replay") {
    return "autonomous";
  }
  return asvSystem === "mission_planner" ? "external" : undefined;
}

export function asvSystemOfControlMode(controlMode: ControlMode): AsvSystem {
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
  asvSystem: AsvSystem;
  controlLayer: ControlLayer;
  agentName: string;
  topic: string;
  /** Gazebo SDF model file content; undefined means the server generates one. */
  gazeboVesselModel?: string;
  /** Id of the preset of the vessel model catalog the server generates the model from; undefined means the automatic model. */
  vesselModelPreset?: string;
}

export type SimulationConnectionWire =
  | {
      context: "simulation";
      asvSystem: AsvSystem;
      controlLayer: ControlLayer;
      controlMode?: ControlMode;
      agentName: string;
      topic: string;
      gazeboVesselModel?: string;
      vesselModelPreset?: string;
    }
  | {
      context: "real";
      asvSystem: AsvSystem;
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

/**
 * Where a vessel's agent publishes by default. A simulated vessel's topic is set by the job that runs it; a real
 * vessel's is where the agent on board publishes, which the operator may change.
 */
export function vesselTopic(context: SimulationContext, agentName: string): string {
  return `waraps/unit/surface/${toTopicSegment(context)}/${agentName}`;
}

/** The draft under the vessel's own name (os, ts1), which the operator does not choose; only a real vessel keeps a topic of its own. */
export function withVesselName(draft: VesselInitConnectionDraft, agentName: string): VesselInitConnectionDraft {
  const topic = draft.context === "real" && draft.topic.trim().length > 0 ? draft.topic : vesselTopic(draft.context, agentName);
  return { ...draft, agentName, topic };
}

export function buildInitialVesselConnectionDrafts(
  vessels: VesselDescriptor[]
): VesselInitConnectionDraft[] {
  const nameOf = createActorNamer();
  return vessels.map((vessel) => {
    // The agent is named as the vessel: os, ts1.
    const agentName = nameOf(vessel.id, { isOwnShip: vessel.isOwnShip, isVessel: true });
    const context: SimulationContext = "simulation";
    const parsedId = Number.parseInt(vessel.id, 10);
    const asvSystem: AsvSystem = Number.isFinite(parsedId) && parsedId === 0 ? "mission_planner" : "replay";
    return {
      vesselId: vessel.id,
      context,
      asvSystem,
      controlLayer: "ardupilot",
      agentName,
      topic: vesselTopic(context, agentName),
    };
  });
}

function draftToWire(draft: VesselInitConnectionDraft): SimulationConnectionWire {
  const controlMode = controlModeOf(draft.asvSystem);
  const mode = controlMode !== undefined ? { controlMode } : {};
  if (draft.context === "real") {
    // A real vessel is its own control and simulation layer and needs no Gazebo model.
    return {
      context: "real",
      asvSystem: draft.asvSystem,
      controlLayer: "real_vessel",
      ...mode,
      agentName: draft.agentName,
      topic: draft.topic,
    };
  }
  const hasModel = typeof draft.gazeboVesselModel === "string" && draft.gazeboVesselModel.length > 0;
  const hasPreset = typeof draft.vesselModelPreset === "string" && draft.vesselModelPreset.length > 0;
  return {
    context: "simulation",
    asvSystem: draft.asvSystem,
    controlLayer: draft.controlLayer,
    ...mode,
    agentName: draft.agentName,
    topic: draft.topic,
    ...(hasModel ? { gazeboVesselModel: draft.gazeboVesselModel } : {}),
    // Left out for the automatic model, as the backend leaves it out of its answers.
    ...(hasPreset ? { vesselModelPreset: draft.vesselModelPreset } : {}),
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

/** Vessel connection fields persisted across refresh (SDF model content excluded; the chosen vessel model preset's id is kept). */
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

/**
 * Settings saved before the stack choices existed carry a controlMode instead of an ASV system, and settings saved
 * while the ASV system was called the ASV software carry it under that name. Settings saved while a vessel had a
 * ground station port carry one, which is dropped: Docker assigns the port a job publishes.
 */
type LegacyPersistedDraft = Partial<PersistedVesselConnectionDraft> & { controlMode?: ControlMode; asvSoftware?: PersistedVesselConnectionDraft["asvSystem"]; port?: number };

function upgradePersistedDraft(saved: LegacyPersistedDraft): Partial<PersistedVesselConnectionDraft> {
  const { controlMode, asvSoftware: formerName, port: formerPort, ...rest } = saved;
  void formerPort;
  if (rest.asvSystem === undefined && formerName !== undefined) {
    return { ...rest, asvSystem: formerName };
  }
  if (rest.asvSystem === undefined && controlMode !== undefined) {
    return { ...rest, asvSystem: asvSystemOfControlMode(controlMode) };
  }
  return rest;
}

/** Restore saved connection settings onto generated drafts; optional in-session SDF models only. A name saved while names could be typed is not restored. */
export function mergePersistedVesselSettings(
  persisted: PersistedVesselConnectionDraft[],
  generated: VesselInitConnectionDraft[],
  sessionModelsByVesselId?: Map<string, string | undefined>
): VesselInitConnectionDraft[] {
  const byId = new Map(persisted.map((draft) => [draft.vesselId, draft]));
  return generated.map((draft) => {
    const saved = byId.get(draft.vesselId);
    const base = saved ? withVesselName({ ...draft, ...upgradePersistedDraft(saved) }, draft.agentName) : draft;
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
  asvSystem: AsvSystem,
  controlLayer: ControlLayer
): StackOptionWire | undefined {
  return options?.combinations.find(
    (item) =>
      item.simulatorType === simulatorType &&
      item.asvSystem === asvSystem &&
      item.controlLayer === controlLayer
  );
}

export function controlLayerChoice(
  options: StackOptionsPayload | null,
  simulatorType: GlobalSimulatorType,
  asvSystem: AsvSystem,
  controlLayer: ControlLayer
): StackChoiceState {
  if (options === null) {
    return { available: true, reason: "" };
  }
  const option = findStackOption(options, simulatorType, asvSystem, controlLayer);
  if (option === undefined) {
    return { available: false, reason: "The backend does not know this combination." };
  }
  return { available: option.available, reason: option.reason };
}

/** An ASV system is available on a simulator when some control layer runs it there. */
export function asvSystemChoice(
  options: StackOptionsPayload | null,
  simulatorType: GlobalSimulatorType,
  asvSystem: AsvSystem
): StackChoiceState {
  const states = CONTROL_LAYERS.map((layer) => controlLayerChoice(options, simulatorType, asvSystem, layer));
  if (states.some((state) => state.available)) {
    return { available: true, reason: "" };
  }
  const reasons = [...new Set(states.map((state) => state.reason).filter((reason) => reason.length > 0))];
  return { available: false, reason: reasons.join("; ") };
}

/** Whether a real vessel can be steered by an ASV system: only the real vessel's own stacks count. */
export function realVesselSoftwareChoice(options: StackOptionsPayload | null, asvSystem: AsvSystem): StackChoiceState {
  if (options === null) {
    return { available: REAL_VESSEL_ASV_SYSTEM.includes(asvSystem), reason: "" };
  }
  const option = findStackOption(options, REAL_VESSEL_SIMULATOR, asvSystem, "real_vessel");
  if (option === undefined) {
    return { available: false, reason: "The server does not offer real vessels." };
  }
  return { available: option.available, reason: option.reason };
}

/**
 * The draft with a stack that runs: a real vessel keeps an ASV system that can steer it (replay
 * when its own cannot), a simulated vessel gets a control layer that runs its ASV system on the
 * simulator, when its own does not and another does.
 */
export function normalizeDraftStack(
  draft: VesselInitConnectionDraft,
  simulatorType: GlobalSimulatorType,
  options: StackOptionsPayload | null
): VesselInitConnectionDraft {
  if (draft.context === "real") {
    return realVesselSoftwareChoice(options, draft.asvSystem).available ? draft : { ...draft, asvSystem: "replay" };
  }
  if (draft.asvSystem === "on_board") {
    // Simulated vessels bring no software of their own.
    return normalizeDraftStack({ ...draft, asvSystem: "replay" }, simulatorType, options);
  }
  if (controlLayerChoice(options, simulatorType, draft.asvSystem, draft.controlLayer).available) {
    return draft;
  }
  const working = CONTROL_LAYERS.find(
    (layer) => controlLayerChoice(options, simulatorType, draft.asvSystem, layer).available
  );
  return working === undefined ? draft : { ...draft, controlLayer: working };
}

/** The presets of the vessel model catalog each vessel of the loaded scenario can take, as the gateway listed them. */
export type VesselModelPresetsByAgentId = Record<string, VesselModelPresetWire[]>;

/** Whether the server generates a Gazebo model for the vessel: a simulated vessel in a Gazebo world. A real vessel is its own physics. */
export function hasGeneratedGazeboModel(draft: VesselInitConnectionDraft, simulatorType: GlobalSimulatorType): boolean {
  return draft.context === "simulation" && simulatorType === "Gazebo";
}

/** The presets a vessel can take; none while the gateway has not listed them for the loaded scenario. */
export function vesselModelPresetsOf(presetsByAgentId: VesselModelPresetsByAgentId | null, vesselId: string): VesselModelPresetWire[] {
  return presetsByAgentId?.[vesselId] ?? [];
}

function canTakeVesselModelPreset(presetsByAgentId: VesselModelPresetsByAgentId | null, draft: VesselInitConnectionDraft): boolean {
  return vesselModelPresetsOf(presetsByAgentId, draft.vesselId).some((preset) => preset.id === draft.vesselModelPreset);
}

function withoutVesselModelPreset(draft: VesselInitConnectionDraft): VesselInitConnectionDraft {
  const rest = { ...draft };
  delete rest.vesselModelPreset;
  return rest;
}

/**
 * The draft with a vessel model that can be generated, as shown and sent: its preset stays where a
 * Gazebo model is generated for the vessel and the gateway lists the preset for it, and is the
 * automatic model otherwise (also while the presets of the loaded scenario are not known). The
 * stored draft keeps the choice for the other simulators, as it keeps its stack.
 */
export function normalizeDraftVesselModel(
  draft: VesselInitConnectionDraft,
  simulatorType: GlobalSimulatorType,
  presetsByAgentId: VesselModelPresetsByAgentId | null
): VesselInitConnectionDraft {
  if (draft.vesselModelPreset === undefined) {
    return draft;
  }
  return hasGeneratedGazeboModel(draft, simulatorType) && canTakeVesselModelPreset(presetsByAgentId, draft) ? draft : withoutVesselModelPreset(draft);
}

/**
 * The drafts once the gateway listed the presets of the loaded scenario: a preset its vessel cannot take
 * (one saved for another scenario's vessel, or one the catalog lost) falls back to the automatic model.
 * The same array when every draft keeps its choice.
 */
export function dropUnavailableVesselModelPresets(drafts: VesselInitConnectionDraft[], presetsByAgentId: VesselModelPresetsByAgentId): VesselInitConnectionDraft[] {
  const unavailable = (draft: VesselInitConnectionDraft) => draft.vesselModelPreset !== undefined && !canTakeVesselModelPreset(presetsByAgentId, draft);
  return drafts.some(unavailable) ? drafts.map((draft) => (unavailable(draft) ? withoutVesselModelPreset(draft) : draft)) : drafts;
}

/**
 * The draft with the chosen vessel model: a preset's id, or undefined for the automatic model. The
 * vessel's loaded or generated SDF goes, since the server would use that text instead of the choice.
 */
export function chooseVesselModelPreset(draft: VesselInitConnectionDraft, presetId: string | undefined): VesselInitConnectionDraft {
  const rest = withoutVesselModelPreset(draft);
  delete rest.gazeboVesselModel;
  return presetId !== undefined && presetId.length > 0 ? { ...rest, vesselModelPreset: presetId } : rest;
}

/** A preset's source and notes as one short hint: "Source: ... . ...". */
export function describeVesselModelPreset(preset: Pick<VesselModelPresetWire, "source" | "notes">): string {
  const sentence = (text: string) => (/[.!?]$/.test(text) ? text : `${text}.`);
  const source = preset.source.trim();
  const notes = preset.notes.trim();
  return [source.length > 0 ? sentence(`Source: ${source}`) : "", notes.length > 0 ? sentence(notes) : ""].filter((part) => part.length > 0).join(" ");
}

/** "vessel 1: TCP localhost:49153" per Mission Planner vessel, ordered by vessel id: where Mission Planner connects. The host is the machine that runs the vessels: the worker node of an attended job. */
/** What a vessel's agent has to report before an attended run with a real vessel may start (`STATUS_VESSELS`), as the operator reads it. */
const VESSEL_STATE_LABELS: Record<string, string> = {
  connected: "its agent on the broker",
  position: "a position",
  armable: "to be armable",
  at_start: "to be at its start point",
};

/** "vessel 1 waits for a position, to be at its start point" per vessel that is not ready, ordered by vessel id; nothing for a vessel that is. */
export function vesselReadinessLabels(statesByAgentId: Record<string, Record<string, boolean>>): string[] {
  return Object.entries(statesByAgentId)
    .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
    .map(([agentId, state]) => ({ agentId, lacking: Object.entries(state).filter(([, met]) => !met).map(([key]) => VESSEL_STATE_LABELS[key] ?? key) }))
    .filter(({ lacking }) => lacking.length > 0)
    .map(({ agentId, lacking }) => `vessel ${agentId} waits for ${lacking.join(", ")}`);
}

export function groundControlEndpointLabels(portsByAgentId: Record<string, number>, host = "localhost"): string[] {
  return Object.entries(portsByAgentId)
    .sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true }))
    .map(([agentId, port]) => `vessel ${agentId}: TCP ${host}:${port}`);
}
