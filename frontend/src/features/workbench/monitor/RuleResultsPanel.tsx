import { useState, type ReactNode } from "react";
import type {
  RuleEvaluation,
  RuleResult,
  RuleResultData,
  SituationContextData,
} from "../../../domain/simulation/types";
import { renderActorName } from "./actorNames";
import { RULE_SCOPE_HINTS } from "./monitorHints";
import { renderRelationId } from "./renderRelationId";
import { Hinted, PersistedDetails } from "./monitorPrimitives";
import { sortEvaluations } from "./ruleEvaluationOrder";
import { failedCount, splitRuleResults } from "./ruleScopes";

interface RuleResultsPanelProps {
  persistKey: string;
  ruleResults: RuleResultData[];
  situationContexts: SituationContextData[];
}

const RESULT_META: Record<RuleResult, { label: string; className: string; title: string }> = {
  FAILED: { label: "Fail", className: "rule-pill--fail", title: "Rule violated" },
  PASSED: { label: "Pass", className: "rule-pill--pass", title: "Rule satisfied" },
  UNKNOWN: {
    label: "N/A",
    className: "rule-pill--na",
    title: "Not applicable yet in the current state",
  },
};

function RuleRow({ evaluation, showSubject }: { evaluation: RuleEvaluation; showSubject: boolean }) {
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
          {showSubject && evaluation.subjectActorName ? (
            <span className="rule-subject-chip">{renderActorName(evaluation.subjectActorName)}</span>
          ) : null}
        </span>
        <span className="rule-row-desc">{evaluation.description}</span>
      </div>
    </li>
  );
}

/** One vessel's or one encounter's rules: a head line with the status, then the rows. */
function RuleGroup({
  heading,
  situationLabel,
  evaluations,
  emptyText,
  showSubject,
  showAll,
  onShowAll,
}: {
  heading: ReactNode;
  situationLabel?: string;
  evaluations: RuleEvaluation[];
  /** Shown when the group has no rule at all. */
  emptyText: string;
  /** Whether rows name their subject vessel: not under a vessel's own heading. */
  showSubject: boolean;
  showAll: boolean;
  onShowAll: () => void;
}) {
  const sorted = sortEvaluations(evaluations);
  const visible = showAll ? sorted : sorted.filter((evaluation) => evaluation.result === "FAILED");
  const hiddenCount = sorted.length - visible.length;
  const failed = failedCount(sorted);

  return (
    <div className={`rule-group${failed > 0 ? " rule-group--failed" : ""}`}>
      <div className="rule-group-head">
        <span className="rule-group-relation">{heading}</span>
        <span className={`rule-status-pill ${failed > 0 ? "rule-status-pill--fail" : "rule-status-pill--ok"}`}>
          {failed > 0 ? "Failed" : "Compliant"}
        </span>
        <span className="rule-group-count meta">
          {failed > 0 ? `${failed} / ` : ""}
          {sorted.length} rule{sorted.length === 1 ? "" : "s"}
        </span>
        {situationLabel ? <span className="rule-group-situation">{situationLabel}</span> : null}
      </div>

      {visible.length > 0 ? (
        <ul className="rule-row-list">
          {visible.map((evaluation, i) => (
            <RuleRow
              key={`${evaluation.ruleName}-${evaluation.subjectActorId ?? ""}-${i}`}
              evaluation={evaluation}
              showSubject={showSubject}
            />
          ))}
        </ul>
      ) : (
        <p className="meta rule-group-empty">{sorted.length === 0 ? emptyText : "All active rules satisfied."}</p>
      )}

      {!showAll && hiddenCount > 0 && visible.length > 0 ? (
        <button type="button" className="rule-show-more" onClick={onShowAll}>
          +{hiddenCount} passed / not-applicable
        </button>
      ) : null}
    </div>
  );
}

/**
 * The frame's rule results. A rule on one vessel's own maneuvering is listed once under that
 * vessel; the rules of an encounter are listed under its pair.
 */
export function RuleResultsPanel({ persistKey, ruleResults, situationContexts }: RuleResultsPanelProps) {
  const [showAll, setShowAll] = useState(false);

  if (ruleResults.length === 0) {
    return null;
  }

  const situationLabelByRelation = new Map(
    situationContexts.map((ctx) => [ctx.relationId, ctx.situationLabel]),
  );
  const { vessels, encounters } = splitRuleResults(ruleResults);
  const groups = [...vessels, ...encounters];
  const totalFailed = groups.reduce((acc, group) => acc + failedCount(group.evaluations), 0);
  const totalRules = groups.reduce((acc, group) => acc + group.evaluations.length, 0);
  const showAllRules = () => setShowAll(true);

  return (
    <PersistedDetails
      persistKey={persistKey}
      className="frame-subpanel"
      data-has-failures={totalFailed > 0 ? "" : undefined}
    >
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

        {vessels.length > 0 ? (
          <>
            <p className="mon-micro">
              <Hinted hint={RULE_SCOPE_HINTS.vessels}>Per vessel</Hinted>
            </p>
            <div className="frame-list-stack">
              {vessels.map((group) => (
                <RuleGroup
                  key={group.actorId}
                  heading={renderActorName(group.actorName)}
                  evaluations={group.evaluations}
                  emptyText="No rules active for this vessel."
                  showSubject={false}
                  showAll={showAll}
                  onShowAll={showAllRules}
                />
              ))}
            </div>
            <p className="mon-micro">
              <Hinted hint={RULE_SCOPE_HINTS.encounters}>Per encounter</Hinted>
            </p>
          </>
        ) : null}

        <div className="frame-list-stack">
          {encounters.map((group, groupIndex) => (
            <RuleGroup
              key={`${group.relationId}-${groupIndex}`}
              heading={renderRelationId(group.relationId)}
              situationLabel={situationLabelByRelation.get(group.relationId)}
              evaluations={group.evaluations}
              emptyText="No rules active for this encounter."
              showSubject
              showAll={showAll}
              onShowAll={showAllRules}
            />
          ))}
        </div>
      </div>
    </PersistedDetails>
  );
}
