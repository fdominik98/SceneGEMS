import { create } from "zustand";
import { useUiStore, type WorkbenchView } from "../../../app/uiStore";

/**
 * The pinned console contract of Phase 6 (design doc 6.6): how Campaign History and the live view
 * of an ongoing entry open an output on the workbench page of its subsystem. `openInWorkbench`
 * shows the page and queues the target for it; the page (P6.9) takes it with `takeTarget(page)`
 * when it mounts or when a target is queued, and loads or follows it from there.
 */

export type WorkbenchPage = "sceneGeneration" | "trajectoryGeneration" | "simulation";

export interface WorkbenchTarget {
  page: WorkbenchPage;
  campaignId: string;
  caseId: number;
  step: "scene_generation" | "trajectory_generation" | "simulation";
  /** Simulation outputs. */
  runRecordId?: number;
  /** The case's index in its class (0-based), for labels; `caseId` is the master's database id. Absent on targets stored before it. */
  caseIndex?: number;
  /** Follow the running job instead of loading the finished output. */
  live?: boolean;
}

/** The workbench view that shows each page: the page ids are the view ids of `uiStore`. */
export const WORKBENCH_VIEW_OF_PAGE: Record<WorkbenchPage, WorkbenchView> = {
  sceneGeneration: "sceneGeneration",
  trajectoryGeneration: "trajectoryGeneration",
  simulation: "simulation",
};

/** The page an output of a step belongs on. */
export const WORKBENCH_PAGE_OF_STEP: Record<WorkbenchTarget["step"], WorkbenchPage> = {
  scene_generation: "sceneGeneration",
  trajectory_generation: "trajectoryGeneration",
  simulation: "simulation",
};

interface WorkbenchTargetState {
  /** The queued target of each page; a newer one replaces an older one that was not taken. */
  pending: Partial<Record<WorkbenchPage, WorkbenchTarget>>;
  queue: (target: WorkbenchTarget) => void;
  /** Returns the page's queued target and clears it, or undefined when there is none. */
  take: (page: WorkbenchPage) => WorkbenchTarget | undefined;
}

/** Not persisted: a queued target is consumed by the page that is shown, and must not replay after a reload. */
export const useWorkbenchTargetStore = create<WorkbenchTargetState>()((set, get) => ({
  pending: {},
  queue: (target) => set((state) => ({ pending: { ...state.pending, [target.page]: target } })),
  take: (page) => {
    const target = get().pending[page];
    if (target === undefined) {
      return undefined;
    }
    set((state) => {
      const { [page]: _taken, ...rest } = state.pending;
      void _taken;
      return { pending: rest };
    });
    return target;
  },
}));

/** Shows the workbench section on the target's page and queues the target for it. */
export function openInWorkbench(target: WorkbenchTarget): void {
  useWorkbenchTargetStore.getState().queue(target);
  const ui = useUiStore.getState();
  ui.setWorkbenchView(WORKBENCH_VIEW_OF_PAGE[target.page]);
  ui.setSection("workbench");
}

/** The page's queued target and clears it (P6.9 calls this to consume what `openInWorkbench` queued). */
export function takeTarget(page: WorkbenchPage): WorkbenchTarget | undefined {
  return useWorkbenchTargetStore.getState().take(page);
}

/** Selector for a page to react to a target queued while it is already shown: `useWorkbenchTargetStore((s) => selectPendingTarget(s, page))`. */
export function selectPendingTarget(state: Pick<WorkbenchTargetState, "pending">, page: WorkbenchPage): WorkbenchTarget | undefined {
  return state.pending[page];
}
