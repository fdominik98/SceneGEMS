import { describe, expect, it } from "vitest";
import { sampleFrames } from "../../test/fixtures/sampleFrames";
import { computeScenarioDiff } from "./scenarioDiff";

describe("computeScenarioDiff", () => {
  it("reports position delta between preview and simulation frames", () => {
    const preview = structuredClone(sampleFrames[0]!);
    const simulation = structuredClone(sampleFrames[0]!);
    const ownId = preview.actors.find((a) => a.isOwnShip)!.id;
    simulation.statesByActorId[ownId] = {
      ...simulation.statesByActorId[ownId]!,
      x: simulation.statesByActorId[ownId]!.x + 10,
    };
    const diff = computeScenarioDiff(preview, simulation);
    const row = diff.actorDeltas.find((d) => d.actorId === ownId);
    expect(row?.distanceM).toBeCloseTo(10, 0);
  });
});
