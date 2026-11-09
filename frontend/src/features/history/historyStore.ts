import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { CampaignStep } from "../../domain/cluster/schemas";
import { INITIAL_LIST_VIEW, listViewReducer, type ListViewAction, type ListViewState } from "./campaignModel";

/**
 * What Campaign History shows: the list, or one entry of a cluster with the step tab it shows.
 * Persisted per browser (`scenegems:history-view`), so a reload comes back to the same entry.
 * The list's filters and page are kept in memory only, so Back from an entry returns to the same view.
 * Other sections open an entry with `showHistoryEntry` (`showHistory.ts`).
 */
export interface HistoryViewState {
  /** The cluster the open entry belongs to; an entry of another cluster is not shown. */
  clusterId: string | null;
  /** The open entry, or null for the list. */
  entryId: string | null;
  /** The step tab of the open entry. */
  step: CampaignStep | null;
  openEntry: (clusterId: string | null, entryId: string) => void;
  closeEntry: () => void;
  setStep: (step: CampaignStep) => void;
  /** The list's filters and page (not persisted). */
  listView: ListViewState;
  updateListView: (action: ListViewAction) => void;
}

export const useHistoryStore = create<HistoryViewState>()(
  persist(
    (set) => ({
      clusterId: null,
      entryId: null,
      step: null,
      openEntry: (clusterId, entryId) => set((state) => (state.clusterId === clusterId && state.entryId === entryId ? state : { clusterId, entryId, step: null })),
      closeEntry: () => set({ entryId: null, step: null }),
      setStep: (step) => set({ step }),
      listView: INITIAL_LIST_VIEW,
      updateListView: (action) =>
        set((state) => {
          const listView = listViewReducer(state.listView, action);
          return listView === state.listView ? state : { listView };
        }),
    }),
    {
      name: "scenegems:history-view",
      version: 1,
      partialize: (state) => ({ clusterId: state.clusterId, entryId: state.entryId, step: state.step }),
    }
  )
);

/** The entry to show for the selected cluster, or null for the list. */
export function selectOpenEntry(state: Pick<HistoryViewState, "clusterId" | "entryId">, clusterId: string | null): string | null {
  return state.entryId !== null && state.clusterId === clusterId ? state.entryId : null;
}
