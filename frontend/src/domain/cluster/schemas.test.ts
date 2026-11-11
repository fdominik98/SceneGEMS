import { describe, expect, it } from "vitest";
import {
  sampleCampaignDetail,
  sampleCampaignSummary,
  sampleCase,
  sampleEvent,
  sampleJob,
  sampleLogLine,
  sampleControlNodeStatus,
  sampleWorkerNode,
  sampleRunRecord,
  sampleVerdict,
} from "../../test/fixtures/clusterViews";
import {
  sampleCampaignRow,
  sampleFindings,
  sampleLiveRunRecord,
  sampleMonitoredCase,
  samplePreSixCampaignRow,
  sampleSceneVerdict,
  sampleUploadedRef,
} from "../../test/fixtures/historyViews";
import {
  artifactRefSchema,
  campaignConfigSchema,
  campaignRowSchema,
  campaignDetailSchema,
  campaignEventSchema,
  campaignSummarySchema,
  caseDetailSchema,
  caseViewSchema,
  jobDetailSchema,
  jobViewSchema,
  controlNodeStatusSchema,
  workerNodeListSchema,
  workerNodeViewSchema,
  runRecordSchema,
  verdictSchema,
} from "./schemas";

describe("operator API schemas", () => {
  it("parses a worker node view with and without the machine", () => {
    const workerNode = workerNodeViewSchema.parse(sampleWorkerNode());
    expect(workerNode.machine).toBe("lab-gpu-1");
    expect(workerNode.slots.simulation).toEqual({ slots: 8, slots_in_use: 8 });
    expect(workerNode, "no capabilities alias of the slots").not.toHaveProperty("capabilities");
    expect(workerNode.components[2]).toEqual({ component: "simulation_layer/kinematic", images: ["scenegems-simulation-subsystem:latest"], state: "usable" });

    const { machine: _machine, ...withoutMachine } = sampleWorkerNode();
    void _machine;
    expect(workerNodeViewSchema.parse(withoutMachine).machine).toBeUndefined();
    expect(workerNodeViewSchema.parse(sampleWorkerNode({ machine: null })).machine).toBeNull();
  });

  it("parses an out-of-date worker node with its mismatching images", () => {
    const workerNode = workerNodeViewSchema.parse(
      sampleWorkerNode({
        out_of_date: true,
        fingerprint_mismatches: [
          { image: "scenegems-worker-node", required: "sha256:aaaa", actual: "sha256:9999" },
          { image: "scenegems-monitoring", required: "sha256:bbbb", actual: null },
        ],
      })
    );
    expect(workerNode.fingerprint_mismatches[1].actual).toBeNull();
  });

  it("refuses a worker node with an unknown status or a missing field", () => {
    expect(workerNodeViewSchema.safeParse(sampleWorkerNode({ status: "sleeping" })).success).toBe(false);
    const { leases: _leases, ...withoutLeases } = sampleWorkerNode();
    void _leases;
    expect(workerNodeViewSchema.safeParse(withoutLeases).success).toBe(false);
    expect(workerNodeListSchema.parse([sampleWorkerNode(), sampleWorkerNode({ worker_node_id: "worker-node-b", name: "worker-b" })])).toHaveLength(2);
  });

  it("parses the control node status", () => {
    const status = controlNodeStatusSchema.parse(sampleControlNodeStatus);
    expect(status.expected_fingerprints.images["scenegems-worker-node"]).toBe("sha256:aaaa");
  });

  it("parses jobs with available_at, progress and log lines", () => {
    const job = jobViewSchema.parse(sampleJob());
    expect(job.available_at).toBe("2026-10-26T09:58:00+00:00");
    expect(job.progress?.progress).toBe(0.5);
    expect(jobViewSchema.parse(sampleJob({ progress: null, state: "queued", lease_owner: null })).progress).toBeNull();

    const detail = jobDetailSchema.parse({
      ...sampleJob(),
      payload: { request_id: "r1" },
      events: [
        { at: "2026-10-26T09:58:00+00:00", kind: "submitted", from_state: null, to_state: "queued", attempt: 0, lease_id: null, worker_node_id: null, detail: {} },
      ],
      log_lines: [sampleLogLine],
    });
    expect(detail.log_lines[0].text).toBe("sample 12 valid");
  });

  it("parses campaign summary, detail, events and config", () => {
    expect(campaignSummarySchema.parse(sampleCampaignSummary).actual_state).toBe("running");
    const detail = campaignDetailSchema.parse(sampleCampaignDetail());
    expect(detail.fecs[0].verdicts["0"]).toEqual({ passed: 2, failed: 1 });
    expect(detail.totals.verdicts.failed).toBe(1);
    expect(campaignEventSchema.parse(sampleEvent).kind).toBe("started");
    expect(
      campaignConfigSchema.parse({
        current_version: 1,
        versions: [{ version: 1, config_hash: "h", created_at: "2026-10-26T09:00:00+00:00", config: { name: "x" } }],
      }).versions
    ).toHaveLength(1);
    expect(campaignSummarySchema.safeParse({ ...sampleCampaignSummary, actual_state: "flying" }).success).toBe(false);
  });

  it("parses a case with its jobs, run records and verdicts, and the case index when present", () => {
    const detail = caseDetailSchema.parse({
      ...sampleCase,
      progress: { steps: {} },
      jobs: [
        {
          stage: "generate_scene",
          run_index: null,
          repeat_index: null,
          idempotency_key: "campaign:c1:case:5:generate_scene",
          job_id: "job-1",
          intent: false,
          created_at: "2026-10-26T09:10:00+00:00",
          submitted_at: "2026-10-26T09:10:01+00:00",
          job: {
            job_type: "scene_generation",
            state: "succeeded",
            priority: 100,
            attempt: 1,
            failed_attempts: 0,
            max_attempts: 3,
            lease_owner: null,
            available_at: "2026-10-26T09:10:01+00:00",
            started_at: "2026-10-26T09:10:02+00:00",
            finished_at: "2026-10-26T09:11:00+00:00",
            error: null,
          },
        },
        {
          stage: "simulate",
          run_index: 0,
          repeat_index: 0,
          idempotency_key: "campaign:c1:case:5:simulate:0:0",
          job_id: null,
          intent: true,
          created_at: "2026-10-26T09:12:00+00:00",
          submitted_at: null,
          job: null,
        },
      ],
      run_records: [sampleRunRecord],
      verdicts: [sampleVerdict],
    });
    expect(detail.jobs[1].job).toBeNull();
    expect(detail.run_records[0].artifacts.state_log).toBe("sha256:cccc");
    expect(detail.verdicts[0].failed_rules).toEqual(["rule_8"]);
    expect(verdictSchema.parse({ ...sampleVerdict, case_index: 2 }).case_index).toBe(2);
    expect(runRecordSchema.parse(sampleRunRecord).case_index).toBeUndefined();
  });
});

describe("Phase 6 views", () => {
  it("reads a campaign row of a control node without Phase 6 and one with it", () => {
    const old = campaignSummarySchema.parse(samplePreSixCampaignRow);
    expect(old.kind).toBeUndefined();
    expect(old.made_from).toBeUndefined();
    const row = campaignRowSchema.parse(sampleCampaignRow());
    expect(row.kind).toBe("campaign");
    expect(row.origin).toBe("wizard");
    expect(row.steps).toEqual(["scene_generation", "trajectory_generation"]);
  });

  it("keeps the detail's own totals next to the row fields", () => {
    const detail = campaignDetailSchema.parse({ ...sampleCampaignDetail(), kind: "workbench", origin: "simulation", steps: ["simulation"], made_from: ["c0"] });
    expect(detail.totals.fecs).toBe(1);
    expect(detail.kind).toBe("workbench");
    expect(detail.made_from).toEqual(["c0"]);
  });

  it("accepts every origin and rejects an unknown one", () => {
    for (const origin of ["wizard", "cli", "scene_generation", "trajectory_generation", "simulation", "live_session"]) {
      expect(campaignRowSchema.safeParse(sampleCampaignRow({ origin })).success).toBe(true);
    }
    expect(campaignRowSchema.safeParse(sampleCampaignRow({ origin: "script" })).success).toBe(false);
  });

  it("reads a null origin, as campaigns created before migration 0005 have", () => {
    expect(campaignRowSchema.parse(sampleCampaignRow({ origin: null })).origin).toBeNull();
  });

  it("reads verdicts with a step and without one", () => {
    expect(verdictSchema.parse(sampleSceneVerdict).step).toBe("scene");
    expect(verdictSchema.parse(sampleSceneVerdict).run_record_id).toBeNull();
    expect(verdictSchema.parse(sampleVerdict).step).toBeUndefined();
    expect(verdictSchema.safeParse({ ...sampleVerdict, step: "monitor" }).success).toBe(false);
  });

  it("reads run records with a source and a missing generator", () => {
    const live = runRecordSchema.parse(sampleLiveRunRecord);
    expect(live.source).toBe("live_session");
    expect(live.trajectory_generator).toBeNull();
    expect(runRecordSchema.parse(sampleRunRecord).source).toBeUndefined();
    expect(runRecordSchema.parse(sampleRunRecord).trajectory_generator).toBe("straight");
  });

  it("knows the monitor stages of a case", () => {
    expect(caseViewSchema.parse(sampleMonitoredCase).stage).toBe("monitor_trajectories");
    expect(caseViewSchema.parse({ ...sampleMonitoredCase, stage: "monitor_scene" }).stage).toBe("monitor_scene");
  });

  it("reads an artifact reference with and without a pointer", () => {
    expect(artifactRefSchema.parse(sampleUploadedRef).pointer).toBeNull();
    const withPointer = artifactRefSchema.parse({ sha256: "e".repeat(64), size_bytes: 10, kind: "trajectory_data", pointer: "/trajectories" });
    expect(withPointer.pointer).toBe("/trajectories");
    expect(withPointer.media_type).toBe("application/json");
    expect(artifactRefSchema.safeParse({ ...sampleUploadedRef, size_bytes: -1 }).success).toBe(false);
  });

  it("has a findings fixture for the step views", () => {
    expect(sampleFindings().step).toBe("trajectory_generation");
  });
});
