import type { DetailsHTMLAttributes, ReactNode } from "react";
import type { TrajectoryStream } from "../../app/uiStore";
import { useUiStore } from "../../app/uiStore";
import type { ActorStaticInfo } from "../../domain/simulation/types";
import { renderActorName } from "./actorNameFormat";
import { directionWord, fmtNum, resolveActorLabel, type Tone } from "./monitorFormat";

export function monitorSectionKey(stream: TrajectoryStream, section: string): string {
  return `monitor:${stream}:${section}`;
}

/**
 * Collapsible `details` whose open state is stored in `uiStore` (and localStorage).
 * Missing keys stay closed so monitor panels start collapsed.
 */
export function PersistedDetails({
  persistKey,
  defaultOpen = false,
  children,
  onToggle,
  ...rest
}: {
  persistKey: string;
  defaultOpen?: boolean;
} & DetailsHTMLAttributes<HTMLDetailsElement>) {
  const stored = useUiStore((s) => s.monitorSectionOpen[persistKey]);
  const open = stored ?? defaultOpen;
  const setMonitorSectionOpen = useUiStore((s) => s.setMonitorSectionOpen);
  return (
    <details
      {...rest}
      open={open}
      onToggle={(event) => {
        const next = event.currentTarget.open;
        if (next !== open) {
          setMonitorSectionOpen(persistKey, next);
        }
        onToggle?.(event);
      }}
    >
      {children}
    </details>
  );
}

/**
 * Collapsible subpanel shell, matching the other Frame data sections. Open state
 * is persisted per `persistKey` so leaving a page and returning restores it.
 */
export function MonitorSection({
  persistKey,
  title,
  badge,
  tone,
  defaultOpen = false,
  children,
}: {
  persistKey: string;
  title: string;
  badge?: ReactNode;
  tone?: "bad";
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <PersistedDetails
      persistKey={persistKey}
      className="frame-subpanel"
      defaultOpen={defaultOpen}
      data-has-failures={tone === "bad" ? "" : undefined}
    >
      <summary className="frame-subpanel-summary">
        <span>{title}</span>
        {badge !== undefined ? (
          <span
            className={`frame-subpanel-badge${tone === "bad" ? " frame-subpanel-badge--bad" : ""}`}
          >
            {badge}
          </span>
        ) : null}
      </summary>
      <div className="mon-section-body">{children}</div>
    </PersistedDetails>
  );
}

export function ActorTag({ actors, id }: { actors: ActorStaticInfo[]; id: string }) {
  return <span className="mon-actor-tag">{renderActorName(resolveActorLabel(actors, id))}</span>;
}

export function Chip({ label, tone = "neutral" }: { label: ReactNode; tone?: Tone }) {
  return <span className={`mon-chip mon-chip--${tone}`}>{label}</span>;
}

/**
 * Boolean as a chip. `tone` says which value is noteworthy:
 * - "danger": true is bad (red), false is muted
 * - "good":   true is good (green), false is muted
 * - "neutral": true is highlighted (blue), false is muted
 */
export function BoolChip({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: boolean;
  tone?: "neutral" | "danger" | "good";
}) {
  const activeTone = tone === "danger" ? "danger" : tone === "good" ? "good" : "info";
  return (
    <span
      className={`mon-bool-chip mon-bool-chip--${value ? activeTone : "off"}`}
      title={`${label}: ${value ? "yes" : "no"}`}
    >
      <span className="mon-bool-dot" />
      {label}
    </span>
  );
}

/** Compact yes/no dot for dense tables. */
export function BoolDot({
  value,
  tone = "neutral",
}: {
  value: boolean;
  tone?: "neutral" | "danger" | "good";
}) {
  const activeTone = tone === "danger" ? "danger" : tone === "good" ? "good" : "info";
  return (
    <span
      className={`mon-bool-dot mon-bool-dot--standalone mon-bool-dot--${value ? activeTone : "off"}`}
      title={value ? "yes" : "no"}
      aria-label={value ? "yes" : "no"}
    />
  );
}

export function StatTile({
  label,
  value,
  unit,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  tone?: Tone;
}) {
  return (
    <div className={`mon-tile mon-tile--${tone}`}>
      <span className="mon-tile-label">{label}</span>
      <span className="mon-tile-value">
        {value}
        {unit ? <span className="mon-tile-unit"> {unit}</span> : null}
      </span>
    </div>
  );
}

export function MiniBar({
  label,
  value,
  max,
  valueText,
  tone = "info",
}: {
  label: string;
  value: number;
  max: number;
  valueText?: string;
  tone?: Tone;
}) {
  const pct = max > 0 && Number.isFinite(value) ? Math.max(0, Math.min(1, value / max)) : 0;
  return (
    <div className="mon-bar">
      <div className="mon-bar-head">
        <span className="mon-bar-label">{label}</span>
        <span className="mon-bar-value meta">{valueText ?? `${fmtNum(value)} / ${fmtNum(max)}`}</span>
      </div>
      <div className="mon-bar-track">
        <div className={`mon-bar-fill mon-bar-fill--${tone}`} style={{ width: `${pct * 100}%` }} />
      </div>
    </div>
  );
}

export function DirectionBadge({ dir }: { dir: string | undefined }) {
  const word = directionWord(dir);
  const tone: Tone = word === "Starboard" ? "good" : word === "Port" ? "warn" : "neutral";
  return <span className={`mon-dir-badge mon-dir-badge--${tone}`}>{word}</span>;
}
