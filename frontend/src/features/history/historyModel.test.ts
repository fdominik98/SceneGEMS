import { describe, expect, it } from "vitest";
import { outputRowSchema } from "../../domain/cluster/historyApi";
import { campaignsReducer } from "../../domain/cluster/liveTopics";
import { OperatorApiError } from "../../domain/cluster/operatorApi";
import { campaignRowSchema } from "../../domain/cluster/schemas";
import {
  sampleCampaignRow,
  sampleDroppedOutput,
  sampleRunningWorkbenchRow,
  sampleSceneOutput,
  sampleSimulationOutput,
  sampleTrajectoryOutput,
  sampleWorkbenchRow,
  samplePreSixCampaignRow,
} from "../../test/fixtures/historyViews";
import { INITIAL_LIST_VIEW } from "./campaignModel";
import {
  canDelete,
  canOpenOutput,
  deleteRefusal,
  entryKind,
  entrySteps,
  initialStep,
  inputSourceLabel,
  isOutputRunning,
  liveNeedsRefetch,
  madeByLabel,
  matchesListView,
  mergeLiveRows,
  originLabel,
  outputCaseLabel,
  outputFlags,
  outputTarget,
  rowTotalsSummary,
  runLabel,
  stepsLabel,
} from "./historyModel";

const row = (raw: Record<string, unknown>) => campaignRowSchema.parse(raw);
const output = (raw: Record<string, unknown>) => outputRowSchema.parse(raw);

describe("entries", () => {
  it("reads kind, origin and steps, with the pre Phase 6 defaults", () => {
    const old = row(samplePreSixCampaignRow);
    expect(entryKind(old)).toBe("campaign");
    expect(entrySteps(old)).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
    expect(originLabel(old.origin)).toBe("not recorded");
    const workbench = row(sampleWorkbenchRow());
    expect(entryKind(workbench)).toBe("workbench");
    expect(originLabel(workbench.origin)).toBe("the trajectory generation page");
    expect(madeByLabel(workbench.origin)).toBe("from the trajectory generation page");
    expect(madeByLabel(old.origin)).toBe("origin not recorded");
    expect(entrySteps(row(sampleCampaignRow({ steps: ["trajectory_generation", "scene_generation"] })))).toEqual(["scene_generation", "trajectory_generation"]);
    expect(stepsLabel(["scene_generation", "trajectory_generation"])).toBe("Scene generation, trajectory generation");
  });

  it("summarizes the row totals: cases by state, verdicts per executed step", () => {
    const campaign = row(sampleCampaignRow());
    expect(rowTotalsSummary(campaign.totals, entrySteps(campaign))).toEqual({
      cases: "5 complete, 4 active, 1 dropped",
      verdicts: [
        { step: "scene_generation", passed: 5, failed: 0, unmonitored: 0 },
        { step: "trajectory_generation", passed: 3, failed: 2, unmonitored: 0 },
      ],
    });
    expect(rowTotalsSummary(undefined, ["simulation"])).toEqual({ cases: null, verdicts: [] });
    expect(rowTotalsSummary({ cases: {}, verdicts: {} }, ["simulation"]).cases).toBe("no cases yet");
  });

  it("deletes only final entries and explains a refusal", () => {
    expect(canDelete(row(sampleWorkbenchRow()))).toBe(true);
    expect(canDelete(row(sampleRunningWorkbenchRow()))).toBe(false);
    expect(deleteRefusal(new OperatorApiError("http", "conflict", "/cluster/campaigns/wb1", 409))).toMatch(/Stop it first/);
    expect(deleteRefusal(new OperatorApiError("http", "gone", "/cluster/campaigns/wb1", 404))).toMatch(/not on this master/);
  });
});

describe("the live list", () => {
  const rows = [row(sampleRunningWorkbenchRow()), row(sampleWorkbenchRow()), row(sampleCampaignRow())];

  it("filters by kind, state, step and name", () => {
    expect(rows.filter((entry) => matchesListView(entry, { ...INITIAL_LIST_VIEW, kind: "workbench" })).map((entry) => entry.campaign_id)).toEqual(["wb2", "wb1"]);
    expect(rows.filter((entry) => matchesListView(entry, { ...INITIAL_LIST_VIEW, step: "scene_generation" })).map((entry) => entry.campaign_id)).toEqual(["c1"]);
    expect(rows.filter((entry) => matchesListView(entry, { ...INITIAL_LIST_VIEW, states: ["running"] })).map((entry) => entry.campaign_id)).toContain("wb2");
    expect(rows.filter((entry) => matchesListView(entry, { ...INITIAL_LIST_VIEW, q: " SIMUL" })).map((entry) => entry.campaign_id)).toEqual(["wb2"]);
  });

  it("patches rows with newer pushed ones and drops deleted ones and ones that left the filter", () => {
    let live = campaignsReducer.snapshot({});
    live = campaignsReducer.update(live, { campaign: sampleRunningWorkbenchRow({ actual_state: "completed", updated_at: "2030-01-01T00:00:00+00:00" }) }, 1);
    live = campaignsReducer.update(live, { deleted: "wb1" }, 2);
    expect(mergeLiveRows(rows, live, INITIAL_LIST_VIEW).map((entry) => [entry.campaign_id, entry.actual_state])).toEqual([
      ["wb2", "completed"],
      ["c1", rows[2].actual_state],
    ]);
    expect(mergeLiveRows(rows, live, { ...INITIAL_LIST_VIEW, states: ["running"] }).map((entry) => entry.campaign_id)).not.toContain("wb2");
    const older = campaignsReducer.update(campaignsReducer.snapshot({}), { campaign: sampleRunningWorkbenchRow({ actual_state: "paused", updated_at: "2000-01-01T00:00:00+00:00" }) }, 1);
    expect(mergeLiveRows(rows, older, INITIAL_LIST_VIEW)[0].actual_state).toBe("running");
    expect(mergeLiveRows(rows, null, INITIAL_LIST_VIEW)).toHaveLength(3);
  });

  it("reads the page again for deletions, new matching entries and rows that left the filter", () => {
    const ids = rows.map((entry) => entry.campaign_id);
    expect(liveNeedsRefetch(ids, INITIAL_LIST_VIEW, { deleted: "zz" })).toBe(true);
    expect(liveNeedsRefetch(ids, INITIAL_LIST_VIEW, { campaign: row(sampleWorkbenchRow({ campaign_id: "new" })) })).toBe(true);
    expect(liveNeedsRefetch(ids, { ...INITIAL_LIST_VIEW, kind: "campaign" }, { campaign: row(sampleWorkbenchRow({ campaign_id: "new" })) })).toBe(false);
    expect(liveNeedsRefetch(ids, INITIAL_LIST_VIEW, { campaign: row(sampleWorkbenchRow()) })).toBe(false);
    expect(liveNeedsRefetch(ids, { ...INITIAL_LIST_VIEW, states: ["running"] }, { campaign: row(sampleRunningWorkbenchRow({ actual_state: "completed" })) })).toBe(true);
  });
});

describe("outputs of a step", () => {
  it("targets the workbench page of the step, with the run record of a simulated run", () => {
    expect(outputTarget("c1", "scene_generation", output(sampleSceneOutput()))).toEqual({ page: "sceneGeneration", campaignId: "c1", caseId: 5, step: "scene_generation" });
    expect(outputTarget("wb2", "simulation", output(sampleSimulationOutput()))).toEqual({ page: "simulation", campaignId: "wb2", caseId: 7, step: "simulation", runRecordId: 11 });
    expect(outputTarget("c1", "trajectory_generation", output(sampleTrajectoryOutput()), true)).toMatchObject({ page: "trajectoryGeneration", live: true });
  });

  it("opens existing outputs and watches cases still working on the step", () => {
    expect(canOpenOutput(output(sampleSceneOutput()))).toBe(true);
    const working = output(sampleSceneOutput({ state: "active", artifact: null, valid: null, verdict: null }));
    expect(canOpenOutput(working)).toBe(false);
    expect(isOutputRunning(working)).toBe(true);
    expect(isOutputRunning(output(sampleDroppedOutput()))).toBe(false);
  });

  it("flags validity and partial paths, and counts runs from 1", () => {
    expect(outputFlags(output(sampleTrajectoryOutput())).map((flag) => flag.label)).toEqual(["valid", "partial"]);
    expect(outputFlags(output(sampleSimulationOutput())).map((flag) => flag.label)).toEqual(["complete"]);
    expect(runLabel(output(sampleSimulationOutput()))).toBe("run 1, repeat 1");
    expect(runLabel(output(sampleSceneOutput()))).toBeNull();
  });

  it("names the case of an output by its class", () => {
    expect(outputCaseLabel({ fec_id: "item/0", case_index: 0 })).toEqual({ title: "input item 0", detail: null });
    expect(outputCaseLabel({ fec_id: "scenario/my_head_on", case_index: 2 })).toEqual({ title: "case 2 of my_head_on", detail: "scenario given as content" });
    expect(outputCaseLabel({ fec_id: "colregs/head_on", case_index: 1 })).toEqual({ title: "case 1 of head_on", detail: "colregs" });
    expect(outputCaseLabel({ fec_id: "colregs/two/crossing", case_index: 1 })).toEqual({ title: "case 1 of crossing", detail: "colregs/two" });
    expect(outputCaseLabel({ fec_id: "class-a", case_index: 3 })).toEqual({ title: "case 3 of class-a", detail: null });
  });

  it("names where the input came from", () => {
    expect(inputSourceLabel({ campaign_id: "c1", case_id: 5, step: "scene_generation" })).toEqual({ kind: "entry", campaignId: "c1", text: "case 5 (scene generation)" });
    expect(inputSourceLabel({ file: "head_on.json" })).toEqual({ kind: "text", text: "file head_on.json" });
    expect(inputSourceLabel({})).toEqual({ kind: "text", text: "a deleted entry" });
    expect(inputSourceLabel(null)).toBeNull();
  });

  it("opens the remembered step tab when the entry runs it, else the last step", () => {
    expect(initialStep(["scene_generation", "trajectory_generation"], null)).toBe("trajectory_generation");
    expect(initialStep(["scene_generation", "trajectory_generation"], "scene_generation")).toBe("scene_generation");
    expect(initialStep(["simulation"], "scene_generation")).toBe("simulation");
  });
});
