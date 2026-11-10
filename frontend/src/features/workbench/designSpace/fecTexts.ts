import type { OperatorClient } from "../../../domain/cluster/operatorApi";
import type { ExploredFec } from "../../../domain/designSpace/explorationResult";
import { artifactText } from "../pages/inputSpecification";
import { useExplorationStore } from "./explorationStore";

/**
 * The texts of the explored FECs, fetched as the page needs them (the selected FEC, the rows in
 * view, every one for an export), a few at a time, each once. A catalog of hundreds of FECs is
 * never fetched whole only to be listed.
 */

export type TextClient = Pick<OperatorClient, "artifactUrl">;

const CONCURRENCY = 4;

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Fetches one FEC's text unless the store has it or fetches it already; resolves with the text, or null when it has none. */
async function fetchOne(client: TextClient, fec: ExploredFec, fetchImpl?: typeof fetch): Promise<string | null> {
  const store = useExplorationStore.getState();
  const known = store.texts[fec.fecId];
  if (known !== undefined) {
    return known;
  }
  if (fec.artifact === null) {
    store.textFailed(fec.fecId, "The master names no text for this FEC.");
    return null;
  }
  const campaignId = store.campaignId;
  store.textLoading(fec.fecId);
  try {
    const text = await artifactText(client, fec.artifact.sha256, undefined, fetchImpl);
    if (useExplorationStore.getState().campaignId === campaignId) {
      useExplorationStore.getState().textLoaded(fec.fecId, text);
    }
    return text;
  } catch (error) {
    if (useExplorationStore.getState().campaignId === campaignId) {
      useExplorationStore.getState().textFailed(fec.fecId, `The FEC's text could not be read: ${describe(error)}`);
    }
    return null;
  }
}

/** Fetches the texts of these FECs that the store neither has nor fetches already. */
export async function loadFecTexts(client: TextClient, fecIds: readonly string[], fetchImpl?: typeof fetch): Promise<void> {
  const state = useExplorationStore.getState();
  const wanted = fecIds
    .map((id) => state.fecs.find((fec) => fec.fecId === id))
    .filter((fec): fec is ExploredFec => fec !== undefined && state.texts[fec.fecId] === undefined && state.loadingTexts[fec.fecId] === undefined && state.textErrors[fec.fecId] === undefined);
  let next = 0;
  const worker = async () => {
    while (next < wanted.length) {
      const fec = wanted[next];
      next += 1;
      await fetchOne(client, fec, fetchImpl);
    }
  };
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, wanted.length) }, worker));
}

/** Every shown FEC's text (an export), fetched where missing; a FEC whose text cannot be read is left out. */
export async function allFecTexts(client: TextClient, fetchImpl?: typeof fetch): Promise<{ fec: ExploredFec; text: string }[]> {
  const fecs = useExplorationStore.getState().fecs;
  const texts: ({ fec: ExploredFec; text: string } | null)[] = new Array(fecs.length).fill(null);
  let next = 0;
  const worker = async () => {
    while (next < fecs.length) {
      const position = next;
      next += 1;
      const text = await fetchOne(client, fecs[position], fetchImpl);
      texts[position] = text === null ? null : { fec: fecs[position], text };
    }
  };
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, fecs.length) }, worker));
  return texts.filter((entry): entry is { fec: ExploredFec; text: string } => entry !== null);
}

/** One FEC's text, fetched when the store does not have it; rejects when it cannot be read. */
export async function fecText(client: TextClient, fec: ExploredFec, fetchImpl?: typeof fetch): Promise<string> {
  const text = await fetchOne(client, fec, fetchImpl);
  if (text === null) {
    throw new Error(useExplorationStore.getState().textErrors[fec.fecId] ?? "The FEC's text could not be read.");
  }
  return text;
}
