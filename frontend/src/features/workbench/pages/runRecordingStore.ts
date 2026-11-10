import { create } from "zustand";
import type { RunRecordingStatus } from "../../../domain/simulation/wireTypes";

/**
 * Whether the gateway records the live session as a workbench entry (design doc 6.4), from its
 * `run_recording` messages: recording while it runs, saved (with the entry) once the post-hoc
 * monitor has it, failed, or unavailable on a gateway without a control node.
 */

export interface RunRecordingState {
  status: RunRecordingStatus | null;
  campaignId: string | null;
  caseId: number | null;
  message: string | null;
  report: (recording: { status: RunRecordingStatus; campaignId: string | null; caseId: number | null; message: string | null }) => void;
  clear: () => void;
}

export const useRunRecordingStore = create<RunRecordingState>()((set) => ({
  status: null,
  campaignId: null,
  caseId: null,
  message: null,
  report: ({ status, campaignId, caseId, message }) =>
    set((state) => ({
      status,
      // A later message without ids (a failure report) keeps the entry it is about.
      campaignId: campaignId ?? (status === "unavailable" ? null : state.campaignId),
      caseId: caseId ?? (status === "unavailable" ? null : state.caseId),
      message,
    })),
  clear: () => set({ status: null, campaignId: null, caseId: null, message: null }),
}));
