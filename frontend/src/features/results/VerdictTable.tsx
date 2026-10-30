import type { Verdict } from "../../domain/cluster/schemas";
import { clampPage, describeRange, pageCount, PAGE_SIZES, splitFailedRule, type VerdictPaging, type VerdictSort } from "../../domain/cluster/resultsApi";
import { StateChip } from "./CaseParts";
import { formatSeconds, shortClassId } from "./resultsFormat";

interface VerdictTableProps {
  verdicts: Verdict[];
  total: number | null;
  paging: VerdictPaging;
  loading: boolean;
  onOpenCase: (verdict: Verdict) => void;
  onPage: (page: number) => void;
  onPageSize: (pageSize: number) => void;
  /** Whether the master sorts by any column; an older one has the FEC order only, which FEC, Case and Run flip together. */
  sortable: boolean;
  onSort: (sort: VerdictSort) => void;
}

const SORT_LABEL: Record<VerdictSort, string> = {
  fec_id: "FEC",
  case_index: "case",
  run_index: "run",
  state: "state",
  first_failure_time_s: "first failure",
  step: "step",
  created_at: "time",
};
/** The columns of the FEC order, the only order of a master before Phase 7. */
const FEC_ORDER: readonly VerdictSort[] = ["fec_id", "case_index", "run_index"];

/** The failed rules by name (a rule that failed for several vessel pairs shows once); the full text is the tooltip. */
function FailedRules({ rules }: { rules: string[] }) {
  if (rules.length === 0) {
    return <span className="meta">-</span>;
  }
  const names = [...new Set(rules.map((text) => splitFailedRule(text).rule))];
  const shown = names.slice(0, 2);
  return (
    <span className="results-rules" title={rules.join("\n")}>
      {shown.map((rule) => (
        <span key={rule} className="results-rule-chip">
          {rule}
        </span>
      ))}
      {names.length > shown.length && <span className="meta">+{names.length - shown.length}</span>}
    </span>
  );
}

export function VerdictTable({ verdicts, total, paging, loading, onOpenCase, onPage, onPageSize, sortable, onSort }: VerdictTableProps) {
  const known = total ?? verdicts.length;
  const pages = pageCount(known, paging.pageSize);
  const page = clampPage(paging.page, known, paging.pageSize);
  const ascending = paging.direction === "asc";
  const activeSort = paging.sort ?? "fec_id";
  const sortHeader = (key: VerdictSort, label: string) => {
    if (!sortable && !FEC_ORDER.includes(key)) {
      return label;
    }
    const active = sortable ? activeSort === key : true;
    const hint = active
      ? `Sorted by ${SORT_LABEL[sortable ? key : "fec_id"]}${sortable ? "" : ", case and run"}, ${ascending ? "ascending" : "descending"}. Select to ${ascending ? "descend" : "ascend"}.`
      : `Select to sort by ${SORT_LABEL[key]}.`;
    return (
      <button type="button" className="results-sort" onClick={() => onSort(key)} title={hint}>
        {label}
        {active && <span aria-hidden="true">{ascending ? " ▲" : " ▼"}</span>}
      </button>
    );
  };
  const ariaSort = (key: VerdictSort) => ((sortable ? activeSort === key : FEC_ORDER.includes(key)) ? (ascending ? "ascending" : "descending") : undefined);

  return (
    <section className="results-panel" aria-label="Verdicts">
      <div className="results-table-wrap results-table-wrap--tall">
        <table className="results-table" aria-busy={loading}>
          <thead>
            <tr>
              <th aria-sort={ariaSort("fec_id")}>{sortHeader("fec_id", "FEC")}</th>
              <th aria-sort={ariaSort("case_index")}>{sortHeader("case_index", "Case")}</th>
              <th aria-sort={ariaSort("run_index")}>{sortHeader("run_index", "Run")}</th>
              <th aria-sort={ariaSort("state")}>{sortHeader("state", "State")}</th>
              <th>Monitor</th>
              <th>Failed rules</th>
              <th aria-sort={ariaSort("first_failure_time_s")}>{sortHeader("first_failure_time_s", "First failure")}</th>
              <th>Early stop</th>
              <th>Sensitive</th>
            </tr>
          </thead>
          <tbody>
            {verdicts.length === 0 && (
              <tr>
                <td colSpan={9} className="results-empty-cell">
                  {loading ? "Loading the verdicts." : "No verdict matches the filters."}
                </td>
              </tr>
            )}
            {verdicts.map((verdict) => (
              <tr
                key={verdict.verdict_id}
                className={`results-row results-row--${verdict.state}`}
                onClick={() => onOpenCase(verdict)}
              >
                <td title={verdict.fec_id} className="results-class">
                  <button
                    type="button"
                    className="results-link"
                    onClick={(event) => {
                      event.stopPropagation();
                      onOpenCase(verdict);
                    }}
                  >
                    {shortClassId(verdict.fec_id, 38)}
                  </button>
                </td>
                <td className="mono">{verdict.case_index ?? `id ${verdict.case_id}`}</td>
                <td className="mono">{verdict.run_index}</td>
                <td>
                  <StateChip state={verdict.state} />
                </td>
                <td>{verdict.monitor}</td>
                <td>
                  <FailedRules rules={verdict.failed_rules} />
                </td>
                <td className="mono">{formatSeconds(verdict.first_failure_time_s)}</td>
                <td className="mono">{formatSeconds(verdict.early_stop_time_s)}</td>
                <td>{verdict.sensitive ? <span className="run-tag">sensitive</span> : <span className="meta">no</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <footer className="results-pager">
        <span className="meta" role="status">
          {total === null ? `${verdicts.length} shown (the master sent no total)` : describeRange(total, paging, verdicts.length)}
          {loading ? ", updating" : ""}
        </span>
        <span className="results-spacer" />
        <label className="results-inline-field">
          Rows
          <select value={paging.pageSize} onChange={(event) => onPageSize(Number(event.target.value))}>
            {PAGE_SIZES.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </select>
        </label>
        <button type="button" onClick={() => onPage(0)} disabled={page <= 0}>
          First
        </button>
        <button type="button" onClick={() => onPage(page - 1)} disabled={page <= 0}>
          Previous
        </button>
        <span className="meta">
          Page {page + 1} of {pages}
        </span>
        <button type="button" onClick={() => onPage(page + 1)} disabled={page >= pages - 1 || (total === null && verdicts.length < paging.pageSize)}>
          Next
        </button>
        <button type="button" onClick={() => onPage(pages - 1)} disabled={page >= pages - 1 || total === null}>
          Last
        </button>
      </footer>
    </section>
  );
}
