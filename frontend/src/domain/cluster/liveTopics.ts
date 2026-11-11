import { z } from "zod";
import {
  campaignDetailSchema,
  campaignEventSchema,
  campaignRowSchema,
  campaignSummarySchema,
  classViewSchema,
  jobViewSchema,
  logLineSchema,
  workerNodeListSchema,
  workerNodeViewSchema,
  type CampaignDetail,
  type CampaignEvent,
  type CampaignRow,
  type CampaignTotals,
  type ClassView,
  type JobView,
  type LogLine,
  type WorkerNodeView,
} from "./schemas";

/**
 * Snapshots and updates of each live channel topic (design doc 5.3), with reducers that
 * fold them into a topic state. A reducer throws (a ZodError) on data that does not match.
 */

export interface LiveTopicReducer<T> {
  snapshot(raw: unknown): T;
  update(state: T, data: unknown, seq: number): T;
}

/** The raw snapshot and the most recent updates, for topics without a typed reducer. */
export interface RawTopicState {
  snapshot: unknown;
  updates: { seq: number; data: unknown }[];
}

const RAW_UPDATES_KEPT = 200;

export const rawTopicReducer: LiveTopicReducer<RawTopicState> = {
  snapshot: (raw) => ({ snapshot: raw, updates: [] }),
  update: (state, data, seq) => ({ snapshot: state.snapshot, updates: [...state.updates, { seq, data }].slice(-RAW_UPDATES_KEPT) }),
};

// worker nodes

export const workerNodesUpdateSchema = z.union([
  z.object({ worker_node: workerNodeViewSchema }),
  z.object({ removed: z.string() }),
]);

function sortWorkerNodes(workerNodes: WorkerNodeView[]): WorkerNodeView[] {
  return [...workerNodes].sort((a, b) => a.name.localeCompare(b.name) || a.worker_node_id.localeCompare(b.worker_node_id));
}

/** Replaces the worker node with the same id, or adds it. */
export function upsertWorkerNode(workerNodes: readonly WorkerNodeView[], workerNode: WorkerNodeView): WorkerNodeView[] {
  const others = workerNodes.filter((entry) => entry.worker_node_id !== workerNode.worker_node_id);
  return sortWorkerNodes([...others, workerNode]);
}

export const workerNodesReducer: LiveTopicReducer<WorkerNodeView[]> = {
  snapshot: (raw) => sortWorkerNodes(workerNodeListSchema.parse(raw)),
  update: (workerNodes, data) => {
    const update = workerNodesUpdateSchema.parse(data);
    if ("worker_node" in update) {
      return upsertWorkerNode(workerNodes, update.worker_node);
    }
    return workerNodes.filter((workerNode) => workerNode.worker_node_id !== update.removed);
  },
};

// campaign:<id>

export const campaignUpdateSchema = z.union([
  z.object({ event: campaignEventSchema }),
  z.object({ campaign: campaignSummarySchema }),
  z.object({ fecs: z.array(classViewSchema) }),
]);

export const campaignSnapshotSchema = campaignDetailSchema.extend({
  /** The newest event when the snapshot was taken; pushed events up to it may repeat the history. */
  last_event_id: z.number().int().nullable().optional(),
});

export interface CampaignTopicState {
  detail: CampaignDetail;
  /** Read the history up to this id from the events route; pushed events at or below it are skipped. */
  lastEventId: number | null;
  /** Events pushed since the snapshot, oldest first. */
  events: CampaignEvent[];
}

const CAMPAIGN_EVENTS_KEPT = 500;

/** The totals of a campaign detail over its FECs, as `campaign_views.campaign_detail_view` computes them. */
export function campaignTotals(classes: readonly ClassView[]): CampaignTotals {
  const verdicts: Record<string, number> = {};
  for (const entry of classes) {
    for (const states of Object.values(entry.verdicts)) {
      for (const [state, count] of Object.entries(states)) {
        verdicts[state] = (verdicts[state] ?? 0) + count;
      }
    }
  }
  const sum = (pick: (entry: ClassView) => number) => classes.reduce((total, entry) => total + pick(entry), 0);
  return {
    fecs: classes.length,
    fecs_open: classes.filter((entry) => entry.state === "open").length,
    fecs_complete: classes.filter((entry) => entry.state === "complete").length,
    fecs_abandoned: classes.filter((entry) => entry.state === "abandoned").length,
    quota: sum((entry) => entry.quota),
    complete: sum((entry) => entry.complete),
    dropped: sum((entry) => entry.dropped),
    in_flight: sum((entry) => entry.in_flight),
    verdicts,
  };
}

export const campaignReducer: LiveTopicReducer<CampaignTopicState> = {
  snapshot: (raw) => {
    const { last_event_id, ...detail } = campaignSnapshotSchema.parse(raw);
    return { detail, lastEventId: last_event_id ?? null, events: [] };
  },
  update: (state, data) => {
    const update = campaignUpdateSchema.parse(data);
    if ("event" in update) {
      const id = update.event.event_id;
      if ((state.lastEventId !== null && id <= state.lastEventId) || state.events.some((event) => event.event_id === id)) {
        return state;
      }
      return { ...state, events: [...state.events, update.event].slice(-CAMPAIGN_EVENTS_KEPT) };
    }
    if ("campaign" in update) {
      return { ...state, detail: { ...state.detail, ...update.campaign } };
    }
    const changed = new Map(update.fecs.map((entry) => [entry.fec_id, entry]));
    const classes = state.detail.fecs.map((entry) => changed.get(entry.fec_id) ?? entry);
    for (const entry of update.fecs) {
      if (!state.detail.fecs.some((existing) => existing.fec_id === entry.fec_id)) {
        classes.push(entry);
      }
    }
    return { ...state, detail: { ...state.detail, fecs: classes, totals: campaignTotals(classes) } };
  },
};

// campaigns (Phase 6, design doc 6.5)

export const campaignsUpdateSchema = z.union([z.object({ campaign: campaignRowSchema }), z.object({ deleted: z.string() })]);
export type CampaignsUpdate = z.infer<typeof campaignsUpdateSchema>;

export interface CampaignsTopicState {
  /** The latest pushed row of each entry changed since the snapshot. */
  rows: Record<string, CampaignRow>;
  /** Entries deleted since the snapshot. */
  deleted: string[];
  /** The latest update, so a consumer can tell whether its page must be read again. */
  last: CampaignsUpdate | null;
  /**
   * A token of the snapshot the rows follow. A new one (a reconnect, or a resubscribe after a gap
   * in seq) drops the pushed rows, and what changed meanwhile is only in a fresh read of the page.
   */
  epoch: object;
}

const CAMPAIGNS_KEPT = 500;

/** The `campaigns` topic: the snapshot carries nothing (the list is read from the route), updates are rows and deletions. */
export const campaignsReducer: LiveTopicReducer<CampaignsTopicState> = {
  snapshot: () => ({ rows: {}, deleted: [], last: null, epoch: {} }),
  update: (state, data) => {
    const update = campaignsUpdateSchema.parse(data);
    if ("campaign" in update) {
      const id = update.campaign.campaign_id;
      const { [id]: _previous, ...others } = state.rows;
      void _previous;
      const kept = Object.entries(others).slice(-(CAMPAIGNS_KEPT - 1));
      return { rows: { ...Object.fromEntries(kept), [id]: update.campaign }, deleted: state.deleted.filter((entry) => entry !== id), last: update, epoch: state.epoch };
    }
    const { [update.deleted]: _removed, ...rows } = state.rows;
    void _removed;
    return { rows, deleted: [...state.deleted.filter((entry) => entry !== update.deleted), update.deleted].slice(-CAMPAIGNS_KEPT), last: update, epoch: state.epoch };
  },
};

// job:<id>

/** A job's status as the live channel pushes it (the operator API's `JobProgress` without the lease). */
export const liveJobStatusSchema = z.object({
  progress: z.number().nullable(),
  message: z.string(),
  at: z.string(),
  detail: z.record(z.string(), z.unknown()).nullable().optional(),
});

export const jobSnapshotSchema = jobViewSchema.extend({
  logs: z.array(logLineSchema).default([]),
});

export const jobUpdateSchema = z.union([
  z.object({ status: liveJobStatusSchema }),
  z.object({ logs: z.array(logLineSchema) }),
  z.object({ job: jobViewSchema }),
]);

export type LiveJobStatus = z.infer<typeof liveJobStatusSchema>;

export interface JobTopicState {
  job: JobView;
  /** The latest status: from the snapshot's progress, then from status updates. */
  status: LiveJobStatus | null;
  logs: LogLine[];
  /** The number of `logs[0]` since the snapshot: line i is number `firstLog + i`, a key that stays while older lines drop off. */
  firstLog: number;
}

export const JOB_LOG_LINES_KEPT = 1000;

export const jobReducer: LiveTopicReducer<JobTopicState> = {
  snapshot: (raw) => {
    const { logs, ...job } = jobSnapshotSchema.parse(raw);
    const status = job.progress ? { progress: job.progress.progress, message: job.progress.message, at: job.progress.at } : null;
    const kept = logs.slice(-JOB_LOG_LINES_KEPT);
    return { job, status, logs: kept, firstLog: logs.length - kept.length };
  },
  update: (state, data) => {
    const update = jobUpdateSchema.parse(data);
    if ("status" in update) {
      return { ...state, status: update.status };
    }
    if ("logs" in update) {
      const all = [...state.logs, ...update.logs];
      const kept = all.slice(-JOB_LOG_LINES_KEPT);
      return { ...state, logs: kept, firstLog: state.firstLog + all.length - kept.length };
    }
    return { ...state, job: update.job };
  },
};

export const instanceSnapshotSchema = z.object({
  worker_node_id: z.string(),
  instance: z.string(),
  kind: z.string(),
  /** The job's state for a job instance, the worker node's status for a pool. */
  state: z.string(),
  job_id: z.string().nullable().optional(),
  attempt: z.number().int().nullable().optional(),
  /** Speed (multiple of real time) the control node paces an observed simulation to; null when unpaced or not observed. */
  observed_speed: z.number().nullable().optional(),
});

export const sceneSampleSchema = z.object({
  kind: z.literal("scene_sample"),
  request_id: z.string(),
  valid: z.boolean(),
  /** The worker's last scene for the request; earlier ones are search progress. */
  final: z.boolean().optional(),
  /** The scene as one frame of the workbench's wire format. */
  scene: z.unknown().optional(),
  evaluation_data: z.unknown(),
});

export const trajectoryPreviewSchema = z.object({
  kind: z.literal("trajectory_preview"),
  request_id: z.string(),
  trajectories: z.unknown(),
  final: z.boolean().optional(),
  valid: z.boolean().nullable().optional(),
  complete: z.boolean().nullable().optional(),
  error_message: z.string().nullable().optional(),
});

export const simulationFramesSchema = z.object({
  kind: z.literal("simulation_frames"),
  job_id: z.string(),
  /** Frames in the workbench's frame wire format (`gateway.serialization.serialize_monitored_frame`). */
  frames: z.array(z.unknown()),
});

export const instanceStatusSchema = z.object({
  kind: z.literal("status"),
  state: z.string(),
  message: z.string().nullable().optional(),
  progress: z.number().nullable().optional(),
  /** Optional: a changed pace of an observed run. */
  observed_speed: z.number().nullable().optional(),
  /** The job's latest status detail (an attended simulation's phase and ground control ports). */
  detail: z.record(z.string(), z.unknown()).nullable().optional(),
});

export const instanceUpdateSchema = z.discriminatedUnion("kind", [
  sceneSampleSchema,
  trajectoryPreviewSchema,
  simulationFramesSchema,
  instanceStatusSchema,
]);

export type InstanceSnapshot = z.infer<typeof instanceSnapshotSchema>;
export type SceneSample = z.infer<typeof sceneSampleSchema>;
export type TrajectoryPreview = z.infer<typeof trajectoryPreviewSchema>;

export interface InstanceTopicState {
  info: InstanceSnapshot;
  /** The latest state, message and progress from status updates (the snapshot's state until one arrives). */
  state: string;
  message: string | null;
  progress: number | null;
  sceneSample: SceneSample | null;
  trajectoryPreview: TrajectoryPreview | null;
  /** Simulation frames since the snapshot, oldest first, bounded. */
  frames: unknown[];
  /** Total frames received, including those no longer kept. */
  frameCount: number;
}

export const INSTANCE_FRAMES_KEPT = 5000;

export const instanceReducer: LiveTopicReducer<InstanceTopicState> = {
  snapshot: (raw) => {
    const info = instanceSnapshotSchema.parse(raw);
    return { info, state: info.state, message: null, progress: null, sceneSample: null, trajectoryPreview: null, frames: [], frameCount: 0 };
  },
  update: (state, data) => {
    const update = instanceUpdateSchema.parse(data);
    switch (update.kind) {
      case "scene_sample":
        return { ...state, sceneSample: update };
      case "trajectory_preview":
        return { ...state, trajectoryPreview: update };
      case "simulation_frames":
        return {
          ...state,
          frames: [...state.frames, ...update.frames].slice(-INSTANCE_FRAMES_KEPT),
          frameCount: state.frameCount + update.frames.length,
        };
      case "status":
        return {
          ...state,
          info: update.observed_speed === undefined ? state.info : { ...state.info, observed_speed: update.observed_speed },
          state: update.state,
          message: update.message ?? null,
          progress: update.progress ?? null,
        };
    }
  },
};
