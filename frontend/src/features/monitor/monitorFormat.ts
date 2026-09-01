import type { ActorStaticInfo } from "../../domain/simulation/types";

export type Tone = "neutral" | "danger" | "good" | "warn" | "info";

export function fmtNum(value: unknown, decimals = 1): string {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return "-";
  }
  if (Number.isInteger(value)) {
    return String(value);
  }
  return value.toFixed(decimals);
}

/** "COURSE_CHANGE_TO_THE_LEFT" -> "Course change to the left". */
export function humanizeEnum(value: string): string {
  if (!value) {
    return "-";
  }
  const spaced = value.replace(/[_-]+/g, " ").trim().toLowerCase();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function resolveActorLabel(actors: ActorStaticInfo[], id: string): string {
  const hit = actors.find((a) => a.id === id);
  return hit?.name ?? id;
}

/** Word for an avoidance / turn direction enum. */
export function directionWord(dir: string | undefined): string {
  switch ((dir ?? "").toUpperCase()) {
    case "RIGHT":
    case "STARBOARD":
    case "COURSE_CHANGE_TO_THE_RIGHT":
      return "Starboard";
    case "LEFT":
    case "PORT":
    case "COURSE_CHANGE_TO_THE_LEFT":
      return "Port";
    case "FORWARD":
    case "PERSISTING_COURSE":
      return "Ahead";
    case "BACKWARD":
      return "Astern";
    case "NONE":
    case "":
    case "UNDETECTED":
      return "-";
    default:
      return humanizeEnum(dir ?? "");
  }
}
