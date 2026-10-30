import type { Verdict } from "../../domain/cluster/schemas";
import { clampPage, describeRange, pageCount, PAGE_SIZES, splitFailedRule, type SortDirection, type VerdictPaging } from "../../domain/cluster/resultsApi";
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
  onDirection: (direction: SortDirection) => void;
}

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

export function VerdictTable({ verdicts, total, paging, loading, onOpenCase, onPage, onPageSize, onDirection }: VerdictTableProps) {
  const known = total ?? verdicts.length;
  const pages = pageCount(known, paging.pageSize);
  const page = clampPage(paging.page, known, paging.pageSize);
  const next: SortDirection = paging.direction === "asc" ? "desc" : "asc";
  const ariaSort = paging.direction === "asc" ? "ascending" : "descending";
  const orderHint = `Ordered by FEC, case and run, ${paging.direction === "asc" ? "ascending" : "descending"}. Select to ${next === "asc" ? "ascend" : "descend"}.`;
  const sortHeader = (label: string) => (
    <button type="button" className="results-sort" onClick={() => onDirection(next)} title={orderHint}>
      {label}
      <span aria-hidden="true">{paging.direction === "asc" ? " ▲" : " ▼"}</span>
    </button>
  );

  return (
    <section className="results-panel" aria-label="Verdicts">
      <div className="results-table-wrap results-table-wrap--tall">
        <table className="results-table" aria-busy={loading}>
          <thead>
            <tr>
              <th aria-sort={ariaSort}>{sortHeader("FEC")}</th>
              <th aria-sort={ariaSort}>{sortHeader("Case")}</th>
              <th aria-sort={ariaSort}>{sortHeader("Run")}</th>
              <th>State</th>
              <th>Monitor</th>
              <th>Failed rules</th>
              <th>First failure</th>
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
