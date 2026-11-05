import { useState, type ReactNode } from "react";
import type { RuleResult } from "../../../domain/simulation/types";
import {
  formatClock,
  formatDegrees,
  formatKnots,
  formatNm,
} from "../scene/encounterGeometry";
import { CANVAS_COLORS, RESULT_COLORS, RESULT_LABELS, ROLE_CODES, ROLE_COLORS } from "../scene/encounterPalette";
import { renderActorName } from "./actorNames";
import type { PairModel, PairRule, PairVessel } from "./encounterPairs";
import { directionWord, humanizeEnum } from "./monitorFormat";
import "./encounterPanel.css";

export interface PairCardListProps {
  pairs: PairModel[];
  colorByActorId: Record<string, string>;
  selectedRelationId?: string | null;
  onSelectRelation?: (relationId: string | null) => void;
  emptyMessage?: string;
}

const RESULT_GLYPH: Record<RuleResult, string> = { FAILED: "✕", PASSED: "✓", UNKNOWN: "·" };

function VesselName({ vessel, color }: { vessel: PairVessel; color: string | undefined }) {
  return (
    <span className="enc-vessel-name">
      <span className="enc-dot" style={{ backgroundColor: color ?? CANVAS_COLORS.fallback }} aria-hidden />
      {renderActorName(vessel.name)}
    </span>
  );
}

function RoleBadge({ vessel }: { vessel: PairVessel }) {
  if (!vessel.role) {
    return null;
  }
  return (
    <span
      className="enc-role"
      style={{ backgroundColor: ROLE_COLORS[vessel.role] }}
      title={`${vessel.name} is the ${vessel.role} vessel`}
    >
      {ROLE_CODES[vessel.role]}
    </span>
  );
}

function RuleChip({ rule }: { rule: PairRule }) {
  const tooltip = [
    `${rule.ruleName}${rule.subjectActorName ? ` (${rule.subjectActorName})` : ""}: ${RESULT_LABELS[rule.result]}`,
    rule.firstFailure !== null ? `first failed at ${formatClock(rule.firstFailure)}` : null,
    rule.description || null,
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <span
      className={`enc-rule-chip enc-rule-chip--${rule.result.toLowerCase()}`}
      style={{ borderColor: RESULT_COLORS[rule.result] }}
      title={tooltip}
    >
      <span className="enc-rule-glyph" style={{ color: RESULT_COLORS[rule.result] }} aria-hidden>
        {RESULT_GLYPH[rule.result]}
      </span>
      <span className="enc-rule-tag">{rule.tag}</span>
      {rule.subjectActorName ? <span className="enc-rule-subject">{renderActorName(rule.subjectActorName)}</span> : null}
      {rule.result === "FAILED" && rule.firstFailure !== null ? (
        <span className="enc-rule-since">{formatClock(rule.firstFailure)}</span>
      ) : null}
      <span className="enc-sr-only">{RESULT_LABELS[rule.result]}</span>
    </span>
  );
}

function cpaText(pair: PairModel): string {
  if (pair.dcpa === null) {
    return "-";
  }
  if (pair.tcpa === null) {
    return `${formatNm(pair.dcpa)}, range steady`;
  }
  if (pair.tcpa <= 0) {
    return "passed, opening";
  }
  return `${formatNm(pair.dcpa)} in ${formatClock(pair.tcpa)}`;
}

function bearingText(vessel: PairVessel): string {
  if (vessel.bearingToOther === null || vessel.relativeBearingToOther === null) {
    return "-";
  }
  return `${formatDegrees(vessel.bearingToOther)} (${vessel.sectorOfOther})`;
}

function Flag({ on, label, tone }: { on: boolean; label: string; tone: "danger" | "warn" | "info" }) {
  if (!on) {
    return null;
  }
  return <span className={`enc-flag enc-flag--${tone}`}>{label}</span>;
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function maneuverText(vessel: PairVessel): string {
  const m = vessel.maneuver;
  if (!m) {
    return "-";
  }
  const turn = m.headingDiffSinceStartDeg;
  const parts = [
    humanizeEnum(m.maneuverType),
    `${m.maneuverCount} maneuver${m.maneuverCount === 1 ? "" : "s"}`,
    `${turn > 0 ? "+" : ""}${turn.toFixed(1)}° since start`,
  ];
  return parts.join(", ");
}

function PairDetails({ pair }: { pair: PairModel }) {
  const colregs = pair.colregs;
  const context = pair.context;
  return (
    <div className="enc-details">
      <dl className="enc-details-grid">
        {context ? (
          <>
            <DetailRow label="Encounter since">
              {formatClock(context.startTimestamp)} ({formatClock(context.timeSpentInCurrentContext)} in it)
            </DetailRow>
            <DetailRow label="Judged side">
              {pair.a.name} {directionWord(pair.a.avoidance ?? undefined)}, {pair.b.name}{" "}
              {directionWord(pair.b.avoidance ?? undefined)}
            </DetailRow>
          </>
        ) : null}
        <DetailRow label={`${pair.a.name} course`}>
          {pair.a.courseDeg === null ? "-" : `${formatDegrees(pair.a.courseDeg)}, ${formatKnots(pair.a.speed ?? 0)}`}
        </DetailRow>
        <DetailRow label={`${pair.b.name} course`}>
          {pair.b.courseDeg === null ? "-" : `${formatDegrees(pair.b.courseDeg)}, ${formatKnots(pair.b.speed ?? 0)}`}
        </DetailRow>
        <DetailRow label={`${pair.a.name} from ${pair.b.name}`}>{bearingText(pair.b)}</DetailRow>
        <DetailRow label="Safety distance">{pair.safetyDistance === null ? "-" : formatNm(pair.safetyDistance)}</DetailRow>
        <DetailRow label="Visibility distance">
          {pair.visibilityDistance === null ? "-" : formatNm(pair.visibilityDistance)}
          {colregs?.visibilityDistance ? ` (${colregs.visibilityDistance === "at" ? "at the band" : colregs.visibilityDistance === "in" ? "within" : "beyond"})` : ""}
        </DetailRow>
        <DetailRow label="CPA source">
          {pair.cpaSource === "monitor" ? "monitor metrics" : pair.cpaSource === "computed" ? "computed from the states" : "-"}
        </DetailRow>
        <DetailRow label={`${pair.a.name} maneuver`}>{maneuverText(pair.a)}</DetailRow>
        <DetailRow label={`${pair.b.name} maneuver`}>{maneuverText(pair.b)}</DetailRow>
        {colregs ? (
          <DetailRow label="Monitor state">
            {[
              colregs.actorsSeeEachOther ? "see each other" : "not in sight",
              colregs.actorsOnCollisionCourse ? "collision course" : null,
              colregs.actorsHaveLowTcpa ? "low TCPA" : null,
              colregs.actorsViolateSafetyDomain ? "safety domain violated" : null,
              colregs.actorsPassedEachOther ? "passed each other" : null,
            ]
              .filter(Boolean)
              .join(", ")}
          </DetailRow>
        ) : null}
      </dl>
      {pair.rules.length > 0 ? (
        <ul className="enc-details-rules">
          {pair.rules.map((rule) => (
            <li key={rule.key}>
              <span className="enc-rule-glyph" style={{ color: RESULT_COLORS[rule.result] }} aria-hidden>
                {RESULT_GLYPH[rule.result]}
              </span>
              <span>
                <strong>
                  {rule.tag}
                  {rule.subjectActorName ? ` ${rule.subjectActorName}` : ""}
                </strong>{" "}
                {rule.title}
                <span className="enc-muted">
                  {" "}
                  {RESULT_LABELS[rule.result]}
                  {rule.firstFailure !== null ? `, first failed at ${formatClock(rule.firstFailure)}` : ""}
                </span>
                {rule.description ? <span className="enc-rule-description">{rule.description}</span> : null}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {pair.rules.length === 0 ? <p className="enc-muted">No rules evaluated for this pair yet.</p> : null}
    </div>
  );
}

function PairCard({
  pair,
  colorByActorId,
  selected,
  onSelect,
}: {
  pair: PairModel;
  colorByActorId: Record<string, string>;
  selected: boolean;
  onSelect?: () => void;
}) {
  const [open, setOpen] = useState(false);
  const rules = pair.rules.filter((rule) => rule.kind === "rule");
  const colregs = pair.colregs;
  return (
    <article
      className={`enc-card enc-card--${pair.severity}${selected ? " is-selected" : ""}`}
      aria-label={`${pair.a.name} and ${pair.b.name}`}
    >
      <header className="enc-card-head" onClick={onSelect} role={onSelect ? "button" : undefined} tabIndex={onSelect ? 0 : undefined}
        onKeyDown={(event) => {
          if (onSelect && (event.key === "Enter" || event.key === " ")) {
            event.preventDefault();
            onSelect();
          }
        }}
      >
        <span className="enc-card-vessels">
          <VesselName vessel={pair.a} color={colorByActorId[pair.a.id]} />
          <RoleBadge vessel={pair.a} />
          <span className="enc-muted" aria-hidden>
            and
          </span>
          <VesselName vessel={pair.b} color={colorByActorId[pair.b.id]} />
          <RoleBadge vessel={pair.b} />
        </span>
        <span className={`enc-type${pair.encounterActive ? "" : " enc-type--ended"}`}>
          {pair.encounterActive
            ? pair.encounterLabel
            : pair.previousEncounterLabel
              ? `${pair.previousEncounterLabel} ended`
              : "No encounter"}
        </span>
      </header>
      <dl className="enc-card-metrics">
        <div>
          <dt>Range</dt>
          <dd>{pair.range === null ? "-" : formatNm(pair.range)}</dd>
        </div>
        <div>
          <dt>Bearing</dt>
          <dd title={`${pair.b.name} seen from ${pair.a.name}, true bearing and sector`}>{bearingText(pair.a)}</dd>
        </div>
        <div>
          <dt>CPA</dt>
          <dd className={pair.tcpa !== null && pair.tcpa > 0 && pair.safetyDistance !== null && pair.dcpa !== null && pair.dcpa < pair.safetyDistance ? "enc-danger" : undefined}>
            {cpaText(pair)}
          </dd>
        </div>
      </dl>
      {colregs ? (
        <div className="enc-flags">
          <Flag on={colregs.actorsOnCollisionCourse} label="collision course" tone="danger" />
          <Flag on={colregs.actorsViolateSafetyDomain} label="in safety domain" tone="danger" />
          <Flag on={colregs.actorsHaveLowTcpa} label="low TCPA" tone="warn" />
          <Flag on={!colregs.actorsSeeEachOther} label="not in sight" tone="info" />
        </div>
      ) : null}
      {rules.length > 0 ? (
        <div className="enc-rules" aria-label="Rule states">
          {rules.map((rule) => (
            <RuleChip key={rule.key} rule={rule} />
          ))}
        </div>
      ) : null}
      <button type="button" className="enc-card-more" aria-expanded={open} onClick={() => setOpen(!open)}>
        {open ? "Hide details" : "Details"}
      </button>
      {open ? <PairDetails pair={pair} /> : null}
    </article>
  );
}

function QuietPairRow({
  pair,
  colorByActorId,
  selected,
  onSelect,
}: {
  pair: PairModel;
  colorByActorId: Record<string, string>;
  selected: boolean;
  onSelect?: () => void;
}) {
  return (
    <li>
      <button type="button" className={`enc-quiet-row${selected ? " is-selected" : ""}`} onClick={onSelect}>
        <VesselName vessel={pair.a} color={colorByActorId[pair.a.id]} />
        <VesselName vessel={pair.b} color={colorByActorId[pair.b.id]} />
        <span className="enc-muted">{pair.range === null ? "" : formatNm(pair.range)}</span>
        <span className="enc-muted">CPA {cpaText(pair)}</span>
      </button>
    </li>
  );
}

/**
 * One card per vessel pair that is or was in an encounter or has a failed rule; pairs that
 * never met are listed in one compact line each below. Selecting a card selects the pair on
 * the canvas and the timeline.
 */
export function PairCardList({
  pairs,
  colorByActorId,
  selectedRelationId = null,
  onSelectRelation,
  emptyMessage = "No vessel pairs in this frame.",
}: PairCardListProps) {
  if (pairs.length === 0) {
    return <p className="enc-muted enc-empty">{emptyMessage}</p>;
  }
  const prominent = pairs.filter((p) => p.encounterActive || p.previousEncounterLabel !== null || p.severity === "fail");
  const quiet = pairs.filter((p) => !prominent.includes(p));
  const select = (relationId: string) =>
    onSelectRelation ? () => onSelectRelation(relationId === selectedRelationId ? null : relationId) : undefined;
  return (
    <div className="enc-card-list">
      {prominent.map((pair) => (
        <PairCard
          key={pair.relationId}
          pair={pair}
          colorByActorId={colorByActorId}
          selected={pair.relationId === selectedRelationId}
          onSelect={select(pair.relationId)}
        />
      ))}
      {quiet.length > 0 ? (
        <section className="enc-quiet" aria-label="Pairs in no encounter">
          <h4>No encounter ({quiet.length})</h4>
          <ul>
            {quiet.map((pair) => (
              <QuietPairRow
                key={pair.relationId}
                pair={pair}
                colorByActorId={colorByActorId}
                selected={pair.relationId === selectedRelationId}
                onSelect={select(pair.relationId)}
              />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
