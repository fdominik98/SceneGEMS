import { describe, expect, it } from "vitest";
import { isLaterRepeat, outputRowSchema } from "../../domain/cluster/historyApi";
import { campaignsReducer } from "../../domain/cluster/liveTopics";
import { campaignRowSchema } from "../../domain/cluster/schemas";
import { sampleCampaignRow, sampleMonitorVerdict, sampleSceneOutput, sampleSimulationOutput, sampleTrajectoryOutput, STATE_LOG_SHA, sampleArtifactRef } from "../../test/fixtures/historyViews";
import { INITIAL_LIST_VIEW } from "./campaignModel";
import {
  commonReason,
  failureGroups,
  groupRepeats,
  groupRunLabel,
  judgedRow,
  leadingVerdicts,
  mergeLiveRows,
  outputProblemFlags,
  pushedOrPage,
  rowTotalsSummary,
  stepsRangeLabel,
} from "./historyModel";

/** What Campaign History leaves out or folds so that what matters is read first. */

const row = (raw: Record<string, unknown>) => campaignRowSchema.parse(raw);
const output = (raw: Record<string, unknown>) => outputRowSchema.parse(raw);

describe("a list row", () => {
  it("names the steps as the stretch of the chain they cover", () => {
    expect(stepsRangeLabel(["simulation"])).toBe("Simulation");
    expect(stepsRangeLabel(["scene_generation", "trajectory_generation"])).toBe("Scene generation to trajectory generation");
    expect(stepsRangeLabel(["design_space_exploration", "scene_generation", "trajectory_generation", "simulation"])).toBe("Design space exploration to simulation");
    expect(stepsRangeLabel([])).toBe("");
  });

  it("shows the verdicts of the last judged step and keeps the earlier steps for the tooltip", () => {
    const totals = { cases: { complete: 5 }, verdicts: { scene: { passed: 5 }, trajectories: { passed: 4, failed: 1 }, simulation: { passed: 1, failed: 4 } } };
    const { verdicts } = rowTotalsSummary(totals, ["scene_generation", "trajectory_generation", "simulation"]);
    const leading = leadingVerdicts(verdicts);
    expect(leading.shown).toEqual({ step: "simulation", passed: 1, failed: 4, unmonitored: 0 });
    expect(leading.others).toEqual(["Scene generation: 5 passed", "Trajectory generation: 4 passed, 1 failed"]);
    expect(leadingVerdicts([])).toEqual({ shown: null, others: [] });
  });

  it("takes the pushed row at the same updated_at: totals change while the campaign's own row does not", () => {
    const page = row(sampleCampaignRow({ totals: { cases: { complete: 6, active: 22 }, verdicts: {} } }));
    const pushed = row(sampleCampaignRow({ totals: { cases: { complete: 12, active: 14 }, verdicts: {} } }));
    expect(pushed.updated_at).toBe(page.updated_at);
    expect(pushedOrPage(page, pushed).totals?.cases.complete).toBe(12);
    const live = campaignsReducer.update(campaignsReducer.snapshot({}), { campaign: pushed }, 1);
    expect(mergeLiveRows([page], live, INITIAL_LIST_VIEW)[0].totals?.cases).toEqual({ complete: 12, active: 14 });
    // A page read after the push is newer and stays
    const later = row(sampleCampaignRow({ updated_at: "2030-01-01T00:00:00+00:00", totals: { cases: { complete: 20 }, verdicts: {} } }));
    expect(pushedOrPage(later, pushed).totals?.cases.complete).toBe(20);
  });
});

describe("the outputs of a step", () => {
  it("flags only what is off: a valid and complete output has no flag", () => {
    expect(outputProblemFlags(output(sampleSimulationOutput()))).toEqual([]);
    expect(outputProblemFlags(output(sampleSceneOutput({ valid: true, complete: null })))).toEqual([]);
    expect(outputProblemFlags(output(sampleTrajectoryOutput())).map((flag) => flag.label)).toEqual(["incomplete"]);
    expect(outputProblemFlags(output(sampleSceneOutput({ valid: false }))).map((flag) => flag.label)).toEqual(["not valid"]);
  });

  it("folds the repeats of a run into one line when they are the same run again", () => {
    const verdict = sampleMonitorVerdict();
    const repeat = (index: number, overrides: Record<string, unknown> = {}) => output(sampleSimulationOutput({ repeat_index: index, run_record_id: 30 + index, verdict, ...overrides }));
    const groups = groupRepeats([repeat(0), repeat(1), repeat(2), repeat(0, { case_id: 8 }), repeat(1, { case_id: 8 })]);
    expect(groups.map((group) => group.rows.map((entry) => entry.run_record_id))).toEqual([
      [30, 31, 32],
      [30, 31],
    ]);
    expect(groupRunLabel(groups[0])).toBe("run 1, 3 identical repeats");
  });

  it("folds repeats of which only the judged one carries the summary, and shows that summary", () => {
    // The control node gives a run's summary to the repeat it judged, the first; the others have none of their own
    const repeat = (index: number, verdict: Record<string, unknown> | null) => output(sampleSimulationOutput({ repeat_index: index, run_record_id: 30 + index, verdict }));
    const [group] = groupRepeats([repeat(0, sampleMonitorVerdict()), repeat(1, null), repeat(2, null)]);
    expect(group.rows).toHaveLength(3);
    expect(judgedRow(group).run_record_id).toBe(30);
    // A page that starts in the middle of a run: the line has no summary, and says where the run was judged
    const [tail] = groupRepeats([repeat(1, null), repeat(2, null)]);
    expect(judgedRow(tail).run_record_id).toBe(31);
    expect(isLaterRepeat(judgedRow(tail))).toBe(true);
    expect(isLaterRepeat(repeat(0, null))).toBe(false);
    expect(isLaterRepeat(output(sampleSceneOutput()))).toBe(false);
  });

  it("keeps a line for a repeat whose state log or state differs, and for outputs that are no repeats", () => {
    const verdict = sampleMonitorVerdict();
    const repeat = (index: number, overrides: Record<string, unknown> = {}) => output(sampleSimulationOutput({ repeat_index: index, run_record_id: 30 + index, verdict, ...overrides }));
    // The state log decides whether a repeat is the same run again
    const otherLog = repeat(1, { artifact: sampleArtifactRef({ sha256: "9".repeat(64), kind: "trajectories" }) });
    expect(groupRepeats([repeat(0), otherLog]).map((group) => group.rows.length)).toEqual([1, 1]);
    expect(groupRepeats([repeat(0), repeat(1, { state: "active" })]).map((group) => group.rows.length)).toEqual([1, 1]);
    // Another run of the same case is another result
    expect(groupRepeats([repeat(0), repeat(0, { run_index: 1 })]).map((group) => group.rows.length)).toEqual([1, 1]);
    const scenes = [output(sampleSceneOutput()), output(sampleSceneOutput())];
    expect(groupRepeats(scenes)).toHaveLength(2);
    expect(groupRunLabel(groupRepeats([repeat(1)])[0])).toBe("run 1, repeat 2");
    expect(groupRunLabel(groupRepeats(scenes)[0])).toBeNull();
    expect(STATE_LOG_SHA).toBe(repeat(0).artifact?.sha256);
  });
});

describe("why cases did not complete", () => {
  const JOB = "69c13761-fcca-4d38-b1ff-9696bbc441f4";
  const OTHER_JOB = "e67af559-5178-4024-ad10-eb559e9f57d5";
  const tick = "WireError: asv_system at os-asv-system:12000: pHelmIvP did not acknowledge the tick at MOOS time 1000000002.0";

  it("reads the reason cases share, without the failed job's key and id", () => {
    expect(commonReason(`simulate:0:0 job ${JOB} failed: ${tick}`)).toBe(tick);
    expect(commonReason(`simulate:0:2 job ${OTHER_JOB} failed: ${tick}`)).toBe(tick);
    expect(commonReason(`generate_trajectories job ${JOB} failed: it finished\n  without a result`)).toBe("it finished without a result");
    expect(commonReason("the scene generation found no valid scene")).toBe("the scene generation found no valid scene");
    expect(commonReason(null)).toBe("no reason recorded");
  });

  it("groups dropped and failed cases by stage and reason, the most frequent first", () => {
    const entry = (case_id: number, state: "dropped" | "failed" | "complete" | "active", stage: "simulate" | "generate_scene" | "generate_trajectories" | "verdict", reason: string | null) => ({ case_id, state, stage, reason });
    const groups = failureGroups([
      entry(1, "dropped", "generate_scene", "the scene generation found no valid scene"),
      entry(2, "failed", "simulate", `simulate:0:0 job ${JOB} failed: ${tick}`),
      entry(3, "failed", "simulate", `simulate:0:2 job ${OTHER_JOB} failed: ${tick}`),
      entry(4, "complete", "verdict", null),
      entry(5, "active", "simulate", null),
      entry(6, "failed", "generate_trajectories", `generate_trajectories job ${JOB} failed: it finished without a result`),
    ]);
    expect(groups).toEqual([
      { state: "failed", stage: "simulate", reason: tick, count: 2, caseId: 2 },
      { state: "failed", stage: "generate_trajectories", reason: "it finished without a result", count: 1, caseId: 6 },
      { state: "dropped", stage: "generate_scene", reason: "the scene generation found no valid scene", count: 1, caseId: 1 },
    ]);
    expect(failureGroups([])).toEqual([]);
  });
});
