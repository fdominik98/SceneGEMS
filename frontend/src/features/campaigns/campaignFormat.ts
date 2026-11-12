import { stringify } from "yaml";
import { formatIsoDateTime } from "../../domain/localDateTime";

/** Readable text for the Campaigns section's values. */

/** An ISO time as local date and time ("2026-10-26 09:58:05"), or "none" when there is none. */
export function formatDateTime(iso: string | null | undefined): string {
  return formatIsoDateTime(iso, "none");
}

/** The time of day of an ISO time, for a feed ("09:58:05"). */
export function formatClock(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) {
    return iso;
  }
  return at.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

/** A length of time in seconds as "45 s", "12 min 5 s", "3 h 20 min" or "2 d 4 h". */
export function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) {
    return "none";
  }
  const total = Math.round(seconds);
  if (total < 60) {
    return `${total} s`;
  }
  const minutes = Math.floor(total / 60);
  if (minutes < 60) {
    const rest = total % 60;
    return rest === 0 ? `${minutes} min` : `${minutes} min ${rest} s`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 48) {
    const rest = minutes % 60;
    return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
  }
  const days = Math.floor(hours / 24);
  const rest = hours % 24;
  return rest === 0 ? `${days} d` : `${days} d ${rest} h`;
}

/** How long a campaign has run: from its start to its end, or to `nowMs` while it has not finished; "not started" before. */
export function runDuration(startedAt: string | null, finishedAt: string | null, nowMs: number): string {
  if (!startedAt) {
    return "not started";
  }
  const start = Date.parse(startedAt);
  const end = finishedAt ? Date.parse(finishedAt) : nowMs;
  if (!Number.isFinite(start) || !Number.isFinite(end)) {
    return "none";
  }
  return formatDuration((end - start) / 1000);
}

/** The last path segment of a class id, with the folder kept when it is short: `3vessel_0obstacle_scenarios/fec5`. */
export function splitClassId(classId: string): { folder: string; name: string } {
  const slash = classId.lastIndexOf("/");
  return slash === -1 ? { folder: "", name: classId } : { folder: classId.slice(0, slash), name: classId.slice(slash + 1) };
}

export function percent(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

/** The config of a version as YAML text. */
export function configYaml(config: Record<string, unknown>): string {
  return stringify(config, { lineWidth: 0, indent: 2 });
}
