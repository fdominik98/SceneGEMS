import { create } from "zustand";
import { selectSelectedCluster, useClusterStore } from "./clusterStore";
import type { CampaignStep } from "./schemas";
import {
  clampPage,
  DEFAULT_PAGE_SIZE,
  DEFAULT_VERDICT_FILTERS,
  type SortDirection,
  type VerdictFilterState,
  type VerdictSort,
} from "./resultsApi";

/**
 * What the Results section shows: the entry (a campaign or a workbench run, `campaignId`), the
 * step view that was picked, the verdict table's filters and page, and the case page that is open. Kept in memory (not persisted): a reload starts at the newest campaign.
 * Other sections open a campaign's results with `openCampaign` (or `openCase`) and then show
 * the section (`features/results/showResults.ts`). The entry belongs to the cluster selected when it
 * was opened: the section is not mounted while hidden, so it reads it with `selectShownEntry`.
 */
export interface ResultsState {
  /** The cluster the entry belongs to; an entry of another cluster is not shown. */
  clusterId: string | null;
  campaignId: string | null;
  /** The step view the user picked; null shows the last step the entry executed. */
  step: CampaignStep | null;
  /** The case page that is open, or null for the verdict table. */
  caseId: number | null;
  filters: VerdictFilterState;
  /** Zero based. */
  page: number;
  pageSize: number;
  direction: SortDirection;
  /** The column the verdict table is sorted by (a master of Phase 7 sorts; an older one keeps the FEC order). */
  sort: VerdictSort;
  /** Shows an entry's results with no filters, on `step` when given (the entry's last step otherwise). */
  openCampaign: (campaignId: string, step?: CampaignStep) => void;
  /** Shows one case of an entry (its page). */
  openCase: (campaignId: string, caseId: number, step?: CampaignStep) => void;
  /** Picks the step view; the filters and the page start over. */
  setStep: (step: CampaignStep) => void;
  /** Back from the case page to the table. */
  closeCase: () => void;
  /** A filter change returns to the first page. */
  setFilters: (changes: Partial<VerdictFilterState>) => void;
  resetFilters: () => void;
  setPage: (page: number, total?: number | null) => void;
  setPageSize: (pageSize: number) => void;
  setDirection: (direction: SortDirection) => void;
  /** Sorts by a column: the same column again flips the direction, another one starts ascending; back to the first page. */
  sortBy: (sort: VerdictSort) => void;
  /** Forgets the campaign (the selected cluster changed). */
  reset: () => void;
}

const INITIAL = {
  clusterId: null,
  campaignId: null,
  step: null,
  caseId: null,
  filters: DEFAULT_VERDICT_FILTERS,
  page: 0,
  pageSize: DEFAULT_PAGE_SIZE,
  direction: "asc" as SortDirection,
  sort: "fec_id" as VerdictSort,
};

/** The cluster an entry opened now belongs to: the selected one, as every section works on it. */
function selectedClusterId(): string | null {
  return selectSelectedCluster(useClusterStore.getState())?.id ?? null;
}

export const useResultsStore = create<ResultsState>()((set, get) => ({
  ...INITIAL,
  openCampaign: (campaignId, step) => {
    const state = get();
    const clusterId = selectedClusterId();
    const same = state.campaignId === campaignId && state.clusterId === clusterId;
    if (same && state.caseId === null && (step === undefined || step === state.step)) {
      return;
    }
    set({ clusterId, campaignId, step: step ?? (same ? state.step : null), caseId: null, filters: DEFAULT_VERDICT_FILTERS, page: 0 });
  },
  openCase: (campaignId, caseId, step) => {
    const state = get();
    const clusterId = selectedClusterId();
    if (state.campaignId === campaignId && state.clusterId === clusterId) {
      set({ caseId, step: step ?? state.step });
    } else {
      set({ clusterId, campaignId, step: step ?? null, caseId, filters: DEFAULT_VERDICT_FILTERS, page: 0 });
    }
  },
  setStep: (step) => set({ step, caseId: null, filters: DEFAULT_VERDICT_FILTERS, page: 0 }),
  closeCase: () => set({ caseId: null }),
  setFilters: (changes) => set((state) => ({ filters: { ...state.filters, ...changes }, page: 0 })),
  resetFilters: () => set({ filters: DEFAULT_VERDICT_FILTERS, page: 0 }),
  setPage: (page, total) =>
    set((state) => ({ page: total === undefined || total === null ? Math.max(0, page) : clampPage(page, total, state.pageSize) })),
  setPageSize: (pageSize) => set({ pageSize, page: 0 }),
  setDirection: (direction) => set({ direction, page: 0 }),
  sortBy: (sort) =>
    set((state) => (state.sort === sort ? { direction: state.direction === "asc" ? "desc" : "asc", page: 0 } : { sort, direction: "asc", page: 0 })),
  reset: () => set({ ...INITIAL }),
}));

/** Whether the store's entry belongs to the selected cluster (a cluster switch made while the section was hidden leaves one that does not). */
export function isShownCluster(state: Pick<ResultsState, "clusterId" | "campaignId">, clusterId: string | null): boolean {
  return state.campaignId === null || state.clusterId === clusterId;
}

/** The entry to show for the selected cluster, or null (the section then shows the newest entry). */
export function selectShownEntry(state: Pick<ResultsState, "clusterId" | "campaignId">, clusterId: string | null): string | null {
  return isShownCluster(state, clusterId) ? state.campaignId : null;
}
