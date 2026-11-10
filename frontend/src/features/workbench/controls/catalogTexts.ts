import { create } from "zustand";

/**
 * The texts of the control node's catalog FECs the scene page has read: for the rows in view (their
 * relations in words), the FEC previewed and the one selected (their graphs). Each is fetched once,
 * a few at a time; the 828 FECs of the catalog are never read only to be listed. Not persisted.
 */

interface CatalogTextsState {
  texts: Record<string, string>;
  /** Why a text could not be read, by class id. */
  errors: Record<string, string>;
  loading: Record<string, true>;
  loaded: (classId: string, text: string) => void;
  failed: (classId: string, message: string) => void;
  started: (classId: string) => void;
  /** Forgets every text (another cluster's catalog). */
  reset: () => void;
}

function without<T>(record: Record<string, T>, key: string): Record<string, T> {
  if (!(key in record)) {
    return record;
  }
  const rest = { ...record };
  delete rest[key];
  return rest;
}

export const useCatalogTexts = create<CatalogTextsState>()((set) => ({
  texts: {},
  errors: {},
  loading: {},
  loaded: (classId, text) => set((state) => ({ texts: { ...state.texts, [classId]: text }, loading: without(state.loading, classId) })),
  failed: (classId, message) => set((state) => ({ errors: { ...state.errors, [classId]: message }, loading: without(state.loading, classId) })),
  started: (classId) => set((state) => ({ loading: { ...state.loading, [classId]: true }, errors: without(state.errors, classId) })),
  reset: () => set({ texts: {}, errors: {}, loading: {} }),
}));

const CONCURRENCY = 4;

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/** Reads the texts of these classes that are neither read, being read nor failed. */
export async function loadCatalogTexts(read: (classId: string) => Promise<string>, classIds: readonly string[]): Promise<void> {
  const state = useCatalogTexts.getState();
  const wanted = [...new Set(classIds)].filter((id) => state.texts[id] === undefined && state.loading[id] === undefined && state.errors[id] === undefined);
  wanted.forEach((id) => useCatalogTexts.getState().started(id));
  let next = 0;
  const worker = async () => {
    while (next < wanted.length) {
      const classId = wanted[next];
      next += 1;
      try {
        useCatalogTexts.getState().loaded(classId, await read(classId));
      } catch (error) {
        useCatalogTexts.getState().failed(classId, `The FEC's text could not be read: ${describe(error)}`);
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(CONCURRENCY, wanted.length) }, worker));
}

/** One class's text, from the cache or read now; rejects when it cannot be read. */
export async function catalogText(read: (classId: string) => Promise<string>, classId: string): Promise<string> {
  const known = useCatalogTexts.getState().texts[classId];
  if (known !== undefined) {
    return known;
  }
  const text = await read(classId);
  useCatalogTexts.getState().loaded(classId, text);
  return text;
}
