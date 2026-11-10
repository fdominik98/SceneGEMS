import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type { ConfigArtifactRef, InputItemSource } from "../../../domain/cluster/campaignApi";
import type { WorkbenchPage, WorkbenchTarget } from "./workbenchTarget";

/**
 * What each workbench page holds (design doc 6.6): its input, set from the previous page's
 * output, a history output or a file, and the target of the latest loaded entry. The pages are
 * independent: the scene page and the trajectory page may show outputs of different campaigns.
 * Contents are not stored here; the page fetches them from the control node (`entryLoader.ts`), and a
 * 404 clears the page.
 */

export type PageInputOrigin = "previous_page" | "history" | "file";

export interface PageInput {
  /** How the page names the input. */
  label: string;
  origin: PageInputOrigin;
  /** The input on the control node: a history output, or a page output that came from an entry. Null for a file not uploaded yet. */
  ref: ConfigArtifactRef | null;
  /** Where it came from, as the entry's config item records it. */
  source: InputItemSource;
}

/** The shown output, as the next page takes it for its input. */
export interface PageOutput {
  label: string;
  /** Null for an output that is not on the control node (a scene loaded from a file). */
  ref: ConfigArtifactRef | null;
  source: InputItemSource;
}

/** idle: nothing loaded; running: the page's own run; following: a live entry; loading: fetching an entry's output. */
export type PageStatus = "idle" | "running" | "following" | "loading" | "shown" | "failed";

export interface PageState {
  input: PageInput | null;
  loaded: WorkbenchTarget | null;
  output: PageOutput | null;
  status: PageStatus;
  /** Why the page is as it is (a deleted entry, a failed load), null when there is nothing to say. */
  message: string | null;
  /** The entry the running or followed job belongs to, while it runs. */
  activeEntryId: string | null;
  setInput: (input: PageInput | null) => void;
  /** The page shows this entry's output now. */
  setLoaded: (target: WorkbenchTarget, output: PageOutput | null) => void;
  /** The page shows an output that is no entry (a file); the loaded target is dropped. */
  setLocalOutput: (output: PageOutput | null) => void;
  /** The loaded entry is gone or unreadable: the page shows nothing of it any more. */
  clearLoaded: (message: string | null) => void;
  setStatus: (status: PageStatus, message?: string | null, activeEntryId?: string | null) => void;
}

/** Fields written to local storage. `migratePageState` must return this shape. */
export type PersistedPageState = Pick<PageState, "input" | "loaded" | "output">;

export const PAGE_STORE_VERSION = 1;

export function pageStorageKey(page: WorkbenchPage): string {
  return `scenegems:workbench-page:${page}`;
}

const EMPTY: PersistedPageState = { input: null, loaded: null, output: null };

const LEGACY_TRAJECTORY_STORE_KEY = "scenegems:trajectory-generation";

function readJson(storage: Pick<Storage, "getItem"> | null, key: string): unknown {
  if (storage === null) {
    return null;
  }
  try {
    const raw = storage.getItem(key);
    return raw === null ? null : (JSON.parse(raw) as unknown);
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The state a page starts with when nothing of its own was stored yet: before Phase 6 the
 * trajectory page kept its initial scene in the trajectory generation store, without saying
 * more than a file name; that scene becomes the page's input.
 */
export function legacyPageState(page: WorkbenchPage, storage: Pick<Storage, "getItem"> | null): PersistedPageState {
  if (page !== "trajectoryGeneration") {
    return EMPTY;
  }
  const legacy = readJson(storage, LEGACY_TRAJECTORY_STORE_KEY);
  const state = isRecord(legacy) && isRecord(legacy.state) ? legacy.state : null;
  if (state === null || !isRecord(state.handoffScene)) {
    return EMPTY;
  }
  const fileName = typeof state.handoffSourceName === "string" && state.handoffSourceName.length > 0 ? state.handoffSourceName : null;
  return {
    ...EMPTY,
    input: fileName
      ? { label: fileName, origin: "file", ref: null, source: { file: fileName } }
      : { label: "The scene of the Scene Generation page", origin: "previous_page", ref: null, source: { file: "scene_generation.json" } },
  };
}

function isTarget(value: unknown): value is WorkbenchTarget {
  return isRecord(value) && typeof value.campaignId === "string" && typeof value.caseId === "number" && typeof value.page === "string" && typeof value.step === "string";
}

/** Older stored blobs to the current shape: unknown fields are dropped, a malformed field is reset. */
export function migratePageState(persisted: unknown, version: number): PersistedPageState {
  void version;
  if (!isRecord(persisted)) {
    return EMPTY;
  }
  const loaded = isTarget(persisted.loaded) ? { ...persisted.loaded, live: undefined } : null;
  const input = isRecord(persisted.input) && typeof persisted.input.label === "string" && isRecord(persisted.input.source) ? (persisted.input as unknown as PageInput) : null;
  const output = isRecord(persisted.output) && typeof persisted.output.label === "string" && isRecord(persisted.output.source) ? (persisted.output as unknown as PageOutput) : null;
  return { input, loaded, output };
}

function browserStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function createPageStore(page: WorkbenchPage, storage: () => Storage | null = browserStorage) {
  return create<PageState>()(
    persist(
      (set) => ({
        ...legacyPageState(page, storage()),
        status: "idle",
        message: null,
        activeEntryId: null,
        setInput: (input) => set({ input }),
        setLoaded: (target, output) => set({ loaded: { ...target, live: undefined }, output, status: "shown", message: null, activeEntryId: null }),
        setLocalOutput: (output) => set({ loaded: null, output, status: output === null ? "idle" : "shown", message: null }),
        clearLoaded: (message) => set({ loaded: null, output: null, status: message === null ? "idle" : "failed", message, activeEntryId: null }),
        setStatus: (status, message = null, activeEntryId) =>
          set((state) => ({ status, message, activeEntryId: activeEntryId === undefined ? state.activeEntryId : activeEntryId })),
      }),
      {
        name: pageStorageKey(page),
        version: PAGE_STORE_VERSION,
        storage: createJSONStorage(() => storage() ?? undefinedStorage),
        partialize: (state): PersistedPageState => ({ input: state.input, loaded: state.loaded, output: state.output }),
        migrate: migratePageState,
      }
    )
  );
}

/** Storage that keeps nothing, where the browser has none (tests, server rendering). */
const undefinedStorage: Storage = {
  length: 0,
  clear: () => undefined,
  getItem: () => null,
  key: () => null,
  removeItem: () => undefined,
  setItem: () => undefined,
};

export type PageStore = ReturnType<typeof createPageStore>;

export const useExplorationPageStore = createPageStore("designSpaceExploration");
export const useScenePageStore = createPageStore("sceneGeneration");
export const useTrajectoryPageStore = createPageStore("trajectoryGeneration");
export const useSimulationPageStore = createPageStore("simulation");

export const PAGE_STORES: Record<WorkbenchPage, PageStore> = {
  designSpaceExploration: useExplorationPageStore,
  sceneGeneration: useScenePageStore,
  trajectoryGeneration: useTrajectoryPageStore,
  simulation: useSimulationPageStore,
};

/** The input a page takes in one click from the previous page's output; null when that page shows nothing usable. */
export function inputFromPreviousPage(output: PageOutput | null): PageInput | null {
  if (output === null) {
    return null;
  }
  return { label: output.label, origin: "previous_page", ref: output.ref, source: output.source };
}
