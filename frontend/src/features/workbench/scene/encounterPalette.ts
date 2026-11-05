import type { RuleResult } from "../../../domain/simulation/types";
import type { VesselRole } from "../monitor/encounterPairs";

/**
 * Colors of the encounter canvas, cards and timeline, as theme tokens (`theme.css`). A screenshot
 * rasterizes the SVG on its own, so `sceneExport` writes the tokens' values into it first.
 */
export const CANVAS_COLORS = {
  sea: "var(--canvas-sea)",
  ring: "var(--canvas-ring)",
  ringLabel: "var(--canvas-ring-label)",
  bearingTick: "var(--canvas-bearing-tick)",
  bearingLabel: "var(--canvas-bearing-label)",
  hullStroke: "var(--canvas-hull-stroke)",
  labelText: "var(--canvas-label-text)",
  labelMuted: "var(--canvas-label-muted)",
  labelBackground: "var(--canvas-label-bg)",
  selection: "var(--canvas-selection)",
  cpaNeutral: "var(--canvas-cpa-neutral)",
  cpaWarn: "var(--canvas-cpa-warn)",
  cpaDanger: "var(--canvas-cpa-danger)",
  legendBackground: "var(--canvas-legend-bg)",
  legendBorder: "var(--canvas-legend-border)",
  /** An actor without a color of its own. */
  fallback: "var(--canvas-fallback)",
} as const;

export const CANVAS_FONT = '"IBM Plex Sans", "Segoe UI", Helvetica, sans-serif';

/** The same in both modes: the role chips carry dark text on these fills. */
export const ROLE_COLORS: Record<VesselRole, string> = {
  "give-way": "#f59e0b",
  "stand-on": "#60a5fa",
};

export const ROLE_CODES: Record<VesselRole, string> = {
  "give-way": "GW",
  "stand-on": "SO",
};

export const RESULT_COLORS: Record<RuleResult, string> = {
  FAILED: "var(--result-failed)",
  UNKNOWN: "var(--result-unknown)",
  PASSED: "var(--result-passed)",
};

export const RESULT_LABELS: Record<RuleResult, string> = {
  FAILED: "failed",
  UNKNOWN: "not applicable yet",
  PASSED: "passed",
};

/** Encounter type colors on the timeline's encounter row. */
export function encounterColor(situationType: string): string {
  const type = situationType.toUpperCase();
  if (type === "HEAD_ON") return "var(--encounter-head-on)";
  if (type.startsWith("TWO_WAY")) return "var(--encounter-two-way)";
  if (type.startsWith("CROSSING")) return "var(--encounter-crossing)";
  if (type.startsWith("OVERTAKING")) return "var(--encounter-overtaking)";
  return "var(--encounter-none)";
}
