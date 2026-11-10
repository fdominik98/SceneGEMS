import { useState } from "react";
import type { OutputRow } from "../../domain/cluster/historyApi";
import { describeOperatorError, OperatorApiError } from "../../domain/cluster/operatorApi";
import { plural } from "../campaigns/campaignFormat";
import { useOperatorClient } from "../campaigns/useCampaignData";
import { artifactText } from "../workbench/pages/inputSpecification";
import { sendToScenePage } from "../workbench/pages/sceneSpecificationHandoff";
import { openInWorkbench } from "../workbench/pages/workbenchTarget";
import { EmptyState } from "./campaignParts";
import { OUTPUT_PAGE_SIZE, outputTarget } from "./historyModel";
import { useStepOutputs } from "./useHistoryData";

const STEP = "design_space_exploration";

function count(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

/**
 * The explored FECs of an entry that ran the design space exploration: per FEC its id, vessels and
 * obstacles, the way onto the exploration page (with the FEC selected) and onto the scene page (its
 * text in the specification editor). The step has no monitor, so there are no findings to show.
 */
export function ExploredFecOutputs({ campaignId, running }: { campaignId: string; running: boolean }) {
  const client = useOperatorClient();
  const [page, setPage] = useState(0);
  const query = useStepOutputs(campaignId, STEP, page, running);
  const total = query.data?.total ?? null;
  const rows = query.data?.items ?? [];

  if (query.isLoading) {
    return (
      <p className="meta" role="status">
        Loading the FECs...
      </p>
    );
  }
  if (query.error && !query.data) {
    const missing = query.error instanceof OperatorApiError && query.error.status === 404;
    return (
      <EmptyState title={missing ? "This master lists no outputs" : "The FECs did not load"} tone="error">
        <p className="meta">{missing ? "Update the master to browse the FECs of an exploration." : describeOperatorError(query.error)}</p>
        <div>
          <button type="button" onClick={() => void query.refetch()} disabled={query.isFetching}>
            Try again
          </button>
        </div>
      </EmptyState>
    );
  }
  if (rows.length === 0) {
    return (
      <EmptyState title="No FECs yet">
        <p className="meta">{running ? "They appear here once the exploration has ended." : "The exploration found no FEC."}</p>
      </EmptyState>
    );
  }

  const known = total ?? page * OUTPUT_PAGE_SIZE + rows.length;
  const pages = Math.max(1, Math.ceil(known / OUTPUT_PAGE_SIZE));
  const toScenePage = (row: OutputRow) => {
    const artifact = row.artifact;
    if (client === null || artifact === null) {
      return;
    }
    sendToScenePage({ label: row.fec_id, text: () => artifactText(client, artifact.sha256) });
  };
  return (
    <div className="history-outputs">
      {query.error ? <p className="meta warning">The FECs may be stale: {describeOperatorError(query.error)}</p> : null}
      <div className="camp-table-wrap">
        <table className="camp-table camp-table--dense">
          <thead>
            <tr>
              <th>FEC</th>
              <th>Vessels</th>
              <th>Obstacles</th>
              <th>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.fec_id}>
                <td>
                  <span className="camp-class-name mono">{row.fec_id}</span>
                </td>
                <td className="camp-num">{count(row.vessel_count)}</td>
                <td className="camp-num">{count(row.obstacle_count)}</td>
                <td className="history-cell-actions">
                  <button type="button" onClick={() => openInWorkbench(outputTarget(campaignId, STEP, row))} title="Show the exploration on the Design Space Exploration page with this FEC selected">
                    Open in workbench
                  </button>
                  <button type="button" disabled={row.artifact === null || client === null} onClick={() => toScenePage(row)} title="Put this FEC into the Scene Generation page's editor">
                    To scene generation
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="camp-paging">
        <span className="meta">
          {page * OUTPUT_PAGE_SIZE + 1} to {page * OUTPUT_PAGE_SIZE + rows.length} of {plural(known, "FEC")}
        </span>
        <span className="camp-paging-controls">
          <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}>
            Previous
          </button>
          <span className="meta">
            Page {page + 1} of {pages}
          </span>
          <button type="button" disabled={(page + 1) * OUTPUT_PAGE_SIZE >= known} onClick={() => setPage(page + 1)}>
            Next
          </button>
        </span>
      </div>
    </div>
  );
}
