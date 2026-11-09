import { describe, expect, it } from "vitest";
import type { SimulationFrame } from "../../../domain/simulation/types";
import { seriesFromFrames } from "./metricSeries";

function frame(timestamp: number, distance?: Record<string, number>): SimulationFrame {
  return {
    timestamp,
    timeStep: 15,
    actors: [],
    statesByActorId: {},
    situationContexts: [],
    colregsStates: [],
    ruleResults: [],
    maneuverStates: [],
    metrics: distance ? { distanceByRelationId: distance } : undefined,
  };
}

describe("seriesFromFrames", () => {
  it("takes the pair's values in frame order", () => {
    const frames = [frame(0, { a: 900 }), frame(15, { a: 800 })];
    expect(seriesFromFrames(frames, "a", "distanceByRelationId")).toEqual([
      { t: 0, y: 900 },
      { t: 15, y: 800 },
    ]);
  });

  it("leaves out frames without the value instead of drawing 0", () => {
    const frames = [frame(0, { a: 900 }), frame(15), frame(30, { b: 5 }), frame(45, { a: Number.NaN }), frame(60, { a: 700 })];
    expect(seriesFromFrames(frames, "a", "distanceByRelationId")).toEqual([
      { t: 0, y: 900 },
      { t: 60, y: 700 },
    ]);
  });
});
