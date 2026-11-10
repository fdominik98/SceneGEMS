import "./pages.css";
import type { PageStore } from "./pageStore";
import { useStore } from "zustand";
import { showHistoryEntry } from "../../history/showHistory";

import { shortEntryId } from "./entryLabels";

function EntryLink({ campaignId }: { campaignId: string }) {
  return (
    <button type="button" className="link-btn" title={`Open entry ${campaignId} in Campaign History`} onClick={() => showHistoryEntry(campaignId)}>
      entry {shortEntryId(campaignId)}
    </button>
  );
}

/**
 * What a page shows of its entries, as one line of its Result row: the latest loaded entry (a
 * link to it in Campaign History), a run or a followed entry in progress, or why the page is
 * empty (a deleted entry, a failed load).
 */
export function PageEntryStatus({ store }: { store: PageStore }) {
  const loaded = useStore(store, (s) => s.loaded);
  const status = useStore(store, (s) => s.status);
  const message = useStore(store, (s) => s.message);
  const activeEntryId = useStore(store, (s) => s.activeEntryId);

  if (status === "failed" && message) {
    return (
      <p className="step-line error page-entry-status" role="alert">
        {message}
      </p>
    );
  }
  if ((status === "running" || status === "following" || status === "loading") && (message || activeEntryId)) {
    return (
      <p className="step-line page-entry-status" role="status">
        {message ?? "Running"}
        {activeEntryId ? (
          <>
            {" "}
            <EntryLink campaignId={activeEntryId} />
          </>
        ) : null}
      </p>
    );
  }
  if (loaded !== null) {
    return (
      <p className="step-line page-entry-status">
        {loaded.step === "design_space_exploration" ? "The exploration" : loaded.caseIndex !== undefined ? `Case ${loaded.caseIndex + 1}` : "A case"}
        {loaded.runRecordId !== undefined ? `, run record ${loaded.runRecordId}` : ""} of <EntryLink campaignId={loaded.campaignId} />
      </p>
    );
  }
  return message ? <p className="step-line page-entry-status">{message}</p> : null;
}
