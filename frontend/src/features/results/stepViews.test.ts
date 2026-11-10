import { describe, expect, it } from "vitest";
import { findingsSchema } from "../../domain/cluster/historyApi";
import { caseDetailSchema, campaignRowSchema } from "../../domain/cluster/schemas";
import { sampleCase, sampleRunRecord, sampleVerdict } from "../../test/fixtures/clusterViews";
import {
  sampleCampaignRow,
  sampleFindings,
  samplePreSixCampaignRow,
  sampleSceneVerdict,
  sampleUnmonitoredFindings,
  sampleWorkbenchRow,
} from "../../test/fixtures/historyViews";
import {
  caseStateCounts,
  caseStepRows,
  chooseStep,
  describeFindings,
  describeOrigin,
  describeStepVerdict,
  encounterTypeCounts,
  entryOption,
  executedSteps,
  hasStepViews,
  rankClasses,
  rankFailedRules,
  verdictStepOf,
  type MonitoredStep,
} from "./stepViews";

const campaign = campaignRowSchema.parse(sampleCampaignRow());
const workbench = campaignRowSchema.parse(sampleWorkbenchRow());
const preSix = campaignRowSchema.parse(samplePreSixCampaignRow);

describe("steps of an entry", () => {
  it("lists the executed steps in chain order", () => {
    expect(executedSteps(campaign)).toEqual(["scene_generation", "trajectory_generation"]);
    expect(executedSteps(workbench)).toEqual(["trajectory_generation"]);
    expect(executedSteps({ steps: ["simulation", "scene_generation"] })).toEqual(["scene_generation", "simulation"]);
  });

  it("reads an entry without steps as the full chain", () => {
    expect(executedSteps(preSix)).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
    expect(executedSteps(null)).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
    expect(hasStepViews(preSix)).toBe(false);
    expect(hasStepViews(campaign)).toBe(true);
  });

  it("shows the last executed step unless the chosen one was executed", () => {
    expect(chooseStep(campaign, null)).toBe("trajectory_generation");
    expect(chooseStep(campaign, "scene_generation")).toBe("scene_generation");
    expect(chooseStep(workbench, "simulation")).toBe("trajectory_generation");
    expect(chooseStep(preSix, null)).toBe("simulation");
    expect(chooseStep(null, "scene_generation")).toBe("scene_generation");
  });

  it("names the step the verdicts carry", () => {
    const names = (["scene_generation", "trajectory_generation", "simulation"] as MonitoredStep[]).map(verdictStepOf);
    expect(names).toEqual(["scene", "trajectories", "simulation"]);
  });

  it("describes the origin and the option of the picker", () => {
    expect(describeOrigin("live_session")).toBe("recorded from a live session");
    expect(describeOrigin(null)).toBe("");
    expect(entryOption(campaign)).toMatch(/^head-on sweep \(Campaign, running, 2026-10-26 \d\d:\d\d\)$/);
    expect(entryOption(workbench)).toContain("Workbench run, completed");
    expect(entryOption(preSix)).toMatch(/^head-on sweep \(running, /);
  });
});

describe("findings of a step", () => {
  it("counts cases known states first and leaves out zero counts", () => {
    expect(caseStateCounts({ dropped: 1, complete: 5, active: 0, paused_by_newer_control_node: 2 })).toEqual([
      { label: "complete", count: 5 },
      { label: "dropped", count: 1 },
      { label: "paused_by_newer_control_node", count: 2 },
    ]);
  });

  it("ranks failed rules by count, then name, with the first failure times", () => {
    const ranked = rankFailedRules([
      { rule: "rule_b", count: 2, first_failure_time_s: { min: 12.5, median: 20.1 } },
      { rule: "rule_a", count: 2, first_failure_time_s: { min: null, median: null } },
      { rule: "rule_c", count: 5, first_failure_time_s: { min: 70, median: 80 } },
    ]);
    expect(ranked.map((rule) => rule.rule)).toEqual(["rule_c", "rule_a", "rule_b"]);
    expect(ranked[0]).toMatchObject({ firstMin: "1 min 10 s", firstMedian: "1 min 20 s" });
    expect(ranked[1]).toMatchObject({ firstMin: "-", firstMedian: "-" });
  });

  it("ranks classes by failures, then by name with numbers in order", () => {
    const rows = rankClasses([
      { fec_id: "item/10", cases: 1, passed: 1, failed: 0 },
      { fec_id: "item/2", cases: 1, passed: 1, failed: 0 },
      { fec_id: "item/3", cases: 2, passed: 0, failed: 2 },
    ]);
    expect(rows.map((row) => row.classId)).toEqual(["item/3", "item/2", "item/10"]);
  });

  it("describes a monitored step with verdicts and ranked rules", () => {
    const view = describeFindings(findingsSchema.parse(sampleFindings()));
    expect(view.monitored).toBe(true);
    expect(view.partial).toBe(false);
    expect(view.statement).toBe("A monitor judged the trajectory sets of this step: 3 passed and 2 failed.");
    expect(view.verdicts).toEqual({ passed: 3, failed: 2, unmonitored: 0, judged: 5 });
    expect(view.failedRules).toEqual([{ rule: "rule_15", count: 2, firstMin: "12.5 s", firstMedian: "20.1 s" }]);
    expect(view.cases).toEqual([
      { label: "complete", count: 5 },
      { label: "dropped", count: 1 },
    ]);
    expect(view.totalCases).toBe(6);
    expect(view.outputs).toEqual({ count: 5, valid: 5, complete: 3 });
    expect(view.showComplete).toBe(true);
    expect(view.duration).toEqual({ median: "4.2 s", p90: "9.8 s" });
  });

  it("lists the vessel pairs by encounter type, most first, with the monitor's labels", () => {
    expect(describeFindings(findingsSchema.parse(sampleFindings())).encounters).toEqual([
      { label: "Crossing from Port", count: 4 },
      { label: "Head-On", count: 4 },
      { label: "Other", count: 2 },
    ]);
  });

  it("counts encounter types without zero entries, puts Other after an equal count and names an unknown type in words", () => {
    expect(encounterTypeCounts({ OTHER: 3, HEAD_ON: 3, OVERTAKING_TO_PORT: 0, NEW_KIND_OF_PAIR: 1 })).toEqual([
      { label: "Head-On", count: 3 },
      { label: "Other", count: 3 },
      { label: "New kind of pair", count: 1 },
    ]);
    expect(encounterTypeCounts(undefined)).toEqual([]);
  });

  it("shows no encounter types for an older control node or an unmonitored step", () => {
    const older = sampleFindings();
    delete older.encounter_types;
    expect(describeFindings(findingsSchema.parse(older)).encounters).toEqual([]);
    expect(describeFindings(findingsSchema.parse(sampleFindings({ monitored: false }))).encounters).toEqual([]);
    expect(describeFindings(findingsSchema.parse(sampleUnmonitoredFindings)).encounters).toEqual([]);
  });

  it("describes an unmonitored step as partial findings: statistics without verdicts or rules", () => {
    const view = describeFindings(findingsSchema.parse(sampleUnmonitoredFindings));
    expect(view.monitored).toBe(false);
    expect(view.partial).toBe(true);
    expect(view.statement).toBe("No monitor judged this step. These are partial findings: statistics about the scenes of scene generation, without monitor result summaries.");
    expect(view.verdicts).toBeNull();
    expect(view.failedRules).toEqual([]);
    expect(view.outputs.count).toBe(5);
    expect(view.showComplete).toBe(false);
    expect(view.duration).toBeNull();
  });

  it("never lists failed rules for an unmonitored step even when the control node sent some", () => {
    const view = describeFindings(findingsSchema.parse(sampleFindings({ monitored: false })));
    expect(view.failedRules).toEqual([]);
    expect(view.verdicts).toBeNull();
  });
});

describe("steps of a case", () => {
  const record = { ...sampleRunRecord, source: "job" };
  function caseOf(overrides: Record<string, unknown>) {
    return caseDetailSchema.parse({ ...sampleCase, progress: {}, jobs: [], run_records: [], verdicts: [], ...overrides });
  }

  it("lists every step of the chain with its output and verdict", () => {
    const detail = caseOf({
      run_records: [record],
      verdicts: [sampleSceneVerdict, { ...sampleVerdict, step: "simulation", state: "failed", failed_rules: ["rule_8"] }],
    });
    const rows = caseStepRows(detail, ["scene_generation", "trajectory_generation", "simulation"]);
    expect(rows.map((row) => row.step)).toEqual(["scene_generation", "trajectory_generation", "simulation"]);
    expect(rows.map((row) => row.output)).toEqual(["scene stored", "trajectories stored", "1 run"]);
    expect(rows.map(describeStepVerdict)).toEqual(["failed", "no monitor result summary", "failed"]);
    expect(rows[2].failedRules).toEqual(["rule_8"]);
    expect(rows[1].monitored).toBe(false);
  });

  it("marks the steps the entry did not execute", () => {
    const rows = caseStepRows(caseOf({ trajectories_artifact: null, trajectories_complete: null }), ["scene_generation"]);
    expect(rows.map((row) => row.executed)).toEqual([true, false, false]);
    expect(describeStepVerdict(rows[1])).toBe("step not executed");
    expect(rows[1].output).toBe("no trajectories");
  });

  it("reads the verdicts of a control node before Phase 6 as the simulation's", () => {
    const rows = caseStepRows(caseOf({ verdicts: [sampleVerdict] }), ["scene_generation", "trajectory_generation", "simulation"]);
    expect(rows[0].verdicts).toEqual({ passed: 0, failed: 0, unmonitored: 0 });
    expect(rows[2].verdicts).toEqual({ passed: 0, failed: 1, unmonitored: 0 });
  });

  it("says when a partial trajectory set was stored and how runs came out", () => {
    const rows = caseStepRows(
      caseOf({
        trajectories_complete: false,
        verdicts: [
          { ...sampleVerdict, verdict_id: 1, step: "simulation", run_index: 0, state: "passed", failed_rules: [] },
          { ...sampleVerdict, verdict_id: 2, step: "simulation", run_index: 1, state: "failed" },
          { ...sampleVerdict, verdict_id: 3, step: "simulation", run_index: 2, state: "unmonitored", failed_rules: [] },
        ],
      }),
      ["trajectory_generation", "simulation"]
    );
    expect(rows[1].output).toBe("trajectories stored, incomplete");
    expect(describeStepVerdict(rows[2])).toBe("failed in 1 of 2 runs");
    expect(describeStepVerdict({ ...rows[2], verdicts: { passed: 3, failed: 0, unmonitored: 0 } })).toBe("passed in 3 runs");
    expect(describeStepVerdict({ ...rows[2], verdicts: { passed: 0, failed: 0, unmonitored: 2 } })).toBe("not monitored");
  });
});
