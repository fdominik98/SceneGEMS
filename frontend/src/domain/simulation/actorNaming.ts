/**
 * How the backend names a scenario's actors (`functional_level/models/object_generator.py`): the own
 * ship is "os", a target "ts<n>" and a static obstacle "so<n>", each counted from 1 within its id
 * range. The ranges never overlap (the own ship 0, targets 1 to 99, obstacles from 100), so an id
 * stays unique while the names read as in the paper's figures.
 */
export const OS_ID = 0;
export const FIRST_TS_ID = 1;
export const FIRST_OBSTACLE_ID = 100;

export function vesselName(id: number, isOwnShip: boolean): string {
  return isOwnShip ? "os" : `ts${id - FIRST_TS_ID + 1}`;
}

export function obstacleName(id: number): string {
  return `so${id >= FIRST_OBSTACLE_ID ? id - FIRST_OBSTACLE_ID + 1 : id}`;
}

/**
 * An actor's name from its id as the backend gives it; an id that is no number (a hand-made file)
 * takes the next number of its kind instead.
 */
export function createActorNamer(): (id: string, kind: { isOwnShip: boolean; isVessel: boolean }) => string {
  let targets = 0;
  let obstacles = 0;
  return (id, { isOwnShip, isVessel }) => {
    const numeric = /^\d+$/.test(id) ? Number(id) : null;
    if (!isVessel) {
      obstacles += 1;
      return numeric !== null ? obstacleName(numeric) : `so${obstacles}`;
    }
    if (isOwnShip) {
      return "os";
    }
    targets += 1;
    return numeric !== null ? vesselName(numeric, false) : `ts${targets}`;
  };
}

/** A vessel's name from its actor id: os, or ts<n> for a numeric id; another id is shown as it is. */
export function vesselNameOf(id: string, isOwnShip: boolean): string {
  if (isOwnShip) {
    return "os";
  }
  return /^\d+$/.test(id) ? vesselName(Number(id), false) : id;
}

/** What a vessel is, written out next to its name. */
export function vesselRole(isOwnShip: boolean): string {
  return isOwnShip ? "own ship" : "target ship";
}
