import type { SimulationFrame } from "../simulation/types";

/**
 * What a finished trajectory generation run actually produced.
 *
 * The backend reports a run as valid whenever it returns more than one scene, so a
 * planner that ran out of admissible manoeuvres after two steps and a planner that
 * planned the whole horizon are reported identically. That is why a run could stop
 * with nothing on screen to say so. Everything here is derived from the result
 * payload the frontend already holds, so it needs no protocol change.
 */
export interface TrajectoryRunSummary {
  /** Number of scenes in the planned trajectory. */
  sceneCount: number;
  /** Seconds between scenes. */
  timeStep: number;
  /** Planned span in seconds. */
  spanSeconds: number;
  /** Iterations the planner reported, when the payload carries them. */
  iterations: number | null;
  /**
   * Labels of the encounters still live in the final scene, in the order they appear.
   * A trajectory that ends here ends mid-encounter, which is the clearest available
   * sign that the planner stopped early rather than finishing. Null when the run
   * carried no monitor data, in which case nothing can be said either way.
   */
  unresolvedEncounters: string[] | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Encounters that are neither classified OTHER nor already past and clear. */
function unresolvedEncountersIn(frame: SimulationFrame): string[] {
  const passedByRelationId = new Map(
    frame.colregsStates.map((state) => [state.relationId, state.actorsPassedEachOther])
  );
  const labels: string[] = [];
  for (const context of frame.situationContexts) {
    if (context.situationType === "OTHER") {
      continue;
    }
    if (passedByRelationId.get(context.relationId) === true) {
      continue;
    }
    labels.push(`${context.relationId} ${context.situationLabel}`);
  }
  return labels;
}

/**
 * Summarizes a finished run from its result payload and the frames built from it.
 *
 * `frames` is what `buildFramesFromTrajectoryData` returned for the same payload, so
 * the monitor fields are already parsed. Returns null when the payload is not a
 * trajectory result at all.
 */
export function summarizeTrajectoryResult(
  raw: unknown,
  frames: SimulationFrame[]
): TrajectoryRunSummary | null {
  if (!isRecord(raw)) {
    return null;
  }
  const trajectories = raw.trajectories;
  if (!isRecord(trajectories) || !Array.isArray(trajectories.scene_list)) {
    return null;
  }

  const sceneCount = trajectories.scene_list.length;
  const timeStepRaw = Number(trajectories.time_step);
  const timeStep = Number.isFinite(timeStepRaw) && timeStepRaw > 0 ? timeStepRaw : 1;

  const iterNumbers = raw.iter_numbers;
  let iterations: number | null = null;
  if (isRecord(iterNumbers)) {
    const first = Object.values(iterNumbers).find((value) => Number.isFinite(Number(value)));
    if (first !== undefined) {
      iterations = Number(first);
    }
  }

  // Without monitor data there is no way to tell a finished plan from an abandoned
  // one, so say nothing rather than guess.
  const lastFrame = frames.length > 0 ? frames[frames.length - 1] : undefined;
  const hasMonitorData =
    lastFrame !== undefined &&
    (lastFrame.situationContexts.length > 0 || lastFrame.colregsStates.length > 0);

  return {
    sceneCount,
    timeStep,
    spanSeconds: Math.max(0, sceneCount - 1) * timeStep,
    iterations,
    unresolvedEncounters: hasMonitorData ? unresolvedEncountersIn(lastFrame) : null,
  };
}

/** One line describing what the run produced. */
export function describeTrajectoryRun(summary: TrajectoryRunSummary): string {
  const steps = `${summary.sceneCount} ${summary.sceneCount === 1 ? "scene" : "scenes"}`;
  const span = `${Math.round(summary.spanSeconds)} s`;
  const iterations =
    summary.iterations === null ? "" : ` after ${summary.iterations} iterations`;
  return `Planned ${steps} (${span})${iterations}.`;
}

/**
 * A warning when the trajectory ends mid-encounter, or null when it does not.
 *
 * Ending with an encounter still live means the planner stopped before the situation
 * it was asked to solve was over: it either ran out of admissible manoeuvres, hit its
 * timeout, or hit the iteration cap.
 */
export function warnAboutTrajectoryRun(summary: TrajectoryRunSummary): string | null {
  const unresolved = summary.unresolvedEncounters;
  if (unresolved === null || unresolved.length === 0) {
    return null;
  }
  const list = unresolved.join(", ");
  return (
    `The trajectory ends while ${unresolved.length === 1 ? "an encounter is" : "encounters are"} ` +
    `still unresolved (${list}), so the planner stopped before finishing. It either ran out of ` +
    `admissible manoeuvres, or hit the timeout or the iteration cap. Check the Monitor tab for ` +
    `the last scene, and try a longer timeout or a higher iteration cap.`
  );
}
