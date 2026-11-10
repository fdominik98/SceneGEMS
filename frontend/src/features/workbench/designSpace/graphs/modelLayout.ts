import { counted, describeLink, relationWords, type NodeFact, type NodeValue, type ReadProblem } from "../../../../domain/designSpace/problemModel";
import { LOOP_HEIGHT, LOOP_ROOM, loopCounts, type Point } from "./graphGeometry";
import { classTones } from "./metamodelLayout";

/**
 * A model as an object graph (pure): a card per object with its types, values and facts, an edge
 * per link. The metamodel part of the same text only says which names are classes and enum literals
 * (`problemModel.ts` reads both); its classes give the objects' colors by their place, never by name.
 */

export interface ModelCard {
  id: string;
  name: string;
  types: string[];
  possibleTypes: string[];
  values: NodeValue[];
  facts: NodeFact[];
  /** The tone of its first type, null for an object without one. */
  tone: number | null;
  width: number;
  height: number;
  layoutWidth: number;
}

export interface ModelEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  title: string;
  twoWay: boolean;
  possible: boolean;
}

export interface ModelGraph {
  cards: ModelCard[];
  edges: ModelEdge[];
}

export const OBJECT_WIDTH = 240; // a value row such as "vesselType: OSPassengerShip" fits
const NAME_ROW = 30; // the colored header
const ROW = 20;
const PADDING = 16;

export const objectId = (name: string) => `object:${name}`;

export function modelGraph(read: ReadProblem): ModelGraph {
  const tones = classTones(read.metamodel);
  const edges: ModelEdge[] = read.model.links.map((link, index) => ({
    id: `link:${index}`,
    source: objectId(link.source),
    target: objectId(link.target),
    label: link.relation,
    title: describeLink(link),
    twoWay: link.twoWay,
    possible: link.possible,
  }));
  const loops = loopCounts(edges);
  const cards = read.model.nodes.map((node): ModelCard => {
    const id = objectId(node.name);
    const loopCount = loops.get(id) ?? 0;
    const content = NAME_ROW + (node.types.length + node.possibleTypes.length + node.values.length + node.facts.length) * ROW + PADDING;
    const first = node.types[0] ?? node.possibleTypes[0];
    return {
      id,
      name: node.name,
      types: node.types,
      possibleTypes: node.possibleTypes,
      values: node.values,
      facts: node.facts,
      tone: first === undefined ? null : (tones.get(first) ?? null),
      width: OBJECT_WIDTH,
      height: Math.max(content, loopCount * LOOP_HEIGHT + PADDING),
      layoutWidth: OBJECT_WIDTH + (loopCount > 0 ? LOOP_ROOM : 0),
    };
  });
  return { cards, edges };
}

/** "4 objects, 3 links", then what the graph leaves out of the text's facts that may matter. */
export function modelSummary(read: ReadProblem): string {
  const { nodes, links, omitted, higherArityRelations } = read.model;
  const parts = [counted(nodes.length, "object"), counted(links.length, "link")];
  const possible = links.filter((link) => link.possible).length;
  if (possible > 0) {
    parts.push(`${possible} of them possible`);
  }
  let summary = `${parts.join(", ")}.`;
  if (omitted.higherArity > 0) {
    summary += ` ${counted(omitted.higherArity, "fact")} of more than two objects (${higherArityRelations.map(relationWords).join(", ")}) ${omitted.higherArity === 1 ? "is" : "are"} not drawn.`;
  }
  return summary;
}

/** Room between two cards, also between two rings. */
const GAP = 40;
/** The rings are ellipses this much lower than wide: a card is wide and low, and so is the pane the graph is drawn in. */
const FLATTEN = 0.5;
/** The room between two cards side by side, for the name of the link between them. */
const LABEL_ROOM = 110;

/**
 * Positions (top left) for the object graph: the object with the most links in the middle (the first
 * one on a tie), the others on rings by their distance from it in links, objects it cannot reach on
 * the outer ring. Inside a ring the objects follow the mean angle of their neighbors on the ring
 * within, so links stay short. The rings are flattened to ellipses (`FLATTEN`), which suits wide, low cards. Rings
 * and the places on a ring are far enough apart that no two cards overlap after the flattening, whatever their number. Names play no part: the same links give the same
 * picture.
 */
export function layoutModel(graph: ModelGraph): Map<string, Point> {
  const positions = new Map<string, Point>();
  const cards = graph.cards;
  if (cards.length === 0) {
    return positions;
  }
  const order = new Map(cards.map((card, index) => [card.id, index]));
  const neighbors = new Map<string, string[]>(cards.map((card) => [card.id, []]));
  for (const edge of graph.edges) {
    if (edge.source !== edge.target && order.has(edge.source) && order.has(edge.target)) {
      (neighbors.get(edge.source) as string[]).push(edge.target);
      (neighbors.get(edge.target) as string[]).push(edge.source);
    }
  }
  let middle = cards[0];
  for (const card of cards) {
    if ((neighbors.get(card.id) as string[]).length > (neighbors.get(middle.id) as string[]).length) {
      middle = card;
    }
  }
  const distance = new Map<string, number>([[middle.id, 0]]);
  const queue = [middle.id];
  while (queue.length > 0) {
    const id = queue.shift() as string;
    const next = [...new Set(neighbors.get(id))].sort((a, b) => (order.get(a) as number) - (order.get(b) as number));
    for (const other of next) {
      if (!distance.has(other)) {
        distance.set(other, (distance.get(id) as number) + 1);
        queue.push(other);
      }
    }
  }
  const reached = Math.max(...distance.values());
  const rings: string[][] = [];
  for (const card of cards) {
    const ring = distance.get(card.id) ?? reached + 1;
    (rings[ring] ??= []).push(card.id);
  }
  // Two places a step apart on a circle differ by a card's width across or, after the flattening, by its height down
  const step = Math.max(...cards.map((card) => Math.hypot(card.layoutWidth + LABEL_ROOM, card.height / FLATTEN))) + GAP;
  const angles = new Map<string, number>([[middle.id, 0]]);
  const centers = new Map<string, Point>([[middle.id, { x: 0, y: 0 }]]);
  let radius = 0;
  for (let index = 1; index < rings.length; index++) {
    const ring = rings[index] ?? [];
    if (ring.length === 0) {
      continue;
    }
    // The mean direction of a card's neighbors placed already; a card without one keeps its place in the order
    const keyed = ring.map((id, position) => {
      const placed = (neighbors.get(id) as string[]).filter((other) => angles.has(other) && other !== middle.id);
      if (placed.length === 0) {
        return { id, key: null as number | null, position };
      }
      const x = placed.reduce((sum, other) => sum + Math.cos(angles.get(other) as number), 0);
      const y = placed.reduce((sum, other) => sum + Math.sin(angles.get(other) as number), 0);
      return { id, key: Math.atan2(y, x), position };
    });
    const withKey = keyed.filter((item) => item.key !== null).sort((a, b) => (a.key as number) - (b.key as number) || a.position - b.position);
    const without = keyed.filter((item) => item.key === null);
    const sorted = [...withKey, ...without];
    const count = sorted.length;
    radius = Math.max(radius + step, count > 1 ? step / (2 * Math.sin(Math.PI / count)) : 0);
    const start = withKey.length > 0 ? (withKey[0].key as number) : count === 1 ? 0 : -Math.PI / 2;
    sorted.forEach((item, position) => {
      const angle = start + (2 * Math.PI * position) / count;
      angles.set(item.id, angle);
      centers.set(item.id, { x: radius * Math.cos(angle), y: FLATTEN * radius * Math.sin(angle) });
    });
  }
  for (const card of cards) {
    const c = centers.get(card.id) as Point;
    positions.set(card.id, { x: Math.round(c.x - card.width / 2), y: Math.round(c.y - card.height / 2) });
  }
  return positions;
}
