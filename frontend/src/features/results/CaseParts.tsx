import { Fragment, useState } from "react";
import { saveBlob } from "../../components/saveBlob";
import { createOperatorClient, describeOperatorError, type OperatorClient } from "../../domain/cluster/operatorApi";
import type { CaseJob, RunRecord, Verdict } from "../../domain/cluster/schemas";
import { ruleOutcomeRows } from "./ruleOutcomes";
import { VERDICT_STEP_LABEL } from "./stepViews";
import { artifactFileName, describeStack, formatSeconds, formatTime, runLabel, shortHash, sortedArtifacts } from "./resultsFormat";
import { useJobDetail } from "./useResultsData";

export function StateChip({ state }: { state: string }) {
  return <span className={`results-chip results-chip--${state}`}>{state}</span>;
}

function JobLogs({ operatorUrl, jobId }: { operatorUrl: string; jobId: string }) {
  const query = useJobDetail(operatorUrl, jobId, true);
  if (query.isPending) {
    return <p className="meta">Loading the log.</p>;
  }
  if (query.isError) {
    return <p className="error">{describeOperatorError(query.error)}</p>;
  }
  const lines = query.data.log_lines;
  return (
    <div className="job-logs">
      {query.data.error && <p className="error">Error: {query.data.error}</p>}
      {lines.length === 0 ? (
        <p className="meta">The master holds no log lines for this job. It keeps the last 200 lines in memory only, so a restart of the master clears them.</p>
      ) : (
        <>
          <p className="meta">The last {lines.length} lines the master kept.</p>
          <pre className="job-log-text" tabIndex={0}>
            {lines.map((line) => `${formatTime(line.timestamp).slice(11)} ${line.stream}${line.source ? ` ${line.source}` : ""}  ${line.text}`).join("\n")}
          </pre>
        </>
      )}
    </div>
  );
}

/** The case's jobs by stage with state, attempts and error; the log of a job on demand. */
export function CaseJobsTable({ operatorUrl, jobs }: { operatorUrl: string; jobs: CaseJob[] }) {
  const [logsOf, setLogsOf] = useState<string | null>(null);
  if (jobs.length === 0) {
    return <p className="meta">No job has been submitted for this case yet.</p>;
  }
  return (
    <div className="results-table-wrap">
      <table className="results-table results-table--plain" aria-label="Jobs of the case">
        <thead>
          <tr>
            <th>Stage</th>
            <th>Run</th>
            <th>Job type</th>
            <th>State</th>
            <th>Attempts</th>
            <th>Started</th>
            <th>Finished</th>
            <th>Error</th>
            <th aria-label="Log" />
          </tr>
        </thead>
        <tbody>
          {jobs.map((link) => {
            const job = link.job;
            const key = link.idempotency_key;
            const open = link.job_id !== null && logsOf === link.job_id;
            return (
              <Fragment key={key}>
                <tr>
                  <td>{link.stage.replace("_", " ")}</td>
                  <td>{link.run_index === null ? "-" : runLabel(link.run_index, link.repeat_index)}</td>
                  <td>{job?.job_type ?? <span className="meta">{link.intent ? "intended" : "not submitted"}</span>}</td>
                  <td>{job ? <StateChip state={job.state} /> : <span className="meta">-</span>}</td>
                  <td className="mono">{job ? `${job.attempt} of ${job.max_attempts}${job.failed_attempts > 0 ? ` (${job.failed_attempts} failed)` : ""}` : "-"}</td>
                  <td className="mono">{formatTime(job?.started_at)}</td>
                  <td className="mono">{formatTime(job?.finished_at)}</td>
                  <td className={job?.error ? "results-error-cell" : undefined}>{job?.error ?? ""}</td>
                  <td>
                    {link.job_id !== null && (
                      <button type="button" onClick={() => setLogsOf(open ? null : link.job_id)} aria-expanded={open}>
                        {open ? "Hide log" : "Log"}
                      </button>
                    )}
                  </td>
                </tr>
                {open && link.job_id !== null && (
                  <tr className="results-row-detail">
                    <td colSpan={9}>
                      <JobLogs operatorUrl={operatorUrl} jobId={link.job_id} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Downloads an artifact through the operator client and saves it as a file. The operator API is
 * another origin, where a link's `download` is ignored and the link would navigate the console away.
 */
export function ArtifactDownload({ client, role, sha256 }: { client: Pick<OperatorClient, "getArtifactBlob">; role: string; sha256: string }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const download = async () => {
    setBusy(true);
    setError(null);
    try {
      const blob = await client.getArtifactBlob(sha256);
      saveBlob(blob, artifactFileName(role, sha256, blob.type));
    } catch (caught) {
      setError(`Cannot download it: ${describeOperatorError(caught)}`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="run-artifact-download">
      {error && (
        <span className="error" role="alert">
          {error}
        </span>
      )}
      <button type="button" onClick={() => void download()} disabled={busy} aria-label={`${busy ? "Downloading" : "Download"} ${role.replace(/_/g, " ")}`}>
        {busy ? "Downloading" : "Download"}
      </button>
    </span>
  );
}

/** One run record: stack, seed, steps, digest, durations and its artifacts with download buttons. */
export function RunRecordCard({
  operatorUrl,
  record,
  selected,
  onShow,
}: {
  operatorUrl: string;
  record: RunRecord;
  selected: boolean;
  onShow: () => void;
}) {
  const client = createOperatorClient(operatorUrl);
  const durations = Object.entries(record.durations_s);
  const artifacts = sortedArtifacts(record.artifacts);
  return (
    <article className={`run-record${selected ? " run-record--selected" : ""}`}>
      <header>
        <strong>{runLabel(record.run_index, record.repeat_index)}</strong>
        <span className="meta">record {record.run_record_id}</span>
        {record.repeatability_tier && <span className="run-tag">{record.repeatability_tier}</span>}
        <span className="results-spacer" />
        <button type="button" className={selected ? undefined : "primary-btn accent"} onClick={onShow} aria-pressed={selected}>
          {selected ? "Shown below" : "Show the run"}
        </button>
      </header>
      <dl className="results-facts">
        <div>
          <dt>Stack</dt>
          <dd>{describeStack(record.stack)}</dd>
        </div>
        <div>
          <dt>Trajectories</dt>
          <dd>
            {record.trajectory_generator ?? (record.source === "live_session" ? "recorded from a live session" : "taken from an item")}
            {record.trajectories_complete ? "" : ", incomplete"}
          </dd>
        </div>
        <div>
          <dt>Seed</dt>
          <dd className="mono">{record.seed}</dd>
        </div>
        <div>
          <dt>Steps</dt>
          <dd className="mono">
            {record.steps ?? "-"}
            {record.dt !== null ? ` at ${record.dt} s` : ""}
          </dd>
        </div>
        <div>
          <dt>State digest</dt>
          <dd className="mono" title={record.state_digest ?? undefined}>
            {shortHash(record.state_digest, 16)}
          </dd>
        </div>
        <div>
          <dt>Node</dt>
          <dd>{record.node_id ?? "-"}</dd>
        </div>
        <div>
          <dt>Durations</dt>
          <dd className="mono">{durations.length === 0 ? "-" : durations.map(([name, value]) => `${name} ${formatSeconds(value)}`).join(", ")}</dd>
        </div>
        <div>
          <dt>Recorded</dt>
          <dd className="mono">{formatTime(record.created_at)}</dd>
        </div>
      </dl>
      {artifacts.length > 0 ? (
        <ul className="run-artifacts" aria-label="Artifacts of the run">
          {artifacts.map(([role, sha256]) => (
            <li key={role}>
              <span>{role.replace(/_/g, " ")}</span>
              <code title={sha256}>{shortHash(sha256, 10)}</code>
              <ArtifactDownload client={client} role={role} sha256={sha256} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="meta">The run kept no artifacts (retention may have removed them).</p>
      )}
    </article>
  );
}

/** A verdict with its failed rules and each rule's outcomes as a table. */
export function VerdictCard({ verdict }: { verdict: Verdict }) {
  const rows = ruleOutcomeRows(verdict.rule_outcomes);
  return (
    <article className={`verdict-card verdict-card--${verdict.state}`}>
      <header>
        <StateChip state={verdict.state} />
        {verdict.step !== undefined && <strong>{VERDICT_STEP_LABEL[verdict.step]}</strong>}
        {verdict.step === undefined || verdict.step === "simulation" ? <strong>{runLabel(verdict.run_index)}</strong> : null}
        <span className="meta">{verdict.monitor} monitor</span>
        {verdict.sensitive && <span className="run-tag">sensitive</span>}
        <span className="results-spacer" />
        <span className="meta">
          {verdict.first_failure_time_s !== null ? `first failure at ${formatSeconds(verdict.first_failure_time_s)}` : "no failure"}
          {verdict.early_stop_time_s !== null ? `, stopped early at ${formatSeconds(verdict.early_stop_time_s)}` : ""}
          {verdict.margin !== null ? `, margin ${Number(verdict.margin.toFixed(3))}` : ""}
        </span>
      </header>
      {rows.length === 0 ? (
        <p className="meta">{verdict.state === "unmonitored" ? "This run was not monitored." : "The monitor reported no rule outcomes."}</p>
      ) : (
        <div className="results-table-wrap">
          <table className="results-table results-table--plain" aria-label={`Rule outcomes of ${runLabel(verdict.run_index)}`}>
            <thead>
              <tr>
                <th>Outcome</th>
                <th>Rule</th>
                <th>Vessels</th>
                <th>First failure</th>
                <th>First pass</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.relation}|${row.rule}`} className={row.outcome === "failed" ? "results-row-failed" : undefined}>
                  <td>
                    <StateChip state={row.outcome} />
                  </td>
                  <td>{row.rule}</td>
                  <td className="mono">{row.relation}</td>
                  <td className="mono">{formatSeconds(row.failedAt)}</td>
                  <td className="mono">{formatSeconds(row.passedAt)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </article>
  );
}
