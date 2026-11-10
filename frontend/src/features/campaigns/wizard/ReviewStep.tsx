import { useState } from "react";
import { shortHash } from "../../cluster/clusterFormat";
import { plural, splitClassId } from "../campaignFormat";
import { describeReason, reasonsByStep, type Reason } from "./reasons";
import type { ValidationState } from "./useValidation";
import { WIZARD_STEP_LABELS, WIZARD_STEPS, type WizardStepId } from "./wizardState";

const CLASSES_SHOWN = 30;

function entryLabel(step: WizardStepId, reason: Reason): string {
  const number = (reason.entry ?? 0) + 1;
  if (step === "runs") {
    return `Run ${number}`;
  }
  if (reason.list === "scenario") {
    return `Scenario file ${number}`;
  }
  return reason.list === "item" ? `Input item ${number}` : `Scope entry ${number}`;
}

function ReasonGroup({ step, reasons, onGoTo }: { step: WizardStepId; reasons: readonly Reason[]; onGoTo: (step: WizardStepId) => void }) {
  if (reasons.length === 0) {
    return null;
  }
  return (
    <section className="wiz-reason-group" aria-label={`Problems in ${WIZARD_STEP_LABELS[step]}`}>
      <header>
        <h5>{WIZARD_STEP_LABELS[step]}</h5>
        {step !== "review" && (
          <button type="button" onClick={() => onGoTo(step)}>
            Go to {WIZARD_STEP_LABELS[step]}
          </button>
        )}
      </header>
      <ul>
        {reasons.map((reason, index) => (
          <li key={`${reason.raw}-${index}`}>
            <span className={`wiz-issue-source wiz-issue-source--${reason.source}`}>{reason.source === "server" ? "master" : "here"}</span>
            {reason.entry !== null && <strong>{entryLabel(step, reason)}: </strong>}
            {describeReason(reason)}
          </li>
        ))}
      </ul>
    </section>
  );
}

export interface ReviewStepProps {
  yaml: string;
  validation: ValidationState;
  /** Whether the validation answers the YAML shown. */
  current: boolean;
  /** What the browser found wrong without asking the master. */
  localReasons: readonly Reason[];
  /** What the master found wrong, from the last check or a refused create. */
  serverReasons: readonly Reason[];
  onGoTo: (step: WizardStepId) => void;
  onCheck: () => void;
  onCreate: (start: boolean) => void;
  creating: boolean;
  createMessage: string | null;
  /** Why the campaign cannot start on the cluster's machines, or null. */
  startBlocker: string | null;
  /** The base seed the case seeds count up from. */
  baseSeed: number | null;
  /**
   * Set when the campaign starts with the design space exploration: its FECs and cases are known only once the
   * exploration ran, so the review says what each explored FEC gets ("1 case per explored FEC") instead of a total.
   */
  explored?: string | null;
}

/** Review: the generated YAML, the master's check of it (reasons attached to their steps) and the way to create the campaign. */
export function ReviewStep({ yaml, validation, current, localReasons, serverReasons, onGoTo, onCheck, onCreate, creating, createMessage, startBlocker, baseSeed, explored = null }: ReviewStepProps) {
  const [copied, setCopied] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const all = [...localReasons, ...serverReasons];
  const grouped = reasonsByStep(all);
  const blocked = localReasons.length > 0;
  const result = validation.result;
  const ready = validation.status === "valid" && current && !blocked;

  const copy = () => {
    void navigator.clipboard?.writeText(yaml).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => setCopied(false)
    );
  };

  return (
    <div className="wiz-step wiz-review">
      <section className={`wiz-verdict wiz-verdict--${blocked ? "invalid" : validation.status}`} aria-live="polite">
        {blocked && (
          <p>
            <strong>Not ready to check.</strong> {plural(localReasons.length, "problem")} to fix first; the master is asked once the config is complete.
          </p>
        )}
        {!blocked && validation.status === "idle" && <p>The config has not been checked on the master yet.</p>}
        {!blocked && validation.status === "checking" && <p role="status">Checking the config on the master...</p>}
        {!blocked && validation.status === "valid" && result && explored !== null && (
          <p>
            <strong>The master accepts this config{current ? "" : " (an earlier version of it)"}.</strong> Its FECs come from the design space exploration, so how many
            there are is known only once it ran: {explored}{result.runs.length > 0 ? `, ${plural(result.runs.length, "run")}` : ""}, base seed <code>{baseSeed ?? 0}</code>.
            Config hash <code title={result.config_hash}>{shortHash(result.config_hash, 12)}</code>.
          </p>
        )}
        {!blocked && validation.status === "valid" && result && explored === null && (
          <p>
            <strong>The master accepts this config{current ? "" : " (an earlier version of it)"}.</strong> {plural(result.fecs.length, "FEC")} selected, <strong>{plural(result.cases_planned, "case")}</strong> planned
            to complete{result.runs.length > 0 ? `, ${plural(result.runs.length, "run")}` : ""}, base seed <code>{baseSeed ?? 0}</code>. Config hash <code title={result.config_hash}>{shortHash(result.config_hash, 12)}</code>.
          </p>
        )}
        {!blocked && validation.status === "invalid" && (
          <p>
            <strong>The master refuses this config.</strong> {plural(validation.reasons.length, "reason")}, listed with the step they belong to.
          </p>
        )}
        {!blocked && validation.status === "error" && (
          <p role="alert">
            <strong>The check did not complete.</strong> {validation.message}
          </p>
        )}
        <div className="wiz-verdict-actions">
          <button type="button" onClick={onCheck} disabled={validation.status === "checking" || blocked}>
            {validation.status === "checking" ? "Checking..." : "Check on the master"}
          </button>
        </div>
      </section>

      {(Object.keys(grouped) as WizardStepId[]).length > 0 && all.length > 0 && (
        <div className="wiz-reasons">
          {WIZARD_STEPS.map((step) => (
            <ReasonGroup key={step} step={step} reasons={grouped[step]} onGoTo={onGoTo} />
          ))}
        </div>
      )}

      {result && validation.status === "valid" && (explored === null || result.runs.length > 0) && (
        <div className="wiz-result">
          <h4>What the master resolved</h4>
          {explored === null && (
            <>
          <div className="camp-table-wrap wiz-class-scroll">
            <table className="camp-table camp-table--dense">
              <thead>
                <tr>
                  <th>FEC</th>
                  <th>Vessels</th>
                  <th>Obstacles</th>
                  <th>Quota</th>
                  <th>Failure budget</th>
                </tr>
              </thead>
              <tbody>
                {(showAll ? result.fecs : result.fecs.slice(0, CLASSES_SHOWN)).map((entry) => (
                  <tr key={entry.fec_id}>
                    <td title={entry.fec_id}>
                      <span className="camp-class-name">{splitClassId(entry.fec_id).name}</span>
                      <span className="camp-class-folder">{splitClassId(entry.fec_id).folder}</span>
                    </td>
                    <td className="camp-num">{entry.vessel_count}</td>
                    <td className="camp-num">{entry.obstacle_count}</td>
                    <td className="camp-num">{entry.quota}</td>
                    <td className="camp-num">{entry.failure_budget ?? "unlimited"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.fecs.length > CLASSES_SHOWN && (
            <button type="button" onClick={() => setShowAll((value) => !value)}>
              {showAll ? "Show fewer FECs" : `Show all ${result.fecs.length} FECs`}
            </button>
          )}
            </>
          )}
          <ul className="wiz-runs-result">
            {result.runs.map((run) => (
              <li key={run.run_index}>
                <strong>{run.name ?? `Run ${run.run_index}`}</strong> repeatability {run.repeatability_tier ?? "unknown"}
                {run.warnings.map((warning) => (
                  <span key={warning} className="wiz-plan-warning">
                    {" "}
                    {warning}
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </div>
      )}

      <details className="wiz-yaml" open>
        <summary>
          <span>Generated config</span>
          <span className="meta">YAML, exactly what is sent to the master</span>
        </summary>
        <div className="wiz-yaml-bar">
          <button type="button" onClick={copy}>
            {copied ? "Copied" : "Copy YAML"}
          </button>
        </div>
        <pre className="camp-yaml" tabIndex={0} aria-label="Generated campaign config">
          {yaml}
        </pre>
      </details>

      <section className="wiz-create" aria-label="Create the campaign">
        <h4>Create</h4>
        <p className="meta wiz-explain">A campaign is created paused unless you start it at once. A paused campaign holds its jobs until you start it in the campaign's page.</p>
        <div className="wiz-create-actions">
          <button type="button" disabled={!ready || creating} onClick={() => onCreate(false)}>
            {creating ? "Creating..." : "Create paused"}
          </button>
          <button
            type="button"
            className="primary-btn accent"
            disabled={!ready || creating || startBlocker !== null}
            title={startBlocker ?? undefined}
            onClick={() => onCreate(true)}
          >
            {creating ? "Creating..." : "Create and start"}
          </button>
        </div>
        {startBlocker && (
          <div className="wiz-start-blocked" role="status">
            <p>
              <strong>The campaign cannot start yet.</strong> {startBlocker} You can create it paused and start it from its page once the machines are there.
            </p>
            <button type="button" onClick={() => onGoTo("resources")}>
              Go to Resources
            </button>
          </div>
        )}
        {!ready && !creating && (
          <p className="wiz-hint">
            {blocked
              ? "Fix the problems above first."
              : validation.status === "checking"
                ? "Waiting for the master's check."
                : validation.status === "valid" && !current
                  ? "The config changed since the check; check it again."
                  : "The master has to accept the config first."}
          </p>
        )}
        {createMessage && (
          <p className="error" role="alert">
            {createMessage}
          </p>
        )}
      </section>
    </div>
  );
}
