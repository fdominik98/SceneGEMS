/**
 * The geometry the problem graphs' edges share (pure): where a line between two cards leaves and
 * meets them, how parallel edges between the same two cards bow apart, and how an edge from a card
 * to itself loops out of the card's right side.
 */

export interface Point {
  x: number;
  y: number;
}

export interface Box extends Point {
  width: number;
  height: number;
}

/** Between two edges that join the same two cards. */
export const PARALLEL_SPACING = 40;
/** How far a loop reaches right of its card, and the room to its right for its label. */
export const LOOP_REACH = 44;
export const LOOP_ROOM = 170;
/** The height each loop on a card needs. */
export const LOOP_HEIGHT = 26;

export type EdgePlacement = { kind: "line"; offset: number } | { kind: "loop"; index: number; count: number };

/** How each edge is drawn: a self edge as one of its card's loops, others bowed apart from the other edges between the same two cards. */
export function placeEdges(edges: readonly { id: string; source: string; target: string }[]): Map<string, EdgePlacement> {
  const groups = new Map<string, string[]>();
  for (const edge of edges) {
    const key = edge.source === edge.target ? `loop\u0000${edge.source}` : [edge.source, edge.target].sort().join("\u0000");
    groups.set(key, [...(groups.get(key) ?? []), edge.id]);
  }
  const placement = new Map<string, EdgePlacement>();
  for (const [key, ids] of groups) {
    ids.forEach((id, index) => {
      placement.set(id, key.startsWith("loop\u0000") ? { kind: "loop", index, count: ids.length } : { kind: "line", offset: (index - (ids.length - 1) / 2) * PARALLEL_SPACING });
    });
  }
  return placement;
}

/** How many loops each card has, for its height and the room right of it. */
export function loopCounts(edges: readonly { source: string; target: string }[]): Map<string, number> {
  const counts = new Map<string, number>();
  for (const edge of edges) {
    if (edge.source === edge.target) {
      counts.set(edge.source, (counts.get(edge.source) ?? 0) + 1);
    }
  }
  return counts;
}

function center(box: Box): Point {
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

/** Where the line from the box's center toward a point leaves the box. */
export function borderPoint(box: Box, toward: Point): Point {
  const c = center(box);
  const dx = toward.x - c.x;
  const dy = toward.y - c.y;
  if (dx === 0 && dy === 0) {
    return c;
  }
  const scale = Math.min(dx === 0 ? Infinity : box.width / 2 / Math.abs(dx), dy === 0 ? Infinity : box.height / 2 / Math.abs(dy));
  return { x: c.x + dx * scale, y: c.y + dy * scale };
}

export interface EdgeShape {
  path: string;
  labelX: number;
  labelY: number;
  /** The point at a share (0 to 1) of the way from the source to the target. */
  at: (share: number) => Point;
}

/**
 * A line between two cards, bowed by `offset` to the side. The side is taken in the order of the two
 * ids, so the edges in both directions between the same cards bow apart rather than onto each other.
 */
export function linePath(source: Box, target: Box, offset: number, sourceFirst: boolean): EdgeShape {
  const a = center(source);
  const b = center(target);
  const length = Math.hypot(b.x - a.x, b.y - a.y) || 1;
  // The normal of the line in the order of the ids
  const sign = sourceFirst ? 1 : -1;
  const nx = (-(b.y - a.y) / length) * sign;
  const ny = ((b.x - a.x) / length) * sign;
  const control = { x: (a.x + b.x) / 2 + nx * offset * 2, y: (a.y + b.y) / 2 + ny * offset * 2 };
  const start = borderPoint(source, offset === 0 ? b : control);
  const end = borderPoint(target, offset === 0 ? a : control);
  if (offset === 0) {
    const at = (share: number) => ({ x: start.x + (end.x - start.x) * share, y: start.y + (end.y - start.y) * share });
    return { path: `M ${start.x},${start.y} L ${end.x},${end.y}`, labelX: (start.x + end.x) / 2, labelY: (start.y + end.y) / 2, at };
  }
  const at = (share: number) => {
    const rest = 1 - share;
    return { x: rest * rest * start.x + 2 * rest * share * control.x + share * share * end.x, y: rest * rest * start.y + 2 * rest * share * control.y + share * share * end.y };
  };
  // The middle of the quadratic curve
  const middle = at(0.5);
  return { path: `M ${start.x},${start.y} Q ${control.x},${control.y} ${end.x},${end.y}`, labelX: middle.x, labelY: middle.y, at };
}

/** One of a card's loops: out of its right side and back, the label right of the loop's far end. */
export function loopPath(box: Box, index: number, count: number): EdgeShape {
  const right = box.x + box.width;
  const step = box.height / (count + 1);
  const middle = box.y + step * (index + 1);
  const half = Math.min(9, step / 2 - 2);
  const top = middle - half;
  const bottom = middle + half;
  const reach = right + LOOP_REACH;
  return {
    path: `M ${right},${top} C ${reach},${top - 14} ${reach},${bottom + 14} ${right},${bottom}`,
    labelX: right + LOOP_REACH - 8,
    labelY: middle,
    at: (share: number) => ({ x: right + LOOP_REACH * Math.sin(Math.PI * share) * 0.75, y: top + (bottom - top) * share }),
  };
}
