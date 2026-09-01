/**
 * Per-field shape guards. Each known monitor field gets a dedicated visualization
 * helper, but only when the data actually matches the expected shape. If a
 * different COLREGS monitor emits the field with other keys, the guard fails for
 * that field and `BasicActorInfoPanel` falls back to the general layout for it,
 * leaving the other fields' helpers untouched.
 */

function isObj(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function hasKeys(v: unknown, keys: string[]): boolean {
  if (!isObj(v)) {
    return false;
  }
  return keys.every((k) => k in v);
}

/** Non-empty array whose every item satisfies `pred`. */
function everyItem(arr: unknown, pred: (item: unknown) => boolean): boolean {
  return Array.isArray(arr) && arr.length > 0 && arr.every(pred);
}

export function looksLikeSituationContexts(arr: unknown): boolean {
  return everyItem(arr, (it) =>
    hasKeys(it, ["relationId", "situationType", "situationLabel", "isGiveWayByActorId"]),
  );
}

export function looksLikeColregsStates(arr: unknown): boolean {
  return everyItem(arr, (it) =>
    hasKeys(it, ["relationId", "actorsSeeEachOther", "actorsOnCollisionCourse"]),
  );
}

export function looksLikeManeuverStates(arr: unknown): boolean {
  return everyItem(arr, (it) => hasKeys(it, ["actorId", "maneuverType", "headingChangeDirection"]));
}

export function looksLikeMetrics(obj: unknown): boolean {
  if (!isObj(obj)) {
    return false;
  }
  return (
    "distanceByRelationId" in obj ||
    "dcpaByRelationId" in obj ||
    "tcpaByRelationId" in obj ||
    "scene" in obj ||
    "relations" in obj
  );
}
