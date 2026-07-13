export type SimulationContext = "simulation" | "real";
export type ControlMode = "autonomous" | "external";
export type GlobalSimulatorType = "Gazebo" | "ArduPilot Sim";

export const GLOBAL_SIMULATOR_TYPES: readonly GlobalSimulatorType[] = [
  "Gazebo",
  "ArduPilot Sim",
];

export const SIMULATION_SPEED_MIN = 1;
export const SIMULATION_SPEED_MAX = 50;
export const DEFAULT_SIMULATION_SPEED = 1;

export interface VesselDescriptor {
  id: string;
  isOwnShip: boolean;
}

interface RawActorCandidate {
  id?: unknown;
  name?: unknown;
  isVessel?: unknown;
  isOwnShip?: unknown;
  type?: unknown;
  kind?: unknown;
  category?: unknown;
}

export interface VesselInitConnectionDraft {
  vesselId: string;
  context: SimulationContext;
  controlMode: ControlMode;
  agentName: string;
  topic: string;
  port: number;
  /** Gazebo SDF model file content; undefined means the server generates one. */
  gazeboVesselModel?: string;
}

export type SimulationConnectionWire =
  | {
      context: "simulation";
      controlMode: ControlMode;
      agentName: string;
      topic: string;
      port: number;
      gazeboVesselModel?: string;
    }
  | {
      context: "real";
      controlMode: ControlMode;
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

function toContextSuffix(context: SimulationContext): "SIM" | "REAL" {
  return context === "simulation" ? "SIM" : "REAL";
}

export function buildInitialVesselConnectionDrafts(
  vessels: VesselDescriptor[]
): VesselInitConnectionDraft[] {
  let targetShipCounter = 1;
  return vessels.map((vessel, index) => {
    const vesselPrefix = vessel.isOwnShip ? "OS_0" : `TS_${targetShipCounter++}`;
    const context: SimulationContext = "simulation";
    const agentName = `${vesselPrefix}_${toContextSuffix(context)}`;
    const parsedId = Number.parseInt(vessel.id, 10);
    const hasNumericId = Number.isFinite(parsedId);
    const portOffset = hasNumericId ? parsedId : index;
    const controlMode: ControlMode =
      hasNumericId && parsedId === 0 ? "external" : "autonomous";
    return {
      vesselId: vessel.id,
      context,
      controlMode,
      agentName,
      topic: `waraps/unit/surface/${toTopicSegment(context)}/${agentName}`,
      port: 14570 + portOffset,
    };
  });
}

function looksLikeVessel(actor: RawActorCandidate): boolean {
  if (typeof actor.isVessel === "boolean") {
    return actor.isVessel;
  }
  const probe = [actor.type, actor.kind, actor.category, actor.name]
    .filter((value): value is string => typeof value === "string")
    .join(" ")
    .toLowerCase();
  return probe.includes("vessel") || probe.includes("ship") || probe.includes("usv") || probe.includes("asv");
}

function inferOwnShip(actor: RawActorCandidate, fallbackId: string): boolean {
  if (typeof actor.isOwnShip === "boolean") {
    return actor.isOwnShip;
  }
  const idProbe = String(actor.id ?? fallbackId).toLowerCase();
  return idProbe.startsWith("os") || idProbe.includes("own");
}

export function extractVesselDescriptorsFromSceneRaw(raw: unknown): VesselDescriptor[] {
  if (typeof raw !== "object" || raw === null) {
    return [];
  }
  const actors = (raw as { actors?: unknown }).actors;
  if (!Array.isArray(actors)) {
    return [];
  }
  return actors
    .map((actor, index) => {
      const candidate = (typeof actor === "object" && actor !== null
        ? actor
        : {}) as RawActorCandidate;
      const fallbackId = `vessel_${index}`;
      const actorId = typeof candidate.id === "string" && candidate.id.length > 0 ? candidate.id : fallbackId;
      return {
        actorId,
        isVessel: looksLikeVessel(candidate),
        isOwnShip: inferOwnShip(candidate, fallbackId),
      };
    })
    .filter((item) => item.isVessel)
    .map((item) => ({ id: item.actorId, isOwnShip: item.isOwnShip }));
}

function draftToWire(draft: VesselInitConnectionDraft): SimulationConnectionWire {
  if (draft.context === "real") {
    // Real vessels do not use a Gazebo model.
    return {
      context: "real",
      controlMode: draft.controlMode,
      agentName: draft.agentName,
      topic: draft.topic,
    };
  }
  const hasModel = typeof draft.gazeboVesselModel === "string" && draft.gazeboVesselModel.length > 0;
  return {
    context: "simulation",
    controlMode: draft.controlMode,
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

/** Restore saved connection settings onto generated drafts; optional in-session SDF models only. */
export function mergePersistedVesselSettings(
  persisted: PersistedVesselConnectionDraft[],
  generated: VesselInitConnectionDraft[],
  sessionModelsByVesselId?: Map<string, string | undefined>
): VesselInitConnectionDraft[] {
  const byId = new Map(persisted.map((draft) => [draft.vesselId, draft]));
  return generated.map((draft) => {
    const saved = byId.get(draft.vesselId);
    const base = saved ? { ...draft, ...saved } : draft;
    const model = sessionModelsByVesselId?.get(draft.vesselId);
    return model != null ? { ...base, gazeboVesselModel: model } : base;
  });
}
