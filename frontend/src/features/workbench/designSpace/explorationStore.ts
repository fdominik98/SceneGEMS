import { create } from "zustand";
import type { ExplorationResult, ExploredFec } from "../../../domain/designSpace/explorationResult";

/**
 * What the design space exploration page shows: the running job's status, then the result and the
 * explored FECs of the loaded entry, with the texts fetched so far and the selected FEC. Not
 * persisted: the page store keeps the loaded entry, and the page fetches it again on start.
 */

export interface ExplorationProgress {
  /** The job's latest status message ("generating models: 17 of at most 100 found after 4.2 s"), null before it reported one. */
  message: string | null;
  /** 0 to 1, null while it generates without a cap. */
  progress: number | null;
}

export interface ExplorationState {
  /** The running job's status, null while nothing runs. */
  running: ExplorationProgress | null;
  /** The entry the shown FECs belong to, null while nothing is shown. */
  campaignId: string | null;
  /** The job's result, null when the control node did not report one. */
  result: ExplorationResult | null;
  fecs: ExploredFec[];
  /** Texts fetched so far, by FEC id. */
  texts: Record<string, string>;
  /** Why a text could not be fetched, by FEC id. */
  textErrors: Record<string, string>;
  loadingTexts: Record<string, true>;
  selectedFecId: string | null;
  setRunning: (progress: ExplorationProgress | null) => void;
  show: (shown: { campaignId: string; result: ExplorationResult | null; fecs: ExploredFec[]; selectedFecId?: string | null }) => void;
  select: (fecId: string | null) => void;
  textLoading: (fecId: string) => void;
  textLoaded: (fecId: string, text: string) => void;
  textFailed: (fecId: string, message: string) => void;
  clear: () => void;
}

const EMPTY = {
  running: null,
  campaignId: null,
  result: null,
  fecs: [],
  texts: {},
  textErrors: {},
  loadingTexts: {},
  selectedFecId: null,
} satisfies Partial<ExplorationState>;

function without<T>(record: Record<string, T>, key: string): Record<string, T> {
  if (!(key in record)) {
    return record;
  }
  const { [key]: _removed, ...rest } = record;
  void _removed;
  return rest;
}

export const useExplorationStore = create<ExplorationState>()((set) => ({
  ...EMPTY,
  setRunning: (running) => set({ running }),
  show: ({ campaignId, result, fecs, selectedFecId = null }) =>
    set((state) => {
      // The texts of the same entry stay: an entry's FECs do not change once it explored them.
      const same = state.campaignId === campaignId;
      const selected = selectedFecId !== null && fecs.some((fec) => fec.fecId === selectedFecId) ? selectedFecId : same && fecs.some((fec) => fec.fecId === state.selectedFecId) ? state.selectedFecId : null;
      return {
        running: null,
        campaignId,
        result,
        fecs,
        texts: same ? state.texts : {},
        textErrors: same ? state.textErrors : {},
        loadingTexts: same ? state.loadingTexts : {},
        selectedFecId: selected,
      };
    }),
  select: (selectedFecId) => set({ selectedFecId }),
  textLoading: (fecId) => set((state) => ({ loadingTexts: { ...state.loadingTexts, [fecId]: true }, textErrors: without(state.textErrors, fecId) })),
  textLoaded: (fecId, text) => set((state) => ({ texts: { ...state.texts, [fecId]: text }, loadingTexts: without(state.loadingTexts, fecId) })),
  textFailed: (fecId, message) => set((state) => ({ textErrors: { ...state.textErrors, [fecId]: message }, loadingTexts: without(state.loadingTexts, fecId) })),
  clear: () => set({ ...EMPTY }),
}));

/** The FEC the page hands to the scene page: the selected one, else the first. */
export function handoffFec(state: Pick<ExplorationState, "fecs" | "selectedFecId">): ExploredFec | null {
  return state.fecs.find((fec) => fec.fecId === state.selectedFecId) ?? state.fecs[0] ?? null;
}
