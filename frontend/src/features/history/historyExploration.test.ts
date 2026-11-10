import { describe, expect, it } from "vitest";
import { outputRowSchema } from "../../domain/cluster/historyApi";
import { campaignConfigSchema, campaignRowSchema, classViewSchema } from "../../domain/cluster/schemas";
import { sampleClass } from "../../test/fixtures/clusterViews";
import { sampleCampaignRow } from "../../test/fixtures/historyViews";
import { classProgress, closedWithoutCases, stepMonitored } from "./campaignModel";
import { entrySteps, madeByLabel, outputTarget, rowTotalsSummary, STEP_LABELS, STEP_OUTPUT_NOUNS, stepsLabel } from "./historyModel";

/** Campaign History for an entry that explored the design space. */

const ROW = outputRowSchema.parse({
  case_id: 4,
  case_index: 3,
  fec_id: "explored/00003",
  state: "complete",
  reason: null,
  artifact: { sha256: "f".repeat(64), size_bytes: 40, kind: "functional_scenario", media_type: "text/plain; charset=utf-8", pointer: null },
  valid: true,
  complete: null,
  run_index: null,
  repeat_index: null,
  run_record_id: null,
  verdict: null,
  input_source: null,
  vessel_count: 2,
  obstacle_count: 1,
});

describe("an entry that explored the design space", () => {
  it("names the step, its outputs and the page it came from", () => {
    expect(STEP_LABELS.design_space_exploration).toBe("Design space exploration");
    expect(STEP_OUTPUT_NOUNS.design_space_exploration.many).toBe("FECs");
    expect(madeByLabel("design_space_exploration")).toBe("from the design space exploration page");
    expect(stepsLabel(["design_space_exploration", "scene_generation"])).toBe("Design space exploration, scene generation");
  });

  it("lists the exploration among its steps; an entry without steps ran the chain of then", () => {
    const row = campaignRowSchema.parse(sampleCampaignRow({ steps: ["design_space_exploration", "scene_generation"] }));
    expect(entrySteps(row)).toEqual(["design_space_exploration", "scene_generation"]);
    expect(entrySteps({ steps: undefined })).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
    // The exploration has no verdicts of its own
    expect(rowTotalsSummary({ cases: { complete: 1 }, verdicts: { scene: { passed: 2 } } }, ["design_space_exploration", "scene_generation"]).verdicts).toEqual([
      { step: "scene_generation", passed: 2, failed: 0, unmonitored: 0 },
    ]);
  });

  it("opens an explored FEC on the exploration page, on the exploration's case with the FEC selected", () => {
    expect(outputTarget("c1", "design_space_exploration", ROW)).toEqual({
      page: "designSpaceExploration",
      campaignId: "c1",
      caseId: 4,
      step: "design_space_exploration",
      caseIndex: 0,
      fecId: "explored/00003",
    });
    expect(ROW).toMatchObject({ vessel_count: 2, obstacle_count: 1 });
  });

  it("never monitors the exploration", () => {
    const config = campaignConfigSchema.parse({
      current_version: 1,
      versions: [{ version: 1, config_hash: "h", created_at: "2026-11-10T09:00:00+00:00", config: { steps: ["design_space_exploration"] } }],
    });
    expect(stepMonitored(config, "design_space_exploration")).toBe(false);
  });

  it("reads an explored FEC closed without cases as done, not as unfinished", () => {
    const closed = classViewSchema.parse(sampleClass({ fec_id: "explored/00000", state: "complete", state_reason: "the campaign runs no step after the exploration", quota: 1, complete: 0, dropped: 0, in_flight: 0 }));
    expect(closedWithoutCases(closed)).toBe(true);
    expect(classProgress(closed)).toBe(1);
    const open = classViewSchema.parse(sampleClass({ state: "open", quota: 2, complete: 1, dropped: 0, in_flight: 1 }));
    expect(closedWithoutCases(open)).toBe(false);
    expect(classProgress(open)).toBe(0.5);
  });
});
