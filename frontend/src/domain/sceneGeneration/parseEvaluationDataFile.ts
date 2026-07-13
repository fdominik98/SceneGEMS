import { parseFrame } from "../simulation/protocol";
import type { ActorStaticInfo, EvaluationData, SimulationFrame } from "../simulation/types";

export interface ParsedScenarioFile {
  evaluationData: EvaluationData;
  scene: SimulationFrame;
  /** True when the source JSON includes `trajectories.scene_list` (full trajectory export). */
  hasFullTrajectories: boolean;
}

const SCENE_CONTAINER_KEYS = [
  "scene",
  "initial_scene",
  "initialScene",
  "frame",
  "snapshot",
  "best_scene",
  "bestScene",
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function looksLikeFramePayload(value: unknown): boolean {
  if (!isRecord(value)) return false;
  return Array.isArray(value.actors) && isRecord(value.statesByActorId);
}

function scenarioMetadataWithoutSceneFields(data: Record<string, unknown>): EvaluationData {
  const copy = { ...data };
  for (const key of SCENE_CONTAINER_KEYS) {
    delete copy[key];
  }
  delete copy.trajectories;
  return copy;
}

export function isFullTrajectoryScenario(raw: unknown): boolean {
  if (!isRecord(raw)) {
    return false;
  }
  const trajectories = raw.trajectories;
  if (!isRecord(trajectories)) {
    return false;
  }
  const sceneList = trajectories.scene_list;
  return Array.isArray(sceneList) && sceneList.length > 0;
}

function extractFirstTrajectoryScene(raw: Record<string, unknown>): unknown | null {
  const trajectories = raw.trajectories;
  if (!isRecord(trajectories)) {
    return null;
  }
  const sceneList = trajectories.scene_list;
  if (!Array.isArray(sceneList) || sceneList.length === 0) {
    return null;
  }
  const firstScene = sceneList[0];
  if (!isRecord(firstScene)) {
    return null;
  }
  return bestSceneDataToFramePayload(firstScene);
}

function normalizeBackendActor(
  actorRaw: Record<string, unknown>,
  id: string,
  displayName?: string
): Record<string, unknown> {
  return {
    id,
    name:
      displayName ??
      (typeof actorRaw.name === "string"
        ? actorRaw.name
        : typeof actorRaw.type === "string"
          ? actorRaw.type
          : id),
    isVessel: actorRaw.is_vessel !== false,
    isOwnShip: actorRaw._is_os === true,
    type: String(actorRaw.type ?? "Unknown"),
    length: Number(actorRaw.length ?? 0),
    breadth: Number(actorRaw.breadth ?? 0),
    height: Number(actorRaw.height ?? 0),
    draft: Number(actorRaw.draft ?? 0),
    mass: Number(actorRaw.mass ?? 0),
    safety_radius: Number(actorRaw.safety_radius ?? actorRaw.safetyRadius ?? 0),
    maxSpeed: actorRaw._max_speed ?? actorRaw.maxSpeed,
    maxAngularSpeed: actorRaw._max_angular_speed ?? actorRaw.maxAngularSpeed,
    maxAcceleration: actorRaw._max_acceleration ?? actorRaw.maxAcceleration,
    rudderMass: actorRaw._rudder_mass ?? actorRaw.rudderMass ?? 0,
    rudderLength: actorRaw._rudder_length ?? actorRaw.rudderLength ?? 0,
    rudderWidth: actorRaw._rudder_width ?? actorRaw.rudderWidth ?? 0,
    rudderHeight: actorRaw._rudder_height ?? actorRaw.rudderHeight ?? 0,
    propellerDiameter: actorRaw._propeller_diameter ?? actorRaw.propellerDiameter ?? 0,
    thrusterMass: actorRaw._thruster_mass ?? actorRaw.thrusterMass ?? 0,
    motorLength: actorRaw._motor_length ?? actorRaw.motorLength ?? 0,
  };
}

/** Converts backend `best_scene._data` [[actor, state], ...] tuples into a frame payload. */
function bestSceneDataToFramePayload(bestScene: Record<string, unknown>): unknown | null {
  const data = bestScene._data;
  if (!Array.isArray(data)) {
    return null;
  }

  const actors: Record<string, unknown>[] = [];
  const statesByActorId: Record<string, Record<string, unknown>> = {};
  let targetNumber = 0;

  for (const entry of data) {
    if (!Array.isArray(entry) || entry.length < 2) {
      continue;
    }
    const actorRaw = entry[0];
    const stateRaw = entry[1];
    if (!isRecord(actorRaw) || !isRecord(stateRaw)) {
      continue;
    }
    const id = String(actorRaw.id ?? actors.length);
    const isOwnShip = actorRaw._is_os === true;
    const displayName = isOwnShip ? "OS" : `TS${++targetNumber}`;
    actors.push(normalizeBackendActor(actorRaw, id, displayName));
    statesByActorId[id] = {
      x: Number(stateRaw.x ?? 0),
      y: Number(stateRaw.y ?? 0),
      speed: Number(stateRaw.speed ?? 0),
      heading: Number(stateRaw.heading ?? 0),
    };
  }

  if (actors.length === 0) {
    return null;
  }

  return {
    timestamp: 0,
    timeStep: 1,
    actors,
    statesByActorId,
    situationContexts: [],
    colregsStates: [],
    ruleResults: [],
    maneuverStates: [],
  };
}

function actorIdForBackend(id: string): string | number {
  const trimmed = id.trim();
  if (/^-?\d+$/.test(trimmed)) {
    return Number.parseInt(trimmed, 10);
  }
  return id;
}

/** Serializes a frame into backend `best_scene._data` [[actor, state], ...] tuples. */
function frameToBackendBestScene(scene: SimulationFrame): Record<string, unknown> {
  const _data: unknown[] = [];
  for (const actor of scene.actors) {
    const state = scene.statesByActorId[actor.id];
    if (!state) {
      continue;
    }
    _data.push([actorToBackendWire(actor), stateToBackendWire(state)]);
  }
  return { _data };
}

function actorToBackendWire(actor: ActorStaticInfo): Record<string, unknown> {
  const wire: Record<string, unknown> = {
    id: actorIdForBackend(actor.id),
    type: actor.type,
    length: actor.length,
    breadth: actor.breadth,
    height: actor.height ?? 0,
    draft: actor.draft ?? 0,
    mass: actor.mass ?? 0,
    safety_radius: actor.safetyRadius,
    _is_os: actor.isOwnShip,
    is_vessel: actor.isVessel,
  };
  if (actor.maxSpeed !== undefined) wire._max_speed = actor.maxSpeed;
  if (actor.maxAngularSpeed !== undefined) wire._max_angular_speed = actor.maxAngularSpeed;
  if (actor.maxAcceleration !== undefined) wire._max_acceleration = actor.maxAcceleration;
  if (actor.rudderMass !== undefined) wire._rudder_mass = actor.rudderMass;
  if (actor.rudderLength !== undefined) wire._rudder_length = actor.rudderLength;
  if (actor.rudderWidth !== undefined) wire._rudder_width = actor.rudderWidth;
  if (actor.rudderHeight !== undefined) wire._rudder_height = actor.rudderHeight;
  if (actor.propellerDiameter !== undefined) wire._propeller_diameter = actor.propellerDiameter;
  if (actor.thrusterMass !== undefined) wire._thruster_mass = actor.thrusterMass;
  if (actor.motorLength !== undefined) wire._motor_length = actor.motorLength;
  return wire;
}

function stateToBackendWire(state: SimulationFrame["statesByActorId"][string]): Record<string, unknown> {
  return {
    x: state.x,
    y: state.y,
    speed: state.speed,
    heading: state.heading,
  };
}

/** JSON object shape accepted by the Python scenario loader (`best_scene`, not `scene`). */
export function buildScenarioJsonForServer(
  evaluationData: EvaluationData | undefined,
  scene: SimulationFrame
): Record<string, unknown> {
  const metadata = isRecord(evaluationData)
    ? scenarioMetadataWithoutSceneFields(evaluationData)
    : {};
  return {
    ...metadata,
    best_scene: frameToBackendBestScene(scene),
  };
}

function extractSceneRaw(data: Record<string, unknown>): unknown | null {
  for (const key of ["scene", "initial_scene", "initialScene", "frame", "snapshot"] as const) {
    const candidate = data[key];
    if (candidate !== undefined && candidate !== null) {
      return candidate;
    }
  }

  const bestScene = data.best_scene ?? data.bestScene;
  if (isRecord(bestScene)) {
    const fromBestScene = bestSceneDataToFramePayload(bestScene);
    if (fromBestScene !== null) {
      return fromBestScene;
    }
  }

  const fromTrajectories = extractFirstTrajectoryScene(data);
  if (fromTrajectories !== null) {
    return fromTrajectories;
  }

  if (looksLikeFramePayload(data)) {
    return data;
  }

  return null;
}

export function parseScenarioFile(jsonText: string): ParsedScenarioFile {
  let raw: unknown;
  try {
    raw = JSON.parse(jsonText);
  } catch {
    throw new Error("Invalid JSON. Expected a scenario file.");
  }

  if (!isRecord(raw)) {
    throw new Error("Scenario file must be a JSON object.");
  }

  const sceneRaw = extractSceneRaw(raw);
  if (sceneRaw === null) {
    throw new Error(
      'Scenario file must include vessel data (e.g. a "scene", "best_scene", or "trajectories.scene_list" field).'
    );
  }

  const scene = parseFrame(sceneRaw);
  const evaluationData = sceneRaw === raw ? {} : scenarioMetadataWithoutSceneFields(raw);
  const hasFullTrajectories = isFullTrajectoryScenario(raw);

  return { evaluationData, scene, hasFullTrajectories };
}

export function formatScenarioJsonForExport(
  evaluationData: EvaluationData | undefined,
  scene: SimulationFrame
): string {
  return JSON.stringify(buildScenarioJsonForServer(evaluationData, scene), null, 2);
}

