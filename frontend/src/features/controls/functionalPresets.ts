import { formatFunctionalPresetLabel } from "./functionalPresetPaths";

export interface FunctionalPresetEntry {
  path: string;
  label: string;
  fileName: string;
  folder: string;
  vesselCount: number | null;
  obstacleCount: number | null;
}

export interface FunctionalPresetsManifest {
  generatedAt: string;
  count: number;
  presets: FunctionalPresetEntry[];
}

const MANIFEST_URL = "/generated_functional_models/presets-manifest.json";

let cachedManifest: FunctionalPresetsManifest | null = null;

export async function loadFunctionalPresetsManifest(): Promise<FunctionalPresetsManifest> {
  if (cachedManifest) {
    return cachedManifest;
  }
  const response = await fetch(MANIFEST_URL);
  if (!response.ok) {
    throw new Error(`Failed to load presets manifest: ${response.status}`);
  }
  cachedManifest = (await response.json()) as FunctionalPresetsManifest;
  return cachedManifest;
}

export function filterPresets(
  presets: FunctionalPresetEntry[],
  query: string,
  vesselFilter: string,
  obstacleFilter: string
): FunctionalPresetEntry[] {
  const q = query.trim().toLowerCase();
  const vessel = vesselFilter === "any" ? null : Number(vesselFilter);
  const obstacle = obstacleFilter === "any" ? null : Number(obstacleFilter);

  return presets.filter((preset) => {
    if (vessel !== null && preset.vesselCount !== vessel) return false;
    if (obstacle !== null && preset.obstacleCount !== obstacle) return false;
    if (!q) return true;
    const label = formatFunctionalPresetLabel(preset.path).toLowerCase();
    return label.includes(q) || preset.path.toLowerCase().includes(q);
  });
}
