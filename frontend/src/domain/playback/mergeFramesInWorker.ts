import type { SimulationFrame } from "../simulation/types";
import MergeFramesWorker from "./mergeFrames.worker?worker";

const CHUNK_WORKER_THRESHOLD = 40;

let worker: Worker | null = null;

function getWorker(): Worker {
  if (!worker) {
    worker = new MergeFramesWorker();
  }
  return worker;
}

export function shouldMergeFramesInWorker(incomingCount: number): boolean {
  return incomingCount >= CHUNK_WORKER_THRESHOLD;
}

let mergeQueue: Promise<unknown> = Promise.resolve();

function mergeFramesInWorkerOnce(
  existing: SimulationFrame[],
  incoming: SimulationFrame[]
): Promise<SimulationFrame[]> {
  return new Promise((resolve, reject) => {
    const w = getWorker();
    const onMessage = (event: MessageEvent<{ merged: SimulationFrame[] }>) => {
      w.removeEventListener("message", onMessage);
      w.removeEventListener("error", onError);
      resolve(event.data.merged);
    };
    const onError = () => {
      w.removeEventListener("message", onMessage);
      w.removeEventListener("error", onError);
      reject(new Error("Frame merge worker failed"));
    };
    w.addEventListener("message", onMessage);
    w.addEventListener("error", onError);
    w.postMessage({ existing, incoming });
  });
}

/** Serializes worker merges so concurrent chunk messages cannot cross-resolve. */
export function mergeFramesInWorker(
  existing: SimulationFrame[],
  incoming: SimulationFrame[]
): Promise<SimulationFrame[]> {
  const task = mergeQueue.then(() => mergeFramesInWorkerOnce(existing, incoming));
  mergeQueue = task.then(
    () => undefined,
    () => undefined
  );
  return task;
}
