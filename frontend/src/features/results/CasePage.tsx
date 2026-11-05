import { useState } from "react";
import { Disclosure } from "../../components/Disclosure";
import { describeOperatorError } from "../../domain/cluster/operatorApi";
import type { CampaignStep, CaseDetail, RunRecord } from "../../domain/cluster/schemas";
import { CaseJobsTable, RunRecordCard, StateChip, VerdictCard } from "./CaseParts";
import { caseStepRows, describeStepVerdict } from "./stepViews";
import { RecordedRun } from "./RecordedRun";
import { formatTime, shortClassId, stageLabel } from "./resultsFormat";
import { useCaseDetail } from "./useResultsData";

interface CasePageProps {
  operatorUrl: string;
  campaignId: string;
  caseId: number;
  /** The steps the entry executed. */
  steps: readonly CampaignStep[];
  onBack: () => void;
}

/** Every step of the chain for this case: whether the entry ran it, what the case has of its output, and the verdict. */
function CaseSteps({ detail, steps }: { detail: CaseDetail; steps: readonly CampaignStep[] }) {
  const rows = caseStepRows(detail, steps);
  return (
    <section className="results-panel" aria-label="Steps of the case">
      <header className="results-panel-head">
        <h3>Steps</h3>
        <span className="meta">{steps.length} of 3 executed</span>
      </header>
      <div className="results-table-wrap">
        <table className="results-table results-table--plain" aria-label="Monitor summary of each step">
          <thead>
            <tr>
              <th>Step</th>
              <th>Output</th>
              <th>Monitor summary</th>
              <th>Failed rules</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.step} className={row.executed ? undefined : "results-row--skipped"}>
                <td>{row.label}</td>
                <td>{row.executed ? row.output : <span className="meta">-</span>}</td>
                <td>
                  {row.monitored && <StateChip state={row.verdicts.failed > 0 ? "failed" : "passed"} />}
                  {(!row.monitored || row.verdicts.passed + row.verdicts.failed > 1) && (
                    <span className={row.monitored ? undefined : "meta"}> {describeStepVerdict(row)}</span>
                  )}
                </td>
                <td>{row.failedRules.length === 0 ? <span className="meta">-</span> : row.failedRules.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function CaseSummary({ detail }: { detail: CaseDetail }) {
  return (
    <section className="results-panel" aria-label="The case">
      <header className="results-panel-head">
        <h3 title={detail.fec_id}>{shortClassId(detail.fec_id, 64)}</h3>
        <span className="meta">case {detail.case_index}</span>
        <StateChip state={detail.state} />
        <span className="run-tag">stage {stageLabel(detail.stage)}</span>
      </header>
      <Disclosure id="results:case-details" variant="link" headingLevel={null} title="Case details" openTitle="Hide case details" hint={`seed ${detail.seed}`}>
      <dl className="results-facts">
        <div>
          <dt>FEC</dt>
          <dd className="mono">{detail.fec_id}</dd>
        </div>
        <div>
          <dt>Case index</dt>
          <dd className="mono">{detail.case_index}</dd>
        </div>
        <div>
          <dt>Seed</dt>
          <dd className="mono">{detail.seed}</dd>
        </div>
        <div>
          <dt>Config version</dt>
          <dd className="mono">{detail.config_version}</dd>
        </div>
        <div>
          <dt>Trajectories</dt>
          <dd>{detail.trajectories_complete === null ? "not generated" : detail.trajectories_complete ? "complete" : "incomplete"}</dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd className="mono">{formatTime(detail.created_at)}</dd>
        </div>
        <div>
          <dt>Finished</dt>
          <dd className="mono">{formatTime(detail.finished_at)}</dd>
        </div>
      </dl>
      </Disclosure>
      {detail.reason && (
        <p className={detail.state === "dropped" || detail.state === "failed" ? "results-reason results-reason--bad" : "results-reason"}>
          <strong>Reason:</strong> {detail.reason}
        </p>
      )}
    </section>
  );
}

/** One case: its state, jobs, run records and verdicts, and a recorded run on demand. */
export function CasePage({ operatorUrl, campaignId, caseId, steps, onBack }: CasePageProps) {
  const query = useCaseDetail(operatorUrl, campaignId, caseId);
  const [shownId, setShownId] = useState<number | null>(null);
  const detail = query.data;

  const back = (
    <button type="button" onClick={onBack} className="results-back">
      Back to the monitor summaries
    </button>
  );
  if (query.isPending) {
    return (
      <div className="results-stack">
        {back}
        <p className="meta" role="status">
          Loading the case.
        </p>
      </div>
    );
  }
  if (query.isError || !detail) {
    return (
      <div className="results-stack">
        {back}
        <div className="results-notice results-notice--bad" role="alert">
          <strong>The case cannot be loaded.</strong>
          <span>{describeOperatorError(query.error)}</span>
        </div>
      </div>
    );
  }

  const shown: RunRecord | undefined = detail.run_records.find((record) => record.run_record_id === shownId);
  const verdictOfShown = shown
    ? detail.verdicts.find((verdict) => verdict.run_record_id === shown.run_record_id) ?? detail.verdicts.find((verdict) => verdict.run_index === shown.run_index) ?? null
    : null;

  return (
    <div className="results-stack">
      {back}
      <CaseSummary detail={detail} />
      <CaseSteps detail={detail} steps={steps} />

      <section className="results-panel" aria-label="Monitor summaries of the case">
        <header className="results-panel-head">
          <h3>Monitor summaries of the steps</h3>
          <span className="meta">{detail.verdicts.length}</span>
        </header>
        {detail.verdicts.length === 0 ? (
          <p className="meta">The case has no monitor summary yet.</p>
        ) : (
          <div className="results-stack">
            {detail.verdicts.map((verdict) => (
              <VerdictCard key={verdict.verdict_id} verdict={verdict} />
            ))}
          </div>
        )}
      </section>

      <section className="results-panel" aria-label="Run records">
        <header className="results-panel-head">
          <h3>Run records</h3>
          <span className="meta">{detail.run_records.length}</span>
        </header>
        {detail.run_records.length === 0 ? (
          <p className="meta">No run has finished for this case yet.</p>
        ) : (
          <div className="run-record-list">
            {detail.run_records.map((record) => (
              <RunRecordCard
                key={record.run_record_id}
                operatorUrl={operatorUrl}
                record={record}
                selected={record.run_record_id === shownId}
                onShow={() => setShownId(record.run_record_id)}
              />
            ))}
          </div>
        )}
      </section>

      {shown && (
        <RecordedRun
          key={shown.run_record_id}
          operatorUrl={operatorUrl}
          campaignId={campaignId}
          runRecord={shown}
          verdict={verdictOfShown}
          title={`${shortClassId(detail.fec_id, 40)}, case ${detail.case_index}, run ${shown.run_index}`}
          autoStart
        />
      )}

      <Disclosure id="results:case-jobs" title="Jobs of the case" hint={`${detail.jobs.length} in the history`} headingLevel={3}>
        <CaseJobsTable operatorUrl={operatorUrl} jobs={detail.jobs} />
      </Disclosure>
    </div>
  );
}
