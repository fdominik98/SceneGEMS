import type { OverlayVisibility } from "../../../app/uiStore";
import type { ActorKinematicState, ActorStaticInfo, SimulationFrame } from "../../../domain/simulation/types";
import { frameRelations } from "../monitor/encounterPairs";
import type { Point } from "./encounterGeometry";

/** One set of frames drawn on the canvas or the map (the workbench overlays a preview and a simulation). */
export interface EncounterCanvasStream {
  key: string;
  /** Legend text when more than one stream is drawn. */
  label: string;
  /** Frame at the play head. */
  frame: SimulationFrame | null;
  /** Every buffered frame, sorted by timestamp, for the tracks. */
  frames: SimulationFrame[];
  colorByActorId: Record<string, string>;
  layers: OverlayVisibility;
  /** Drawn as a twin of the primary stream: outlined hulls, thicker track, no labels or CPA marks. */
  secondary?: boolean;
}

/** A stream that has a frame to draw. */
export type DrawnStream = EncounterCanvasStream & { frame: SimulationFrame };

export function drawnStreams(streams: EncounterCanvasStream[]): DrawnStream[] {
  return streams.filter((stream): stream is DrawnStream => stream.frame !== null);
}

/** The stream whose labels, CPA marks and own ship the view follows: the first one not drawn as a twin. */
export function primaryStream(streams: DrawnStream[]): DrawnStream | null {
  return streams.find((stream) => !stream.secondary) ?? streams[0] ?? null;
}

export function ownShipOf(frame: SimulationFrame | null): { actor: ActorStaticInfo; state: ActorKinematicState } | null {
  const actor = frame?.actors.find((item) => item.isOwnShip);
  const state = actor && frame ? frame.statesByActorId[actor.id] : undefined;
  return actor && state ? { actor, state } : null;
}

/** What the view turns and zooms around: the own ship, else the vessels' centroid, else the origin. */
export function anchorOf(frame: SimulationFrame | null): Point {
  const own = ownShipOf(frame);
  if (own) {
    return { x: own.state.x, y: own.state.y };
  }
  const states = frame ? Object.values(frame.statesByActorId) : [];
  if (states.length === 0) {
    return { x: 0, y: 0 };
  }
  return {
    x: states.reduce((sum, s) => sum + s.x, 0) / states.length,
    y: states.reduce((sum, s) => sum + s.y, 0) / states.length,
  };
}

/** Whether two frames place the same vessels at the same positions (a scene and the same scene with the monitor's verdicts). */
export function samePositions(a: SimulationFrame, b: SimulationFrame): boolean {
  const aIds = Object.keys(a.statesByActorId);
  if (aIds.length !== Object.keys(b.statesByActorId).length) {
    return false;
  }
  return aIds.every((id) => {
    const p = a.statesByActorId[id]!;
    const q = b.statesByActorId[id];
    return q !== undefined && p.x === q.x && p.y === q.y;
  });
}

/** Every vessel of the drawn streams with the room it needs around it, for fitting the view. */
export function fitPoints(streams: DrawnStream[]): { x: number; y: number; radius: number }[] {
  return streams.flatMap((stream) =>
    stream.frame.actors.flatMap((actor) => {
      const state = stream.frame.statesByActorId[actor.id];
      return state ? [{ x: state.x, y: state.y, radius: Math.max(actor.safetyRadius, actor.length / 2, 20) }] : [];
    })
  );
}

/**
 * The box in local meters that holds every point with its room, at least `minHalfExtent`
 * each way from its middle; null without points. The map fits its view to it.
 */
export function fitBox(
  points: { x: number; y: number; radius: number }[],
  minHalfExtent = 150
): { minX: number; minY: number; maxX: number; maxY: number } | null {
  if (points.length === 0) {
    return null;
  }
  const minX = Math.min(...points.map((p) => p.x - p.radius));
  const maxX = Math.max(...points.map((p) => p.x + p.radius));
  const minY = Math.min(...points.map((p) => p.y - p.radius));
  const maxY = Math.max(...points.map((p) => p.y + p.radius));
  const midX = (minX + maxX) / 2;
  const midY = (minY + maxY) / 2;
  const halfX = Math.max((maxX - minX) / 2, minHalfExtent);
  const halfY = Math.max((maxY - minY) / 2, minHalfExtent);
  return { minX: midX - halfX, maxX: midX + halfX, minY: midY - halfY, maxY: midY + halfY };
}

/**
 * What a click on a vessel does: another vessel selects its pair with the own ship (a second
 * click clears it), the own ship clears the selection. Undefined without an own ship or a handler.
 */
export function vesselClickHandler(
  frame: SimulationFrame | null,
  selectedRelationId: string | null,
  onSelectRelation: ((relationId: string | null) => void) | undefined
): ((actorId: string) => void) | undefined {
  const own = ownShipOf(frame);
  if (!onSelectRelation || !frame || !own) {
    return undefined;
  }
  const relations = frameRelations(frame);
  return (actorId: string) => {
    if (actorId === own.actor.id) {
      onSelectRelation(null);
      return;
    }
    const relation = relations.find(
      (r) => (r.actor1Id === own.actor.id && r.actor2Id === actorId) || (r.actor2Id === own.actor.id && r.actor1Id === actorId)
    );
    onSelectRelation(relation && relation.relationId !== selectedRelationId ? relation.relationId : null);
  };
}
