import { useUiStore } from "../../app/uiStore";
import { describeOperatorError } from "../../domain/cluster/operatorApi";
import { useResultsStore } from "../../domain/cluster/resultsStore";
import { plural } from "../campaigns/campaignFormat";
import { ToneBadge } from "./campaignParts";
import { failureGroups, STAGE_LABELS, type FailureGroup } from "./historyModel";
import { FAILURE_CASES_READ, useCaseFailures } from "./useHistoryData";

/** How many reasons are listed before the rest is summed up in one line. */
const REASONS_SHOWN = 5;

function openCase(campaignId: string, caseId: number): void {
  useResultsStore.getState().openCase(campaignId, caseId);
  useUiStore.getState().setSection("results");
}

function ReasonRow({ campaignId, group }: { campaignId: string; group: FailureGroup }) {
  const failed = group.state === "failed";
  return (
    <li className="history-failure">
      <ToneBadge tone={failed ? "bad" : "warn"} title={failed ? "A job of the case failed: a fault of the system, not of the output" : "The step gave no output a later step can use"}>
        {group.count} {group.state}
      </ToneBadge>
      <span className="history-failure-stage">in {STAGE_LABELS[group.stage]}</span>
      <span className="history-failure-reason" title={group.reason}>
        {group.reason}
      </span>
      <button type="button" className="camp-link" onClick={() => openCase(campaignId, group.caseId)} title="Open one of these cases in the Results section, with its jobs and their errors">
        Open a case
      </button>
    </li>
  );
}

export interface FailureReasonsProps {
  campaignId: string;
  /** Cases the entry reports as dropped or failed; the panel is not shown without any. */
  count: number;
  running: boolean;
}

/**
 * Why cases did not complete: the dropped and failed cases of an entry by the step they stopped at
 * and the reason they share, the most frequent first. One line then says what twenty rows of the
 * outputs table say one by one.
 */
export function FailureReasons({ campaignId, count, running }: FailureReasonsProps) {
  const query = useCaseFailures(campaignId, count > 0, running);
  if (count <= 0) {
    return null;
  }
  const groups = failureGroups(query.data?.cases ?? []);
  const read = query.data?.cases.length ?? 0;
  const total = query.data?.total ?? 0;
  const hidden = groups.slice(REASONS_SHOWN);
  return (
    <section className="panel history-failures" aria-label="Why cases did not complete">
      <div className="camp-section-head">
        <h3>Why cases did not complete</h3>
        <span className="meta">
          {query.data ? `${plural(total, "case")}, the most frequent reason first` : null}
          {query.data && total > read ? ` (read from the first ${read}; at most ${FAILURE_CASES_READ} dropped and ${FAILURE_CASES_READ} failed)` : null}
        </span>
      </div>
      {query.isLoading ? (
        <p className="meta" role="status">Reading the reasons...</p>
      ) : query.error && !query.data ? (
        <p className="meta warning">The reasons did not load: {describeOperatorError(query.error)}</p>
      ) : groups.length === 0 ? (
        <p className="meta">The control node lists no dropped or failed case any more.</p>
      ) : (
        <ul className="history-failure-list">
          {groups.slice(0, REASONS_SHOWN).map((group) => (
            <ReasonRow key={`${group.state}/${group.stage}/${group.reason}`} campaignId={campaignId} group={group} />
          ))}
          {hidden.length > 0 && (
            <li className="meta">
              and {plural(hidden.reduce((sum, group) => sum + group.count, 0), "case")} for {plural(hidden.length, "other reason")}
            </li>
          )}
        </ul>
      )}
    </section>
  );
}
