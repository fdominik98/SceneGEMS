import { useState } from "react";
import type {
  RuleEvaluation,
  RuleResult,
  RuleResultData,
  SituationContextData,
} from "../../domain/simulation/types";
import { renderActorName, renderRelationId } from "./actorNameFormat";

interface RuleResultsPanelProps {
  ruleResults: RuleResultData[];
  situationContexts: SituationContextData[];
}

/** FAILED first, then not-yet-evaluated, then satisfied. */
const RESULT_RANK: Record<RuleResult, number> = {
  FAILED: 0,
  UNKNOWN: 1,
  PASSED: 2,
};

const RESULT_META: Record<RuleResult, { label: string; className: string; title: string }> = {
  FAILED: { label: "Fail", className: "rule-pill--fail", title: "Rule violated" },
  PASSED: { label: "Pass", className: "rule-pill--pass", title: "Rule satisfied" },
  UNKNOWN: {
    label: "N/A",
    className: "rule-pill--na",
    title: "Not applicable yet in the current state",
  },
};

function sortEvaluations(evaluations: RuleEvaluation[]): RuleEvaluation[] {
  return [...evaluations].sort((a, b) => {
    if (RESULT_RANK[a.result] !== RESULT_RANK[b.result]) {
      return RESULT_RANK[a.result] - RESULT_RANK[b.result];
    }
    if (a.kind !== b.kind) {
      return a.kind === "rule" ? -1 : 1;
    }
    if (a.ruleNumber !== b.ruleNumber) {
      return a.ruleNumber.localeCompare(b.ruleNumber, undefined, { numeric: true });
    }
    return a.title.localeCompare(b.title);
  });
}

function RuleRow({ evaluation }: { evaluation: RuleEvaluation }) {
  const meta = RESULT_META[evaluation.result];
  const badge = evaluation.kind === "suggestion" ? "Tip" : `R${evaluation.ruleNumber || "?"}`;
  return (
    <li className={`rule-row rule-row--${evaluation.result.toLowerCase()}`}>
      <span className={`rule-pill ${meta.className}`} title={meta.title}>
        {meta.label}
      </span>
      <span
        className={`rule-num-badge${evaluation.kind === "suggestion" ? " rule-num-badge--tip" : ""}`}
      >
        {badge}
      </span>
      <div className="rule-row-main">
        <span className="rule-row-title">
          {evaluation.title || evaluation.ruleName}
          {evaluation.subjectActorName ? (
            <span className="rule-subject-chip">{renderActorName(evaluation.subjectActorName)}</span>
          ) : null}
        </span>
        <span className="rule-row-desc">{evaluation.description}</span>
      </div>
    </li>
  );
}

export function RuleResultsPanel({ ruleResults, situationContexts }: RuleResultsPanelProps) {
  const [showAll, setShowAll] = useState(false);

  const situationLabelByRelation = new Map(
    situationContexts.map((ctx) => [ctx.relationId, ctx.situationLabel]),
  );

  const totalFailed = ruleResults.reduce((acc, r) => acc + r.failedRules.length, 0);
  const totalRules = ruleResults.reduce((acc, r) => acc + r.evaluations.length, 0);

  if (ruleResults.length === 0) {
    return null;
  }

  return (
    <details className="frame-subpanel" data-has-failures={totalFailed > 0 ? "" : undefined}>
      <summary className="frame-subpanel-summary">
        <span>COLREGS rules</span>
        <span
          className={`frame-subpanel-badge${totalFailed > 0 ? " frame-subpanel-badge--bad" : ""}`}
        >
          {totalFailed > 0 ? `${totalFailed} failed` : `${totalRules} ok`}
        </span>
      </summary>

      <div className="rule-panel-body">
        <label className="rule-filter-toggle">
          <input
            type="checkbox"
            checked={showAll}
            onChange={(event) => setShowAll(event.target.checked)}
          />
          Show passed &amp; not-applicable
        </label>

        <div className="frame-list-stack">
          {ruleResults.map((group, groupIndex) => {
            const sorted = sortEvaluations(group.evaluations);
            const visible = showAll
              ? sorted
              : sorted.filter((evaluation) => evaluation.result === "FAILED");
            const hiddenCount = sorted.length - visible.length;
            const failedCount = group.failedRules.length;
            const situationLabel = situationLabelByRelation.get(group.relationId);

            return (
              <div
                key={`${group.relationId}-${groupIndex}`}
                className={`rule-group${group.overallStatus === "FAILED" ? " rule-group--failed" : ""}`}
              >
                <div className="rule-group-head">
                  <span className="rule-group-relation">
                    {renderRelationId(group.relationId)}
                  </span>
                  <span
                    className={`rule-status-pill ${
                      group.overallStatus === "FAILED"
                        ? "rule-status-pill--fail"
                        : "rule-status-pill--ok"
                    }`}
                  >
                    {group.overallStatus === "FAILED" ? "Failed" : "Compliant"}
                  </span>
                  <span className="rule-group-count meta">
                    {failedCount > 0 ? `${failedCount} / ` : ""}
                    {sorted.length} rule{sorted.length === 1 ? "" : "s"}
                  </span>
                  {situationLabel ? (
                    <span className="rule-group-situation">{situationLabel}</span>
                  ) : null}
                </div>

                {visible.length > 0 ? (
                  <ul className="rule-row-list">
                    {visible.map((evaluation, i) => (
                      <RuleRow key={`${evaluation.ruleName}-${evaluation.subjectActorId ?? ""}-${i}`} evaluation={evaluation} />
                    ))}
                  </ul>
                ) : (
                  <p className="meta rule-group-empty">
                    {sorted.length === 0
                      ? "No rules active for this encounter."
                      : "All active rules satisfied."}
                  </p>
                )}

                {!showAll && hiddenCount > 0 && visible.length > 0 ? (
                  <button
                    type="button"
                    className="rule-show-more"
                    onClick={() => setShowAll(true)}
                  >
                    +{hiddenCount} passed / not-applicable
                  </button>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </details>
  );
}
