/** Top-level frame keys handled in structured sections; anything else is shown under “More”. */
export const FRAME_STRUCTURE_KEYS = new Set([
  "timestamp",
  "timeStep",
  "actors",
  "statesByActorId",
  "trajectoriesByActorId",
  "situationContexts",
  "colregsStates",
  "ruleResults",
  "maneuverStates",
  "metrics",
]);

/** Preferred column order for vessel / actor static fields (unknown keys sort after). */
export const ACTOR_FIELD_PRIORITY = [
  "id",
  "name",
  "type",
  "isVessel",
  "isOwnShip",
  "length",
  "breadth",
  "height",
  "draft",
  "blockCoefficient",
  "mass",
  "safetyRadius",
  "maxSpeed",
  "maxAngularSpeed",
  "maxAcceleration",
  "steeringType",
  "rudderMass",
  "rudderLength",
  "rudderWidth",
  "rudderHeight",
  "propellerDiameter",
  "thrusterMass",
  "motorLength",
] as const;

export const KINEMATIC_FIELD_PRIORITY = ["x", "y", "speed", "heading"] as const;

/** An actor's static fields as the panel shows them: the steering type in words ("vectored thrust"). */
export function actorDisplayFields(actor: Record<string, unknown>): Record<string, unknown> {
  const steeringType = actor.steeringType;
  if (typeof steeringType !== "string") {
    return actor;
  }
  return { ...actor, steeringType: steeringType.replace(/_/g, " ") };
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

export function humanizeKey(key: string): string {
  const spaced = key
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .trim();
  if (spaced.length === 0) {
    return key;
  }
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function sortKeys(keys: string[], priority: readonly string[]): string[] {
  const pSet = new Set(priority);
  const ordered = priority.filter((k) => keys.includes(k));
  const rest = keys.filter((k) => !pSet.has(k)).sort((a, b) => a.localeCompare(b));
  return [...ordered, ...rest];
}

function formatNumber(n: number): string {
  if (!Number.isFinite(n)) {
    return String(n);
  }
  if (Number.isInteger(n) && Math.abs(n) < 1e9) {
    return String(n);
  }
  if (Math.abs(n) >= 1e4 || (Math.abs(n) > 0 && Math.abs(n) < 1e-3)) {
    return n.toExponential(3);
  }
  const s = n.toFixed(4).replace(/\.?0+$/, "");
  return s === "-0" ? "0" : s;
}

export function formatScalar(value: unknown): string {
  if (value === null || value === undefined) {
    return "-";
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  if (typeof value === "number") {
    return formatNumber(value);
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "bigint") {
    return value.toString();
  }
  return "";
}
