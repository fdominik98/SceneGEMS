import { describe, expect, it, vi } from "vitest";
import type { OverlayVisibility } from "../../../app/uiStore";
import type { SimulationFrame } from "../../../domain/simulation/types";
import { sampleFrames } from "../../../test/fixtures/sampleFrames";
import {
  anchorOf,
  drawnStreams,
  fitBox,
  fitPoints,
  ownShipOf,
  primaryStream,
  samePositions,
  vesselClickHandler,
  type EncounterCanvasStream,
} from "./canvasStreams";

const LAYERS: OverlayVisibility = {
  dot: true,
  velocity: true,
  safetyRadius: false,
  trajectory: true,
  safetyDomain: true,
  staticAvoidanceDomain: false,
  maneuveringDomain: true,
};

const frame = sampleFrames[0]!;

function stream(key: string, shown: SimulationFrame | null, secondary = false): EncounterCanvasStream {
  return { key, label: key, frame: shown, frames: shown ? [shown] : [], colorByActorId: {}, layers: LAYERS, secondary };
}

function withoutOwnShip(source: SimulationFrame): SimulationFrame {
  return { ...source, actors: source.actors.map((actor) => ({ ...actor, isOwnShip: false })) };
}

describe("drawnStreams and primaryStream", () => {
  it("drops the streams without a frame", () => {
    expect(drawnStreams([stream("preview", null), stream("simulation", frame)]).map((s) => s.key)).toEqual(["simulation"]);
  });

  it("follows the first stream not drawn as a twin", () => {
    const drawn = drawnStreams([stream("simulation", frame, true), stream("preview", frame)]);
    expect(primaryStream(drawn)?.key).toBe("preview");
  });

  it("falls back to the first stream when every one is a twin, and to null without streams", () => {
    expect(primaryStream(drawnStreams([stream("a", frame, true), stream("b", frame, true)]))?.key).toBe("a");
    expect(primaryStream([])).toBeNull();
  });
});

describe("ownShipOf and anchorOf", () => {
  it("anchors on the own ship", () => {
    const own = ownShipOf(frame);
    expect(own?.actor.id).toBe("own_ship");
    expect(anchorOf(frame)).toEqual({ x: frame.statesByActorId.own_ship!.x, y: frame.statesByActorId.own_ship!.y });
  });

  it("anchors on the vessels' centroid without an own ship, and on the origin without a frame", () => {
    const states = Object.values(frame.statesByActorId);
    const anchor = anchorOf(withoutOwnShip(frame));
    expect(ownShipOf(withoutOwnShip(frame))).toBeNull();
    expect(anchor.x).toBeCloseTo(states.reduce((sum, s) => sum + s.x, 0) / states.length);
    expect(anchor.y).toBeCloseTo(states.reduce((sum, s) => sum + s.y, 0) / states.length);
    expect(anchorOf(null)).toEqual({ x: 0, y: 0 });
  });
});

describe("fitPoints and fitBox", () => {
  it("gives every vessel of every drawn stream the room of its safety radius, half length or 20 m", () => {
    const points = fitPoints(drawnStreams([stream("preview", frame), stream("simulation", frame, true)]));
    expect(points).toHaveLength(4);
    expect(points[0]).toEqual({ x: frame.statesByActorId.own_ship!.x, y: 120, radius: 20 });
  });

  it("holds every point with its room", () => {
    const box = fitBox([
      { x: 0, y: 0, radius: 10 },
      { x: 1000, y: 400, radius: 50 },
    ]);
    expect(box).toEqual({ minX: -10, maxX: 1050, minY: -10, maxY: 450 });
  });

  it("keeps at least the minimum extent each way around the middle", () => {
    expect(fitBox([{ x: 100, y: -40, radius: 20 }], 150)).toEqual({ minX: -50, maxX: 250, minY: -190, maxY: 110 });
  });

  it("is null without points", () => {
    expect(fitBox([])).toBeNull();
  });
});

describe("vesselClickHandler", () => {
  it("selects the pair of the clicked vessel with the own ship, and clears it on a second click", () => {
    const select = vi.fn();
    vesselClickHandler(frame, null, select)!("target_1");
    expect(select).toHaveBeenLastCalledWith("own_ship->target_1");
    vesselClickHandler(frame, "own_ship->target_1", select)!("target_1");
    expect(select).toHaveBeenLastCalledWith(null);
  });

  it("clears the selection when the own ship is clicked", () => {
    const select = vi.fn();
    vesselClickHandler(frame, "own_ship->target_1", select)!("own_ship");
    expect(select).toHaveBeenCalledWith(null);
  });

  it("has no handler without a frame, an own ship or a callback", () => {
    expect(vesselClickHandler(null, null, vi.fn())).toBeUndefined();
    expect(vesselClickHandler(withoutOwnShip(frame), null, vi.fn())).toBeUndefined();
    expect(vesselClickHandler(frame, null, undefined)).toBeUndefined();
  });
});

describe("samePositions", () => {
  const frame = sampleFrames[0]!;

  it("is true for the same vessels at the same places, whatever else changed", () => {
    expect(samePositions(frame, { ...frame, ruleResults: [], metrics: undefined })).toBe(true);
  });

  it("is false once a vessel moved or the vessels differ", () => {
    const moved = { ...frame, statesByActorId: { ...frame.statesByActorId, own_ship: { ...frame.statesByActorId.own_ship!, x: frame.statesByActorId.own_ship!.x + 1 } } };
    expect(samePositions(frame, moved)).toBe(false);
    const { own_ship: _gone, ...others } = frame.statesByActorId;
    void _gone;
    expect(samePositions(frame, { ...frame, statesByActorId: others })).toBe(false);
  });
});
