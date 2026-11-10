import { Disclosure } from "../../components/Disclosure";
import { hasActiveFilters, runIndexesOf, type SensitiveFilter, type VerdictFilterState } from "../../domain/cluster/resultsApi";
import type { CampaignDetail, VerdictState } from "../../domain/cluster/schemas";

interface VerdictFilterBarProps {
  detail: CampaignDetail | undefined;
  filters: VerdictFilterState;
  onChange: (changes: Partial<VerdictFilterState>) => void;
  onReset: () => void;
  /** The CSV download of the filtered set. */
  csvUrl: string | null;
  total: number | null;
  /** The run filter: only the simulation step has more than run 0. */
  showRun: boolean;
}

export function VerdictFilterBar({ detail, filters, onChange, onReset, csvUrl, total, showRun }: VerdictFilterBarProps) {
  const classes = (detail?.fecs ?? []).map((view) => view.fec_id).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const runs = runIndexesOf(detail);
  const active = hasActiveFilters(filters);
  const activeCount =
    (filters.classId !== "" ? 1 : 0) +
    (filters.state !== "any" ? 1 : 0) +
    (filters.runIndex !== null ? 1 : 0) +
    (filters.sensitive !== "any" ? 1 : 0);
  return (
    <div className="results-filters-wrap">
      <div className="results-filters-head">
        <span className="meta">{total !== null ? `${total} ${total === 1 ? "monitor result summary" : "monitor result summaries"}${active ? " match the filters" : ""}` : "Loading the monitor result summaries"}</span>
        {csvUrl ? (
          <a className="results-csv" href={csvUrl} download title="Every monitor result summary the filters match, as CSV, in the table's columns plus the case id">
            Download CSV{total !== null ? ` (${total})` : ""}
          </a>
        ) : (
          <span className="meta">CSV unavailable</span>
        )}
      </div>
      <Disclosure
        id="results:filters"
        title="Filters"
        hint={activeCount > 0 ? `${activeCount} active` : "none, showing every monitor result summary"}
        forceOpen={active}
        headingLevel={3}
      >
    <section className="results-filters" aria-label="Filters">
      <label className="results-field results-field--wide">
        <span>FEC</span>
        <select value={filters.classId} onChange={(event) => onChange({ classId: event.target.value })}>
          <option value="">All FECs ({classes.length})</option>
          {filters.classId !== "" && !classes.includes(filters.classId) && <option value={filters.classId}>{filters.classId}</option>}
          {classes.map((classId) => (
            <option key={classId} value={classId}>
              {classId}
            </option>
          ))}
        </select>
      </label>
      <label className="results-field">
        <span>Monitor result summary</span>
        <select value={filters.state} onChange={(event) => onChange({ state: event.target.value as VerdictState | "any" })}>
          <option value="any">Any</option>
          <option value="passed">Passed</option>
          <option value="failed">Failed</option>
          <option value="unmonitored">Unmonitored</option>
        </select>
      </label>
      {showRun && (
      <label className="results-field">
        <span>Run</span>
        <select value={filters.runIndex === null ? "" : String(filters.runIndex)} onChange={(event) => onChange({ runIndex: event.target.value === "" ? null : Number(event.target.value) })}>
          <option value="">Any</option>
          {filters.runIndex !== null && !runs.includes(filters.runIndex) && <option value={filters.runIndex}>run {filters.runIndex}</option>}
          {runs.map((run) => (
            <option key={run} value={run}>
              run {run}
            </option>
          ))}
        </select>
      </label>
      )}
      <label className="results-field">
        <span>Sensitive</span>
        <select value={filters.sensitive} onChange={(event) => onChange({ sensitive: event.target.value as SensitiveFilter })}>
          <option value="any">Any</option>
          <option value="yes">Only sensitive</option>
          <option value="no">Not sensitive</option>
        </select>
      </label>
      <div className="results-filter-actions">
        <button type="button" onClick={onReset} disabled={!active}>
          Clear filters
        </button>
      </div>
    </section>
      </Disclosure>
    </div>
  );
}
