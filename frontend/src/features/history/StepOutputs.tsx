import { useState } from "react";
import type { OutputRow } from "../../domain/cluster/historyApi";
import { describeOperatorError, OperatorApiError } from "../../domain/cluster/operatorApi";
import type { CampaignStep, CaseState } from "../../domain/cluster/schemas";
import type { VesselRole } from "../workbench/monitor/encounterPairs";
import { openInWorkbench } from "../workbench/pages/workbenchTarget";
import { plural } from "../campaigns/campaignFormat";
import type { Tone } from "./campaignModel";
import { EmptyState, ToneBadge } from "./campaignParts";
import {
  canOpenOutput,
  inputSourceLabel,
  isOutputRunning,
  monitorSummary,
  OUTPUT_PAGE_SIZE,
  outputCaseLabel,
  outputFlags,
  outputTarget,
  runLabel,
  showsMonitorSummary,
  STEP_LABELS,
  STEP_OUTPUT_NOUNS,
  type MonitorEncounter,
} from "./historyModel";
import { useStepOutputs } from "./useHistoryData";

const CASE_STATE_LABELS: Record<CaseState, string> = {
  active: "in progress",
  complete: "complete",
  dropped: "dropped",
  failed: "failed",
  cancelled: "cancelled",
};

const CASE_STATE_TONES: Record<CaseState, Tone> = {
  active: "info",
  complete: "ok",
  dropped: "warn",
  failed: "bad",
  cancelled: "idle",
};

/** How many failed rules a list shows; the rest are in the tooltip of its last line, and all of them in Results. */
const FAILED_RULES_SHOWN = 3;

const ROLE_TONES: Record<VesselRole, Tone> = {
  "give-way": "warn",
  "stand-on": "info",
};

export interface StepOutputsProps {
  campaignId: string;
  step: CampaignStep;
  /** The entry still runs: the page is read again every few seconds. */
  running: boolean;
  /** Whether the entry's config monitors the step; null while the config is not known. */
  monitored: boolean | null;
  onOpenEntry: (campaignId: string) => void;
}

function FailedRules({ rules }: { rules: readonly string[] }) {
  if (rules.length === 0) {
    return null;
  }
  const hidden = rules.slice(FAILED_RULES_SHOWN);
  return (
    <ul className="history-monitor-rules">
      {rules.slice(0, FAILED_RULES_SHOWN).map((rule) => (
        <li key={rule}>{rule}</li>
      ))}
      {hidden.length > 0 && (
        <li className="history-monitor-more" title={hidden.join("\n")}>
          and {hidden.length} more
        </li>
      )}
    </ul>
  );
}

function EncounterLine({ encounter }: { encounter: MonitorEncounter }) {
  return (
    <span className="history-monitor-encounter">
      <span className="history-monitor-type">{encounter.label}</span>
      {encounter.roles === null ? (
        <span className="meta" title="The monitor that wrote this summary did not record the roles of the vessels.">
          roles not recorded
        </span>
      ) : (
        <span className="history-monitor-roles">
          {encounter.roles.map(({ vessel, role }) => (
            <ToneBadge key={vessel} tone={ROLE_TONES[role]} title={`${vessel} is the ${role} vessel`}>
              {vessel} {role}
            </ToneBadge>
          ))}
        </span>
      )}
    </span>
  );
}

/** The monitor summary of an output, very brief: passed or failed and, per vessel pair, the encounter types, the vessels' roles and the rules that failed. */
function MonitorSummaryCell({ row }: { row: OutputRow }) {
  if (row.verdict === null) {
    return <span className="meta">{row.state === "active" ? "no monitor summary yet" : "no monitor summary"}</span>;
  }
  const summary = monitorSummary(row.verdict);
  if (summary.headline === null) {
    return <span className="camp-verdict camp-verdict--unmonitored">not monitored</span>;
  }
  return (
    <div className="history-monitor">
      <div className="history-monitor-head">
        <span className={`camp-verdict camp-verdict--${summary.state}`}>{summary.state}</span>
        <span className="meta">{summary.headline}</span>
      </div>
      {summary.pairs.map((pair) => (
        <div key={pair.relation} className={`history-monitor-pair${pair.failedRules.length > 0 ? " history-monitor-pair--failed" : ""}`}>
          <span className="history-monitor-relation">{pair.relation}</span>
          {pair.encounters.length === 0 ? <span className="meta">no encounter</span> : pair.encounters.map((encounter) => <EncounterLine key={encounter.type} encounter={encounter} />)}
          <FailedRules rules={pair.failedRules} />
        </div>
      ))}
      <FailedRules rules={summary.otherFailedRules} />
      {summary.quietPairs > 0 && <span className="meta">{plural(summary.quietPairs, "pair")} without an encounter</span>}
    </div>
  );
}

function OutputRowView({
  campaignId,
  step,
  row,
  showMonitor,
  onOpenEntry,
}: {
  campaignId: string;
  step: CampaignStep;
  row: OutputRow;
  showMonitor: boolean;
  onOpenEntry: (campaignId: string) => void;
}) {
  const caseLabel = outputCaseLabel(row);
  const source = inputSourceLabel(row.input_source);
  const run = runLabel(row);
  const flags = outputFlags(row);
  const running = isOutputRunning(row);
  return (
    <tr>
      <td>
        <span className="camp-class-name" title={row.fec_id}>
          {caseLabel.title}
        </span>
        {caseLabel.detail && <span className="camp-class-folder">{caseLabel.detail}</span>}
        {run && <span className="meta history-run">{run}</span>}
      </td>
      <td>
        <ToneBadge tone={CASE_STATE_TONES[row.state]}>{CASE_STATE_LABELS[row.state]}</ToneBadge>
        {row.reason && <span className="camp-reason">{row.reason}</span>}
      </td>
      <td>
        {flags.length === 0 ? (
          <span className="meta">{row.artifact ? "" : "no output yet"}</span>
        ) : (
          <span className="history-flags">
            {flags.map((flag) => (
              <ToneBadge key={flag.label} tone={flag.tone} title={flag.title}>
                {flag.label}
              </ToneBadge>
            ))}
          </span>
        )}
      </td>
      {showMonitor && (
        <td>
          <MonitorSummaryCell row={row} />
        </td>
      )}
      <td>
        {source === null ? (
          <span className="meta">none</span>
        ) : source.kind === "entry" ? (
          <button type="button" className="camp-link" title={`Open entry ${source.campaignId}`} onClick={() => onOpenEntry(source.campaignId)}>
            {source.text}
          </button>
        ) : (
          <span>{source.text}</span>
        )}
      </td>
      <td className="history-cell-actions">
        {running ? (
          <button type="button" onClick={() => openInWorkbench(outputTarget(campaignId, step, row, true))} title={`Follow the running job on the ${STEP_LABELS[step].toLowerCase()} page`}>
            Watch live
          </button>
        ) : (
          <button
            type="button"
            disabled={!canOpenOutput(row)}
            onClick={() => openInWorkbench(outputTarget(campaignId, step, row))}
            title={canOpenOutput(row) ? `Load this ${STEP_OUTPUT_NOUNS[step].one} on the ${STEP_LABELS[step].toLowerCase()} page` : "This case has no output for the step"}
          >
            Open in workbench
          </button>
        )}
      </td>
    </tr>
  );
}

/** The outputs of one executed step, a page at a time, each with its state, flags, the monitor summary of a monitored step and the way onto its workbench page. */
export function StepOutputs({ campaignId, step, running, monitored, onOpenEntry }: StepOutputsProps) {
  const [page, setPage] = useState(0);
  const query = useStepOutputs(campaignId, step, page, running);
  const total = query.data?.total ?? null;
  const rows = query.data?.items ?? [];
  const nouns = STEP_OUTPUT_NOUNS[step];

  if (query.isLoading) {
    return <p className="meta" role="status">Loading the {nouns.many}...</p>;
  }
  if (query.error && !query.data) {
    const missing = query.error instanceof OperatorApiError && query.error.status === 404;
    return (
      <EmptyState title={missing ? "This master lists no outputs" : `The ${nouns.many} did not load`} tone="error">
        <p className="meta">{missing ? "The outputs route is new in Phase 6; update the master to browse the outputs of each step." : describeOperatorError(query.error)}</p>
        <div>
          <button type="button" onClick={() => void query.refetch()} disabled={query.isFetching}>
            Try again
          </button>
        </div>
      </EmptyState>
    );
  }
  if (rows.length === 0 && page > 0) {
    return (
      <EmptyState title="This page is past the end" action={<button type="button" onClick={() => setPage(0)}>Back to the first page</button>}>
        <p className="meta">The step has fewer {nouns.many} than when the page was chosen.</p>
      </EmptyState>
    );
  }
  if (rows.length === 0) {
    return (
      <EmptyState title={`No ${nouns.many} yet`}>
        <p className="meta">{running ? `They appear here as the cases reach ${STEP_LABELS[step].toLowerCase()}.` : `No case reached ${STEP_LABELS[step].toLowerCase()}.`}</p>
      </EmptyState>
    );
  }

  const known = total ?? page * OUTPUT_PAGE_SIZE + rows.length;
  const pages = Math.max(1, Math.ceil(known / OUTPUT_PAGE_SIZE));
  const showMonitor = showsMonitorSummary(monitored, rows);
  return (
    <div className="history-outputs">
      {query.error ? <p className="meta warning">The outputs may be stale: {describeOperatorError(query.error)}</p> : null}
      <div className="camp-table-wrap">
        <table className="camp-table camp-table--dense">
          <thead>
            <tr>
              <th>Case</th>
              <th>State</th>
              <th>Output</th>
              {showMonitor && <th>Monitor summary</th>}
              <th>Input from</th>
              <th>
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <OutputRowView key={`${row.case_id}/${row.run_record_id ?? "-"}/${row.run_index ?? "-"}/${row.repeat_index ?? "-"}`} campaignId={campaignId} step={step} row={row} showMonitor={showMonitor} onOpenEntry={onOpenEntry} />
            ))}
          </tbody>
        </table>
      </div>
      <div className="camp-paging">
        <span className="meta">
          {page * OUTPUT_PAGE_SIZE + 1} to {page * OUTPUT_PAGE_SIZE + rows.length} of {plural(known, nouns.one, nouns.many)}
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
