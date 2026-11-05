import { Disclosure } from "../../components/Disclosure";
import { percent, type VerdictSummary } from "../../domain/cluster/resultsApi";
import { formatSeconds } from "./resultsFormat";

interface VerdictSummaryPanelProps {
  summary: VerdictSummary | undefined;
  loading: boolean;
  /** Whether filters narrow the set the summary is about. */
  filtered: boolean;
}

function Tile({ label, count, whole, tone }: { label: string; count: number; whole: number; tone: "passed" | "failed" | "unmonitored" }) {
  return (
    <div className={`results-tile results-tile--${tone}`}>
      <span className="results-tile-label">{label}</span>
      <span className="results-tile-value">{count}</span>
      <span className="results-tile-detail">{whole > 0 ? `${percent(count, whole)} percent` : "none"}</span>
    </div>
  );
}

/** Verdict counts per run and state, and the failed rules ranked by the verdicts they failed in. */
export function VerdictSummaryPanel({ summary, loading, filtered }: VerdictSummaryPanelProps) {
  if (!summary) {
    return (
      <section className="results-panel" aria-label="Counts of the monitor summaries">
        <p className="meta" role="status">
          {loading ? "Counting the monitor summaries." : "No counts."}
        </p>
      </section>
    );
  }
  const whole = summary.analyzed;
  const mostFailures = Math.max(1, ...summary.failedRules.map((rule) => rule.verdicts));
  return (
    <section className="results-panel" aria-label="Counts of the monitor summaries">
      <header className="results-panel-head">
        <h3>Runs</h3>
        <span className="meta">
          {filtered ? "of the filtered monitor summaries" : "of all monitor summaries"}
          {summary.partial ? `: the first ${summary.analyzed} of ${summary.total}` : `: ${summary.analyzed}`}
          {summary.sensitive > 0 ? `, ${summary.sensitive} sensitive` : ""}
        </span>
        {loading && <span className="meta" role="status">updating</span>}
      </header>
      {summary.partial && (
        <p className="meta warning">The ranking and the counts below read the first {summary.analyzed} monitor summaries only; narrow the filters for an exact picture.</p>
      )}
      <div className="results-summary-grid">
        <div className="results-tiles">
          <Tile label="Passed" count={summary.byState.passed} whole={whole} tone="passed" />
          <Tile label="Failed" count={summary.byState.failed} whole={whole} tone="failed" />
          <Tile label="Unmonitored" count={summary.byState.unmonitored} whole={whole} tone="unmonitored" />
        </div>

        <Disclosure
          id="results:per-run"
          title="Counts per run"
          hint={`${summary.byRun.length} ${summary.byRun.length === 1 ? "run" : "runs"}`}
          variant="plain"
          headingLevel={4}
        >
          {summary.byRun.length === 0 ? (
            <p className="meta">No monitor summary matches.</p>
          ) : (
            <table className="results-table results-table--plain results-table--compact" aria-label="Monitor summary counts per run and state">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Passed</th>
                  <th>Failed</th>
                  <th>Unmonitored</th>
                  <th>Total</th>
                  <th aria-label="Share failed" />
                </tr>
              </thead>
              <tbody>
                {summary.byRun.map((run) => (
                  <tr key={run.runIndex}>
                    <td>run {run.runIndex}</td>
                    <td className="mono">{run.passed}</td>
                    <td className={`mono${run.failed > 0 ? " results-count-failed" : ""}`}>{run.failed}</td>
                    <td className="mono">{run.unmonitored}</td>
                    <td className="mono">{run.total}</td>
                    <td>
                      <span className="results-bar" title={`${percent(run.failed, run.total)} percent failed`}>
                        <span className="results-bar-fill results-bar-fill--failed" style={{ width: `${percent(run.failed, run.total)}%` }} />
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Disclosure>

        <Disclosure
          id="results:failed-rules"
          title="Which rules failed"
          hint={summary.failedRules.length === 0 ? "none" : `${summary.failedRules.length} ${summary.failedRules.length === 1 ? "rule" : "rules"}, most often first`}
          defaultOpen={summary.byState.failed > 0}
          variant="plain"
          headingLevel={4}
        >
          {summary.failedRules.length === 0 ? (
            <p className="meta">No rule failed in these monitor summaries.</p>
          ) : (
            <ol className="results-rules-rank">
              {summary.failedRules.slice(0, 8).map((rule) => (
                <li key={rule.rule} title={rule.relations.length > 0 ? `vessel pairs: ${rule.relations.join(", ")}` : undefined}>
                  <span className="results-rule-name">{rule.rule}</span>
                  <span className="results-bar">
                    <span className="results-bar-fill results-bar-fill--failed" style={{ width: `${(rule.verdicts / mostFailures) * 100}%` }} />
                  </span>
                  <span className="mono results-rule-count">{rule.verdicts}</span>
                  <span className="meta">earliest {formatSeconds(rule.earliestFailureS)}</span>
                </li>
              ))}
              {summary.failedRules.length > 8 && <li className="meta">and {summary.failedRules.length - 8} more rules</li>}
            </ol>
          )}
        </Disclosure>
      </div>
    </section>
  );
}
