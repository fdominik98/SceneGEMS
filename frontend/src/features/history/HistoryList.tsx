import { useEffect, useState } from "react";
import { describeOperatorError, OperatorApiError } from "../../domain/cluster/operatorApi";
import { CAMPAIGN_STEPS, type CampaignKind, type CampaignRow, type CampaignStep } from "../../domain/cluster/schemas";
import { SSH_TUNNEL_COMMAND } from "../cluster/ClusterListPanel";
import { formatDateTime, plural } from "../campaigns/campaignFormat";
import { ACTUAL_STATES, ACTUAL_STATE_LABELS, LIST_PAGE_SIZES, pageInfo } from "./campaignModel";
import { EmptyState, StateBadge, ToneBadge } from "./campaignParts";
import { DeleteEntry } from "./DeleteEntry";
import { entryKind, entrySteps, KIND_LABELS, madeByLabel, rowTotalsSummary, STEP_LABELS, stepsLabel } from "./historyModel";
import { MadeFrom, VerdictChips } from "./historyParts";
import { useHistoryStore } from "./historyStore";
import { useHistoryList } from "./useHistoryData";

export interface HistoryListProps {
  onOpen: (campaignId: string) => void;
  clusterName: string;
  operatorUrl: string;
}

const KIND_FILTERS: { kind: CampaignKind | null; label: string }[] = [
  { kind: null, label: "All" },
  { kind: "campaign", label: "Campaigns" },
  { kind: "workbench", label: "Workbench runs" },
];

function EntryRow({ entry, names, onOpen }: { entry: CampaignRow; names: Map<string, string>; onOpen: (campaignId: string) => void }) {
  const kind = entryKind(entry);
  const steps = entrySteps(entry);
  const totals = rowTotalsSummary(entry.totals, steps);
  return (
    <tr className="camp-row" onClick={() => onOpen(entry.campaign_id)}>
      <td className="camp-cell-name">
        <button type="button" className="camp-link" onClick={() => onOpen(entry.campaign_id)}>
          {entry.name}
        </button>
        <span className="history-kind-line">
          <ToneBadge tone={kind === "campaign" ? "info" : "idle"}>{KIND_LABELS[kind]}</ToneBadge>
          <span className="meta">{madeByLabel(entry.origin)}</span>
        </span>
        {entry.state_reason && <span className="camp-reason">{entry.state_reason}</span>}
      </td>
      <td>{stepsLabel(steps)}</td>
      <td>
        <StateBadge state={entry.actual_state} desired={entry.desired_state} />
      </td>
      <td>
        <MadeFrom ids={entry.made_from ?? []} names={names} onOpen={onOpen} />
      </td>
      <td className="history-cell-totals">
        {totals.cases === null ? <span className="meta">not reported</span> : <span>{totals.cases}</span>}
        <VerdictChips lines={totals.verdicts} />
      </td>
      <td className="camp-cell-time">{formatDateTime(entry.created_at)}</td>
      <td className="history-cell-actions">
        <DeleteEntry entry={entry} compact />
      </td>
    </tr>
  );
}

/**
 * Every entry of the selected cluster, campaigns and workbench runs, newest first: kind, origin,
 * steps, state, made-from links, totals and creation time. Filters by kind, state, step and name;
 * kept live through the `campaigns` topic, polled while the topic is not live.
 */
export function HistoryList({ onOpen, clusterName, operatorUrl }: HistoryListProps) {
  // Kept in the store, so the filters and the page are still set after Back from an entry
  const view = useHistoryStore((state) => state.listView);
  const dispatch = useHistoryStore((state) => state.updateListView);
  const [search, setSearch] = useState(view.q ?? "");
  const { result, rows, total, liveStatus } = useHistoryList(view);

  useEffect(() => {
    const timer = setTimeout(() => dispatch({ type: "setQuery", q: search }), 300);
    return () => clearTimeout(timer);
  }, [search, dispatch]);

  useEffect(() => {
    if (total !== null) {
      dispatch({ type: "clampPage", total });
    }
  }, [total, dispatch]);

  const error = result.error;
  const unreachable = error instanceof OperatorApiError && error.unreachable;

  if (result.isLoading) {
    return <p className="meta" role="status">Loading the history...</p>;
  }
  if (error && !result.data) {
    return (
      <EmptyState title={unreachable ? `Cannot reach ${clusterName}` : "The history did not load"} tone="error">
        <p className="meta">{describeOperatorError(error)}</p>
        {unreachable && (
          <>
            <p className="meta">
              Check that the master runs and that its operator API is reachable at <code>{operatorUrl}</code>. For a remote master, open the tunnel first:
            </p>
            <code className="cluster-hint-command">{SSH_TUNNEL_COMMAND}</code>
          </>
        )}
        <div>
          <button type="button" onClick={() => void result.refetch()} disabled={result.isFetching}>
            {result.isFetching ? "Trying..." : "Try again"}
          </button>
        </div>
      </EmptyState>
    );
  }

  const fetched = result.data?.items.length ?? 0;
  const page = pageInfo(view, fetched, total);
  const filtered = view.states.length > 0 || Boolean(view.kind) || Boolean(view.step) || (view.q ?? "") !== "";
  const names = new Map(rows.map((row) => [row.campaign_id, row.name]));

  return (
    <div className="camp-list">
      <div className="history-filters">
        <div className="camp-filters" role="group" aria-label="Filter by kind">
          <span className="camp-filters-label">Kind</span>
          {KIND_FILTERS.map(({ kind, label }) => {
            const on = (view.kind ?? null) === kind;
            return (
              <button key={label} type="button" className={`camp-chip${on ? " camp-chip--on" : ""}`} aria-pressed={on} onClick={() => dispatch({ type: "setKind", kind })}>
                {label}
              </button>
            );
          })}
        </div>
        <div className="camp-filters" role="group" aria-label="Filter by state">
          <span className="camp-filters-label">State</span>
          <button type="button" className={`camp-chip${view.states.length === 0 ? " camp-chip--on" : ""}`} aria-pressed={view.states.length === 0} onClick={() => dispatch({ type: "clearStates" })}>
            All
          </button>
          {ACTUAL_STATES.map((state) => (
            <button
              key={state}
              type="button"
              className={`camp-chip${view.states.includes(state) ? " camp-chip--on" : ""}`}
              aria-pressed={view.states.includes(state)}
              onClick={() => dispatch({ type: "toggleState", state })}
            >
              {ACTUAL_STATE_LABELS[state]}
            </button>
          ))}
        </div>
        <div className="history-filter-fields">
          <label className="camp-inline-field">
            Step
            <select value={view.step ?? ""} onChange={(event) => dispatch({ type: "setStep", step: (event.target.value || null) as CampaignStep | null })}>
              <option value="">Any step</option>
              {CAMPAIGN_STEPS.map((step) => (
                <option key={step} value={step}>
                  {STEP_LABELS[step]}
                </option>
              ))}
            </select>
          </label>
          <label className="camp-inline-field history-search">
            Name
            <input type="search" value={search} placeholder="contains" onChange={(event) => setSearch(event.target.value)} />
          </label>
          <span className={`camp-badge camp-badge--${liveStatus === "live" ? "ok" : "warn"}`} title={liveStatus === "live" ? "Changes arrive over the live channel." : "The live channel is not delivering; the list is read every 4 s."}>
            {liveStatus === "live" ? "live" : "polling"}
          </span>
          {result.isFetching && !result.isLoading && <span className="meta camp-refreshing">updating</span>}
        </div>
      </div>
      {error ? <p className="meta warning">The list may be stale: {describeOperatorError(error)}</p> : null}
      {rows.length === 0 ? (
        <EmptyState title={filtered ? "No entry matches these filters" : "No entries yet"}>
          <p className="meta">
            {filtered
              ? view.step && fetched > 0
                ? "No entry on this page runs that step. Try the next page or clear the step."
                : "Clear the filters to see every entry of this cluster."
              : "Campaigns started in the Campaigns section and every run of the workbench appear here."}
          </p>
        </EmptyState>
      ) : (
        <div className="camp-table-wrap">
          <table className="camp-table history-table">
            <thead>
              <tr>
                <th>Entry</th>
                <th>Steps</th>
                <th>State</th>
                <th>Made from</th>
                <th>Totals</th>
                <th>Created</th>
                <th>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((entry) => (
                <EntryRow key={entry.campaign_id} entry={entry} names={names} onOpen={onOpen} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="camp-paging">
        <span className="meta">
          {page.total === 0 ? "No entries" : `${page.from} to ${page.to} of ${plural(page.total, "entry", "entries")}`}
          {view.step && rows.length < fetched ? `, ${rows.length} on this page run ${STEP_LABELS[view.step].toLowerCase()}` : ""}
        </span>
        <span className="camp-paging-controls">
          <label className="camp-inline-field">
            Per page
            <select value={view.pageSize} onChange={(event) => dispatch({ type: "setPageSize", pageSize: Number(event.target.value) })}>
              {LIST_PAGE_SIZES.map((size) => (
                <option key={size} value={size}>
                  {size}
                </option>
              ))}
            </select>
          </label>
          <button type="button" disabled={!page.hasPrevious} onClick={() => dispatch({ type: "setPage", page: view.page - 1 })}>
            Previous
          </button>
          <span className="meta">
            Page {view.page + 1} of {page.pages}
          </span>
          <button type="button" disabled={!page.hasNext} onClick={() => dispatch({ type: "setPage", page: view.page + 1 })}>
            Next
          </button>
        </span>
      </div>
    </div>
  );
}
