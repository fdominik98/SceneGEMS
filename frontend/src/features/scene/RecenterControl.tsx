import { useState, type ReactNode } from "react";

function CrosshairIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden focusable="false">
      <circle cx="12" cy="12" r="5" fill="none" stroke="currentColor" strokeWidth="1.75" />
      <path
        d="M12 3v4M12 17v4M3 12h4M17 12h4"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="12"
      height="12"
      aria-hidden
      focusable="false"
      className={open ? "recenter-chevron recenter-chevron--open" : "recenter-chevron"}
    >
      <path
        d="M9 6l6 6-6 6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

const CARTESIAN_LEGEND = (
  <>
    <span>X: left-right</span>
    <span>Y: down-up</span>
    <span>Z: outward-inward</span>
  </>
);

const NAUTICAL_LEGEND = (
  <>
    <span>X/Y local meters from geofence center</span>
    <span>Projected with UTM (WGS84)</span>
    <span>Map centered at selected geofence</span>
  </>
);

export type RecenterLegendMode = "cartesian" | "nautical";

interface RecenterControlProps {
  onRecenter: () => void;
  legendMode?: RecenterLegendMode;
  legend?: ReactNode;
  className?: string;
}

export function RecenterControl({
  onRecenter,
  legendMode,
  legend,
  className,
}: RecenterControlProps) {
  const [legendOpen, setLegendOpen] = useState(false);
  const legendContent =
    legend ?? (legendMode === "nautical" ? NAUTICAL_LEGEND : CARTESIAN_LEGEND);

  return (
    <div className={["recenter-control", className].filter(Boolean).join(" ")}>
      <div className="recenter-control-actions">
        <button
          type="button"
          className="recenter-btn"
          onClick={onRecenter}
          title="Recenter view"
          aria-label="Recenter view"
        >
          <CrosshairIcon />
        </button>
        <button
          type="button"
          className="recenter-legend-toggle"
          onClick={() => setLegendOpen((open) => !open)}
          aria-expanded={legendOpen}
          aria-label={legendOpen ? "Hide view legend" : "Show view legend"}
          title={legendOpen ? "Hide legend" : "Show legend"}
        >
          <ChevronIcon open={legendOpen} />
        </button>
      </div>
      {legendOpen ? <div className="recenter-legend">{legendContent}</div> : null}
    </div>
  );
}
