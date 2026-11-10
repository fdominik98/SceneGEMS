import { useState } from "react";
import type { CampaignSummary } from "../../domain/cluster/schemas";
import { canDelete, deleteRefusal } from "./historyModel";
import { useDeleteEntry } from "./useHistoryData";

export interface DeleteEntryProps {
  entry: Pick<CampaignSummary, "campaign_id" | "name" | "actual_state">;
  onDeleted?: () => void;
  /** A small button for a table row. */
  compact?: boolean;
}

/**
 * Deletes a final entry after a confirmation. A running entry has to be stopped first; the
 * button says so instead of asking, and the control node's 409 says the same if the state changed.
 */
export function DeleteEntry({ entry, onDeleted = () => {}, compact = false }: DeleteEntryProps) {
  const [confirming, setConfirming] = useState(false);
  const mutation = useDeleteEntry(entry.campaign_id, onDeleted);
  const allowed = canDelete(entry);

  return (
    <span className={`history-delete${compact ? " history-delete--compact" : ""}`} onClick={(event) => event.stopPropagation()}>
      {!confirming && (
        <button
          type="button"
          className="history-delete-btn"
          disabled={!allowed || mutation.isPending}
          title={allowed ? "Delete the entry, its cases and outputs" : "Only a finished entry can be deleted: stop it first"}
          onClick={() => {
            mutation.reset();
            setConfirming(true);
          }}
        >
          {mutation.isPending ? "Deleting..." : "Delete"}
        </button>
      )}
      {confirming && (
        <span className="history-delete-confirm" role="alertdialog" aria-label={`Delete ${entry.name}`}>
          <span>
            <strong>Delete {entry.name}?</strong> Its outputs are freed unless another entry uses them.
          </span>
          <button
            type="button"
            className="camp-control-btn camp-control-btn--danger"
            onClick={() => {
              setConfirming(false);
              mutation.mutate();
            }}
          >
            Delete the entry
          </button>
          <button type="button" onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </span>
      )}
      {mutation.isError && (
        <span className="history-delete-error" role="alert">
          {deleteRefusal(mutation.error)}
        </span>
      )}
    </span>
  );
}
