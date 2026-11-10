import { readResultField } from "../../../domain/cluster/clusterJobs";
import type { ConfigArtifactRef } from "../../../domain/cluster/campaignApi";
import { createFramesApi, parseFrames, runFramesFlow } from "../../../domain/cluster/framesApi";
import { listOutputs, type OutputRow } from "../../../domain/cluster/historyApi";
import { exploredFecsOfResult, parseExplorationResult, type ExplorationResult, type ExploredFec } from "../../../domain/designSpace/explorationResult";
import { OperatorApiError, type OperatorClient } from "../../../domain/cluster/operatorApi";
import type { CaseDetail, PipelineStage, RunRecord } from "../../../domain/cluster/schemas";
import { buildFramesFromTrajectoryData, parseScenarioFile } from "../../../domain/sceneGeneration/parseEvaluationDataFile";
import type { EvaluationData, SimulationFrame } from "../../../domain/simulation/types";
import { EntryEndedError, stageJob } from "./entryFollower";
import { caseLabel } from "./entryLabels";
import type { PageOutput } from "./pageStore";
import type { WorkbenchTarget } from "./workbenchTarget";

/**
 * Loads the output of an entry for its workbench page: the scene, the planned trajectories or the
 * simulated run of one case, with the monitor's frames, fetched from the control node (artifacts through
 * `/cluster/artifacts/<sha>`, a run's frames through the frames route). A 404 means the entry (or
 * its output) was deleted: the loader rejects with an `EntryEndedError` that is `gone`, and the
 * page clears itself.
 */

export type LoaderClient = Pick<OperatorClient, "getCase" | "getJob" | "artifactUrl" | "request">;

export interface LoaderOptions {
  signal?: AbortSignal;
  fetch?: typeof fetch;
  /** A run's monitor frames; the frames route (a post-hoc job over its state log) by default. */
  runFrames?: (client: LoaderClient, campaignId: string, runRecordId: number, signal?: AbortSignal) => Promise<SimulationFrame[]>;
}

export interface LoadedScene {
  step: "scene_generation";
  scene: SimulationFrame;
  evaluationData: EvaluationData;
  /** The scene as a scenario file holds it (EvaluationData with `best_scene`). */
  scenario: Record<string, unknown>;
  valid: boolean;
  /** The scene monitor's judgment of the scene, null when the step ran unmonitored. */
  monitorFrame: SimulationFrame | null;
  output: PageOutput;
  /** The case's index in its class (0-based). */
  caseIndex: number;
}

export interface LoadedTrajectories {
  step: "trajectory_generation";
  /** The TrajectoryData document (`trajectories`, `monitor_frames`). */
  trajectoryData: Record<string, unknown>;
  /** The monitor's frames over the planned trajectories, or the planned scenes when it ran unmonitored. */
  frames: SimulationFrame[];
  valid: boolean;
  complete: boolean | null;
  output: PageOutput;
  caseIndex: number;
}

/** What the simulation page fills its setup from, so the run can run again. */
export interface LoadedRunSetup {
  simulationLayer: string;
  /** The control layer the run's stack section names (custom), or null for the one its layer implies. */
  controlLayer: string | null;
  mode: string | null;
  /** SITL's requested pace of an ArduPilot run; null on the kinematic layer. */
  speedup: number | null;
  windVector: [number, number, number];
  waves: { amplitude: number; period: number; steepness: number; direction: [number, number] } | null;
}

export interface LoadedRun {
  step: "simulation";
  runRecord: RunRecord;
  /** The run's input as a full trajectory scenario (`{trajectories: ...}`), null when it is not kept. */
  scenario: Record<string, unknown> | null;
  frames: SimulationFrame[];
  setup: LoadedRunSetup;
  /** The run's input trajectories, as the page's input to run it again. */
  input: PageOutput | null;
  caseIndex: number;
}

export interface LoadedExploration {
  step: "design_space_exploration";
  /** The exploration job's result, null when the control node reports none (the job did not end). */
  result: ExplorationResult | null;
  /** The explored FECs in index order. */
  fecs: ExploredFec[];
  caseIndex: number;
}

export type LoadedOutput = LoadedExploration | LoadedScene | LoadedTrajectories | LoadedRun;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function gone<T>(call: () => Promise<T>, what: string): Promise<T> {
  try {
    return await call();
  } catch (error) {
    if (error instanceof OperatorApiError && error.status === 404) {
      throw new EntryEndedError(`${what} was deleted.`, true);
    }
    throw error;
  }
}

/** An artifact's JSON and its size in bytes. A missing artifact answers 404 (`OperatorApiError`). */
export async function fetchArtifact(client: Pick<OperatorClient, "artifactUrl">, sha256: string, options: Pick<LoaderOptions, "signal" | "fetch"> = {}) {
  const fetchImpl = options.fetch ?? ((input: RequestInfo | URL, init?: RequestInit) => globalThis.fetch(input, init));
  const path = `/cluster/artifacts/${sha256}`;
  let response: Response;
  try {
    response = await fetchImpl(client.artifactUrl(sha256), { headers: { Accept: "application/json" }, signal: options.signal });
  } catch (error) {
    if (options.signal?.aborted) {
      throw error;
    }
    throw new OperatorApiError("network", `cannot download the output (${error instanceof Error ? error.message : String(error)})`, path);
  }
  if (!response.ok) {
    throw new OperatorApiError("http", `the output artifact answered HTTP ${response.status}`, path, response.status);
  }
  const text = await response.text();
  try {
    return { document: JSON.parse(text) as unknown, sizeBytes: new TextEncoder().encode(text).length };
  } catch (error) {
    throw new OperatorApiError("schema", `the output artifact is not JSON (${error instanceof Error ? error.message : String(error)})`, path, response.status);
  }
}

function sourceOf(target: WorkbenchTarget) {
  return { campaign_id: target.campaignId, case_id: target.caseId, step: target.step };
}

function ref(sha256: string, sizeBytes: number, kind: string, pointer: string | null = null): ConfigArtifactRef {
  return { sha256, size_bytes: sizeBytes, kind, media_type: "application/json", pointer };
}

/** The monitor frames of a stage's post-hoc job (kept with `policy.keep_frames`), empty when it has none. */
export async function stageMonitorFrames(client: LoaderClient, detail: CaseDetail, stage: PipelineStage, options: LoaderOptions = {}): Promise<SimulationFrame[]> {
  const job = stageJob(detail, stage);
  if (job === null || job.job_id === null || job.job?.state !== "succeeded") {
    return [];
  }
  const view = await client.getJob(job.job_id, options.signal);
  const result = isRecord(view.result) ? view.result : {};
  if (result.frames === undefined || result.frames === null) {
    return [];
  }
  return parseFrames(await readResultField(client, result.frames, { signal: options.signal, fetch: options.fetch }));
}

/** A run's frames through the frames route: the control node's post-hoc job over the stored state log. */
export async function framesOfRun(client: LoaderClient, campaignId: string, runRecordId: number, signal?: AbortSignal): Promise<SimulationFrame[]> {
  const phase = await runFramesFlow(createFramesApi(client, campaignId, runRecordId), { signal });
  if (phase.phase === "done") {
    return phase.frames;
  }
  if (phase.phase === "idle") {
    throw new DOMException("Loading the run was stopped.", "AbortError");
  }
  throw new Error(`The run's frames are not available: ${"message" in phase ? phase.message : phase.phase}`);
}

/** A full trajectory scenario of a planned or recorded trajectory document, for the gateway and the cluster runs. */
export function trajectoryScenarioOf(document: unknown): Record<string, unknown> | null {
  if (!isRecord(document)) {
    return null;
  }
  if (isRecord(document.trajectories) && Array.isArray(document.trajectories.scene_list)) {
    return document;
  }
  return Array.isArray(document.scene_list) ? { trajectories: document } : null;
}

function numberTriple(value: unknown): [number, number, number] {
  return Array.isArray(value) && value.length === 3 && value.every((n) => typeof n === "number") ? (value as [number, number, number]) : [0, 0, 0];
}

export function runSetupOf(record: Pick<RunRecord, "stack" | "environment">): LoadedRunSetup {
  const config = isRecord(record.stack.config) ? record.stack.config : record.stack;
  const waves = isRecord(record.environment.waves) ? record.environment.waves : null;
  return {
    simulationLayer: typeof config.simulation_layer === "string" ? config.simulation_layer : "kinematic",
    controlLayer: typeof config.control_layer === "string" ? config.control_layer : null,
    mode: typeof config.mode === "string" ? config.mode : null,
    speedup: typeof config.speedup === "number" && Number.isFinite(config.speedup) ? config.speedup : null,
    windVector: numberTriple(record.environment.wind_vector),
    waves:
      waves && typeof waves.amplitude === "number"
        ? {
            amplitude: waves.amplitude,
            period: typeof waves.period === "number" ? waves.period : 0,
            steepness: typeof waves.steepness === "number" ? waves.steepness : 0,
            direction: Array.isArray(waves.direction) && waves.direction.length === 2 ? (waves.direction as [number, number]) : [0, 0],
          }
        : null,
  };
}

async function loadScene(client: LoaderClient, target: WorkbenchTarget, detail: CaseDetail, options: LoaderOptions): Promise<LoadedScene> {
  if (detail.scene_artifact === null) {
    throw new EntryEndedError(detail.state === "active" ? "The scene is not generated yet." : "The case has no scene.", false);
  }
  const { document, sizeBytes } = await gone(() => fetchArtifact(client, detail.scene_artifact as string, options), "The scene");
  if (!isRecord(document)) {
    throw new Error("The scene artifact is not a scenario.");
  }
  const parsed = parseScenarioFile(JSON.stringify(document));
  const frames = await stageMonitorFrames(client, detail, "monitor_scene", options).catch(() => []);
  return {
    step: "scene_generation",
    scene: parsed.scene,
    evaluationData: parsed.evaluationData,
    scenario: document,
    valid: !(detail.state === "dropped" && detail.stage === "generate_scene"),
    monitorFrame: frames[0] ?? null,
    output: { label: `Scene of ${caseLabel(detail.case_index, target.campaignId)}`, ref: ref(detail.scene_artifact, sizeBytes, "scene"), source: sourceOf(target) },
    caseIndex: detail.case_index,
  };
}

async function loadTrajectories(client: LoaderClient, target: WorkbenchTarget, detail: CaseDetail, options: LoaderOptions): Promise<LoadedTrajectories> {
  if (detail.trajectories_artifact === null) {
    throw new EntryEndedError(detail.state === "active" ? "The trajectories are not planned yet." : "The case has no trajectories.", false);
  }
  const { document, sizeBytes } = await gone(() => fetchArtifact(client, detail.trajectories_artifact as string, options), "The trajectories");
  const scenario = trajectoryScenarioOf(document);
  if (scenario === null) {
    throw new Error("The trajectory artifact holds no trajectories.");
  }
  const planned = buildFramesFromTrajectoryData(scenario);
  const monitored = await stageMonitorFrames(client, detail, "monitor_trajectories", options).catch(() => []);
  return {
    step: "trajectory_generation",
    trajectoryData: scenario,
    frames: monitored.length > 0 ? monitored : planned,
    valid: planned.length > 0,
    complete: detail.trajectories_complete,
    output: {
      label: `Trajectories of ${caseLabel(detail.case_index, target.campaignId)}`,
      ref: ref(detail.trajectories_artifact, sizeBytes, "trajectories", scenario === document ? "/trajectories" : null),
      source: sourceOf(target),
    },
    caseIndex: detail.case_index,
  };
}

async function loadRun(client: LoaderClient, target: WorkbenchTarget, detail: CaseDetail, options: LoaderOptions): Promise<LoadedRun> {
  const runRecord = (target.runRecordId === undefined ? detail.run_records[0] : detail.run_records.find((record) => record.run_record_id === target.runRecordId)) ?? null;
  if (runRecord === null) {
    throw new EntryEndedError(detail.state === "active" ? "The run has not ended yet." : "The case has no recorded run.", target.runRecordId !== undefined && detail.state !== "active");
  }
  const runFrames = options.runFrames ?? framesOfRun;
  const frames = await gone(() => runFrames(client, target.campaignId, runRecord.run_record_id, options.signal), "The run");
  const inputSha = runRecord.artifacts.trajectories ?? null;
  let scenario: Record<string, unknown> | null = null;
  let input: PageOutput | null = null;
  if (inputSha) {
    try {
      const { document, sizeBytes } = await fetchArtifact(client, inputSha, options);
      scenario = trajectoryScenarioOf(document);
      if (scenario !== null) {
        input = {
          label: `Trajectories of the run in ${caseLabel(detail.case_index, target.campaignId)}`,
          ref: ref(inputSha, sizeBytes, "trajectories", scenario === document ? "/trajectories" : null),
          source: sourceOf(target),
        };
      }
    } catch (error) {
      // A run whose input was freed still replays; it only cannot run again.
      if (!(error instanceof OperatorApiError && error.status === 404)) {
        throw error;
      }
    }
  }
  return { step: "simulation", runRecord, scenario, frames, setup: runSetupOf(runRecord), input, caseIndex: detail.case_index };
}

const OUTPUT_PAGE = 500;

/** Every output row of a step, page by page. */
export async function allOutputs(client: Pick<OperatorClient, "request">, campaignId: string, step: "design_space_exploration", signal?: AbortSignal): Promise<OutputRow[]> {
  const rows: OutputRow[] = [];
  for (;;) {
    const page = await listOutputs(client, campaignId, { step, limit: OUTPUT_PAGE, offset: rows.length }, signal);
    rows.push(...page.items);
    if (page.items.length < OUTPUT_PAGE || (page.total !== null && rows.length >= page.total)) {
      return rows;
    }
  }
}

/** An output row of the exploration as a listed FEC. */
export function exploredFecOfRow(row: OutputRow): ExploredFec {
  return { fecId: row.fec_id, index: row.case_index, vesselCount: row.vessel_count ?? null, obstacleCount: row.obstacle_count ?? null, artifact: row.artifact };
}

async function loadExploration(client: LoaderClient, target: WorkbenchTarget, detail: CaseDetail, options: LoaderOptions): Promise<LoadedExploration> {
  const job = stageJob(detail, "explore_design_space");
  let result: ExplorationResult | null = null;
  if (job !== null && job.job_id !== null) {
    const view = await client.getJob(job.job_id, options.signal).catch((error: unknown) => {
      if (error instanceof OperatorApiError && error.status === 404) {
        return null;
      }
      throw error;
    });
    result = view === null ? null : parseExplorationResult(view.result);
  }
  if (detail.state === "active" && result === null) {
    throw new EntryEndedError("The exploration has not ended yet.", false);
  }
  const rows = await gone(() => allOutputs(client, target.campaignId, "design_space_exploration", options.signal), "The entry");
  const fecs = rows.length > 0 ? rows.map(exploredFecOfRow).sort((a, b) => a.index - b.index) : result !== null ? exploredFecsOfResult(result) : [];
  return { step: "design_space_exploration", result, fecs, caseIndex: detail.case_index };
}

/** Fetches the output a target names. Rejects with `EntryEndedError` (`gone`) when the entry or output was deleted. */
export async function loadEntryOutput(client: LoaderClient, target: WorkbenchTarget, options: LoaderOptions = {}): Promise<LoadedOutput> {
  const detail = await gone(() => client.getCase(target.campaignId, target.caseId, options.signal), "The entry");
  switch (target.step) {
    case "design_space_exploration":
      return loadExploration(client, target, detail, options);
    case "scene_generation":
      return loadScene(client, target, detail, options);
    case "trajectory_generation":
      return loadTrajectories(client, target, detail, options);
    case "simulation":
      return loadRun(client, target, detail, options);
  }
}
