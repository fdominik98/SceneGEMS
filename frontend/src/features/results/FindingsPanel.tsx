import { Disclosure } from "../../components/Disclosure";
import type { Findings } from "../../domain/cluster/historyApi";
import { describeOperatorError } from "../../domain/cluster/operatorApi";
import { percent } from "../../domain/cluster/resultsApi";
import { StateChip } from "./CaseParts";
import { describeFindings, STEP_OUTPUT, type FindingsView } from "./stepViews";

interface FindingsPanelProps {
  findings: Findings | undefined;
  loading: boolean;
  error: unknown;
}

function Tile({ label, count, tone, detail }: { label: string; count: number; tone?: "passed" | "failed" | "unmonitored"; detail: string }) {
  return (
    <div className={`results-tile${tone ? ` results-tile--${tone}` : ""}`}>
      <span className="results-tile-label">{label}</span>
      <span className="results-tile-value">{count}</span>
      <span className="results-tile-detail">{detail}</span>
    </div>
  );
}

function share(part: number, whole: number): string {
  return whole > 0 ? `${percent(part, whole)} percent of ${whole}` : "none";
}

function RankedRules({ rules }: { rules: FindingsView["failedRules"] }) {
  const most = Math.max(1, ...rules.map((rule) => rule.count));
  return (
    <ol className="results-rules-rank results-rules-rank--findings">
      {rules.map((rule) => (
        <li key={rule.rule}>
          <span className="results-rule-name" title={rule.rule}>
            {rule.rule}
          </span>
          <span className="results-bar">
            <span className="results-bar-fill results-bar-fill--failed" style={{ width: `${(rule.count / most) * 100}%` }} />
          </span>
          <span className="mono results-rule-count">{rule.count}</span>
          <span className="meta">
            first failure from {rule.firstMin}, median {rule.firstMedian}
          </span>
        </li>
      ))}
    </ol>
  );
}

function ClassTable({ view }: { view: FindingsView }) {
  return (
    <div className="results-table-wrap">
      <table className="results-table results-table--plain results-table--compact" aria-label="Findings per FEC">
        <thead>
          <tr>
            <th>FEC</th>
            <th>Cases</th>
            {view.monitored && <th>Passed</th>}
            {view.monitored && <th>Failed</th>}
            {view.monitored && <th aria-label="Share failed" />}
          </tr>
        </thead>
        <tbody>
          {view.classes.map((row) => (
            <tr key={row.classId}>
              <td className="results-class" title={row.classId}>
                {row.classId}
              </td>
              <td className="mono">{row.cases}</td>
              {view.monitored && <td className="mono">{row.passed}</td>}
              {view.monitored && <td className={`mono${row.failed > 0 ? " results-count-failed" : ""}`}>{row.failed}</td>}
              {view.monitored && (
                <td>
                  <span className="results-bar" title={`${percent(row.failed, row.passed + row.failed)} percent failed`}>
                    <span className="results-bar-fill results-bar-fill--failed" style={{ width: `${percent(row.failed, row.passed + row.failed)}%` }} />
                  </span>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The findings of one step of an entry (design doc 6.13): cases by state, outputs, the verdicts
 * and failed rules when a monitor judged the step, per class, and durations. An unmonitored step
 * shows its statistics and says so plainly.
 */
export function FindingsPanel({ findings, loading, error }: FindingsPanelProps) {
  if (error && !findings) {
    return (
      <div className="results-notice results-notice--bad" role="alert">
        <strong>The findings cannot be loaded.</strong>
        <span>{describeOperatorError(error)}</span>
      </div>
    );
  }
  if (!findings) {
    return (
      <section className="results-panel" aria-label="Findings of the step">
        <p className="meta" role="status">
          {loading ? "Loading the findings." : "No findings."}
        </p>
      </section>
    );
  }
  const view = describeFindings(findings);
  const judged = view.verdicts?.judged ?? 0;
  return (
    <section className="results-panel" aria-label="Findings of the step">
      <header className="results-panel-head">
        <h3>Findings</h3>
        <span className={`results-chip results-chip--${view.monitored ? "passed" : "undecided"}`}>{view.monitored ? "monitored" : "partial findings"}</span>
        <span className="meta">
          {view.totalCases} {view.totalCases === 1 ? "case" : "cases"} reached this step
        </span>
        {loading && (
          <span className="meta" role="status">
            updating
          </span>
        )}
      </header>
      {view.partial ? (
        <p className="results-notice results-notice--warn" role="note">
          {view.statement}
        </p>
      ) : (
        <p className="meta">{view.statement}</p>
      )}

      <div className="results-tiles">
        {view.verdicts && (
          <>
            <Tile label="Passed" count={view.verdicts.passed} tone="passed" detail={share(view.verdicts.passed, judged)} />
            <Tile label="Failed" count={view.verdicts.failed} tone="failed" detail={share(view.verdicts.failed, judged)} />
            {view.verdicts.unmonitored > 0 && <Tile label="Unmonitored" count={view.verdicts.unmonitored} tone="unmonitored" detail="without a monitor summary" />}
          </>
        )}
        <Tile label={`Valid ${STEP_OUTPUT[view.step]}`} count={view.outputs.valid} detail={share(view.outputs.valid, view.outputs.count)} />
        {view.showComplete && <Tile label="Complete" count={view.outputs.complete} detail={share(view.outputs.complete, view.outputs.count)} />}
      </div>

      <dl className="results-facts">
        <div>
          <dt>Cases by state</dt>
          <dd className="results-count-chips">
            {view.cases.length === 0 ? (
              <span className="meta">none yet</span>
            ) : (
              view.cases.map((entry) => (
                <span key={entry.label} className="results-count-chip">
                  <StateChip state={entry.label} /> <span className="mono">{entry.count}</span>
                </span>
              ))
            )}
          </dd>
        </div>
        <div>
          <dt>Outputs</dt>
          <dd>
            {view.outputs.count} {STEP_OUTPUT[view.step]} stored
          </dd>
        </div>
        <div>
          <dt>Generation time</dt>
          <dd className="mono">{view.duration ? `median ${view.duration.median}, 90th percentile ${view.duration.p90}` : "no finished job yet"}</dd>
        </div>
      </dl>

      {view.monitored && (
        <Disclosure
          id="results:findings-rules"
          title="Which rules failed"
          hint={view.failedRules.length === 0 ? "none" : `${view.failedRules.length} ${view.failedRules.length === 1 ? "rule" : "rules"}, most often first`}
          defaultOpen={view.failedRules.length > 0}
          variant="plain"
          headingLevel={4}
        >
          {view.failedRules.length === 0 ? <p className="meta">No rule failed in the monitor summaries of this step.</p> : <RankedRules rules={view.failedRules} />}
        </Disclosure>
      )}

      {view.monitored && view.encounters.length > 0 && (
        <Disclosure
          id="results:findings-encounters"
          title="Encounter types"
          hint={`${view.encounters.reduce((sum, entry) => sum + entry.count, 0)} vessel pairs, by the first type of each`}
          variant="plain"
          headingLevel={4}
        >
          <ul className="results-count-chips" aria-label="Vessel pairs by encounter type">
            {view.encounters.map((entry) => (
              <li key={entry.label} className="results-count-chip">
                {entry.label} <span className="mono">{entry.count}</span>
              </li>
            ))}
          </ul>
        </Disclosure>
      )}

      <Disclosure
        id="results:findings-classes"
        title="Per FEC"
        hint={`${view.classes.length} ${view.classes.length === 1 ? "FEC" : "FECs"}${view.monitored ? ", most failures first" : ""}`}
        variant="plain"
        headingLevel={4}
      >
        {view.classes.length === 0 ? <p className="meta">No FEC reached this step yet.</p> : <ClassTable view={view} />}
      </Disclosure>
    </section>
  );
}
