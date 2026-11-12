import { formatIsoDateTime } from "../../domain/localDateTime";
/** Formatting helpers of the Results section. */

/** Seconds as `12.5 s`, or `1 min 05 s` from a minute on; a dash for no value. */
export function formatSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "-";
  }
  if (Math.abs(value) < 60) {
    return `${Number(value.toFixed(2))} s`;
  }
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value - minutes * 60);
  return `${minutes} min ${String(seconds).padStart(2, "0")} s`;
}

export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  const units = ["KiB", "MiB", "GiB"];
  let scaled = value / 1024;
  let unit = 0;
  while (scaled >= 1024 && unit < units.length - 1) {
    scaled /= 1024;
    unit += 1;
  }
  return `${scaled.toFixed(scaled < 10 ? 1 : 0)} ${units[unit]}`;
}

export function shortHash(value: string | null | undefined, length = 10): string {
  if (!value) {
    return "-";
  }
  return value.length <= length ? value : value.slice(0, length);
}

/** An ISO time as `2026-10-26 09:00:05` in the browser's zone. */
export function formatTime(iso: string | null | undefined): string {
  return formatIsoDateTime(iso, "-");
}

/** A pipeline stage as the page names it; the API calls the last stage, where the case has its monitor result summaries, `verdict`. */
export function stageLabel(stage: string): string {
  return stage === "verdict" ? "monitor result summary" : stage.replace("_", " ");
}

/** The last part of a class id (`folder/name`) with the folder kept short. */
export function shortClassId(classId: string, maxLength = 42): string {
  return classId.length <= maxLength ? classId : `...${classId.slice(classId.length - maxLength + 3)}`;
}

/** `repeat 2 of run 1` style label of a run and its repeat. */
export function runLabel(runIndex: number | null, repeatIndex?: number | null): string {
  if (runIndex === null) {
    return "-";
  }
  // Counted from 1 for people, as Campaign History and the workbench count them.
  return repeatIndex === null || repeatIndex === undefined ? `run ${runIndex + 1}` : `run ${runIndex + 1}, repeat ${repeatIndex + 1}`;
}

/** A case's number for people: its index in the class counted from 1. */
export function caseNumber(caseIndex: number): number {
  return caseIndex + 1;
}

/** A compact text of a record's stack (`kinematic usv_navigation`) from its JSON. */
export function describeStack(stack: Record<string, unknown>): string {
  const layer = typeof stack.simulation_layer === "string" ? stack.simulation_layer : null;
  const mode = typeof stack.mode === "string" ? stack.mode : null;
  const parts = [layer, mode].filter((part): part is string => part !== null);
  return parts.length > 0 ? parts.join(" ") : JSON.stringify(stack);
}

/** The roles of an artifact in a run record, the ones people look for first. */
const ARTIFACT_ORDER = ["state_log", "frames", "trajectory_data"];

export function sortedArtifacts(artifacts: Record<string, string>): [string, string][] {
  return Object.entries(artifacts).sort(([a], [b]) => {
    const ia = ARTIFACT_ORDER.indexOf(a);
    const ib = ARTIFACT_ORDER.indexOf(b);
    if (ia !== ib) {
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib);
    }
    return a.localeCompare(b);
  });
}

const EXTENSIONS: Record<string, string> = {
  "application/json": "json",
  "application/x-ndjson": "jsonl",
  "application/yaml": "yaml",
  "application/x-yaml": "yaml",
  "text/yaml": "yaml",
  "text/csv": "csv",
  "text/plain": "txt",
  "application/xml": "xml",
  "application/gzip": "gz",
  "application/zip": "zip",
};

/** The file name a downloaded artifact is saved as: its role and the start of its hash, with the extension of its media type when it is known. */
export function artifactFileName(role: string, sha256: string, mediaType: string): string {
  const type = mediaType.split(";")[0].trim().toLowerCase();
  const extension = EXTENSIONS[type] ?? (type.endsWith("+json") ? "json" : null);
  return `${role}-${sha256.slice(0, 12)}${extension ? `.${extension}` : ""}`;
}
