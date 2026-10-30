import { usePersistedState } from "../../../app/usePersistedState";
import type { Orientation } from "./encounterGeometry";

/** What the encounter canvas and the nautical map draw besides the vessel layers; kept per browser. */
export interface CanvasSettings {
  orientation: Orientation;
  vectorMinutes: number;
  rings: boolean;
  cpa: boolean;
  labels: boolean;
  legend: boolean;
}

export const DEFAULT_CANVAS_SETTINGS: CanvasSettings = {
  orientation: "north-up",
  vectorMinutes: 6,
  rings: true,
  cpa: true,
  labels: true,
  legend: true,
};

export const VECTOR_MINUTES = [1, 3, 6, 12, 30];

/** The chart toggles of the layer menu, in its order. */
export const CHART_TOGGLES: [keyof Pick<CanvasSettings, "rings" | "cpa" | "labels" | "legend">, string][] = [
  ["rings", "Range rings"],
  ["cpa", "CPA"],
  ["labels", "Labels"],
  ["legend", "Legend"],
];

/** The settings with every missing field (an older stored value) at its default. */
export function withCanvasDefaults(stored: Partial<CanvasSettings> | null | undefined): CanvasSettings {
  return { ...DEFAULT_CANVAS_SETTINGS, ...stored };
}

/** The canvas settings shared by the encounter canvas and the nautical map, and a patch setter. */
export function useCanvasSettings(): [CanvasSettings, (patch: Partial<CanvasSettings>) => void] {
  const [stored, setStored] = usePersistedState<CanvasSettings>("encounter-canvas", DEFAULT_CANVAS_SETTINGS);
  const update = (patch: Partial<CanvasSettings>) => setStored((prev) => ({ ...withCanvasDefaults(prev), ...patch }));
  return [withCanvasDefaults(stored), update];
}
