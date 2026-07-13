import type { SimulationFrame } from "../simulation/types";

export interface MergeFramesRequest {
  existing: SimulationFrame[];
  incoming: SimulationFrame[];
}

export interface MergeFramesResponse {
  merged: SimulationFrame[];
}

/** Merge trajectory chunks off the main thread (same semantics as playbackStore). */
self.onmessage = (event: MessageEvent<MergeFramesRequest>) => {
  const { existing, incoming } = event.data;
  const byTs = new Map<number, SimulationFrame>();
  for (const f of existing) {
    byTs.set(f.timestamp, f);
  }
  for (const f of incoming) {
    byTs.set(f.timestamp, f);
  }
  const merged = Array.from(byTs.values()).sort((a, b) => a.timestamp - b.timestamp);
  const response: MergeFramesResponse = { merged };
  self.postMessage(response);
};
