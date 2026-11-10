import { sampleFrames } from "./sampleFrames";

/**
 * Instance topic payloads shaped as the live channel contract's examples (design doc 5.3,
 * `cluster/protocol/live.py`): scene samples, trajectory previews, simulation frames and the
 * snapshots of pool and job instances.
 */

export function poolSnapshot(instance = "scene_generation-0", overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    worker_node_id: "worker-node-a1",
    instance,
    kind: instance.startsWith("scene") ? "scene_generation" : "trajectory_generation",
    state: "online",
    job_id: null,
    attempt: null,
    ...overrides,
  };
}

export function jobInstanceSnapshot(jobId = "job-1", attempt = 1, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    worker_node_id: "worker-node-a1",
    instance: `job-${jobId}-${attempt}`,
    kind: "simulation",
    state: "running",
    job_id: jobId,
    attempt,
    observed_speed: 10,
    ...overrides,
  };
}

/** A frame of the workbench's wire format (the sample frames the workbench tests use). */
export function wireFrame(index: number): Record<string, unknown> {
  return JSON.parse(JSON.stringify(sampleFrames[index % sampleFrames.length])) as Record<string, unknown>;
}

export function sceneSampleUpdate(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    kind: "scene_sample",
    request_id: "r1",
    valid: false,
    final: false,
    scene: wireFrame(0),
    evaluation_data: { iterations: 42, best_score: 0.8125, status: "searching", constraints: ["a", "b"], nested: { x: 1 } },
    ...overrides,
  };
}

function backendActor(id: number, isOwnShip: boolean): Record<string, unknown> {
  return { id, type: "CargoShip", length: 30, breadth: 8, height: 5, draft: 2, mass: 1000, safety_radius: 15, _is_os: isOwnShip, is_vessel: true };
}

/** The trajectory data of a preview: `trajectories.scene_list` of `_data` tuples, as the trajectory subsystem emits it. */
export function trajectoryData(sceneCount: number, timeStep = 2): Record<string, unknown> {
  const scene_list = Array.from({ length: sceneCount }, (_, step) => ({
    _data: [
      [backendActor(0, true), { x: step * 10, y: 0, speed: 5, heading: 0 }],
      [backendActor(1, false), { x: 200 - step * 8, y: 40, speed: 4, heading: Math.PI }],
    ],
  }));
  return {
    trajectories: { scene_list, time_step: timeStep },
    iter_numbers: { rrt: 120 },
  };
}

export function trajectoryPreviewUpdate(sceneCount = 4, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return { kind: "trajectory_preview", request_id: "t1", trajectories: trajectoryData(sceneCount), final: false, ...overrides };
}

export function trajectoryResultUpdate(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return trajectoryPreviewUpdate(6, { final: true, valid: true, complete: true, error_message: null, ...overrides });
}

export function simulationFramesUpdate(from: number, count: number, jobId = "job-1"): Record<string, unknown> {
  return { kind: "simulation_frames", job_id: jobId, frames: Array.from({ length: count }, (_, offset) => wireFrame(from + offset)) };
}
