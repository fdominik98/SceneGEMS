import { counted, type ClassFeature, type Metamodel } from "../../../../domain/designSpace/problemModel";
import { LOOP_HEIGHT, LOOP_ROOM, loopCounts, type Point } from "./graphGeometry";

/**
 * The metamodel as a class diagram (pure): a card per class (also one a text only uses) with its
 * attributes and enum valued features inside, a card per enum with its literals, an edge from each
 * class to each superclass, and an edge per reference to another class. Two references that are each
 * other's opposite are one edge without a direction. Nothing here knows a class by its name.
 */

export const TONE_COUNT = 6;

export interface ClassRow {
  name: string;
  type: string;
  multiplicity: string | null;
}

export interface ClassCard {
  id: string;
  kind: "class";
  name: string;
  abstract: boolean;
  defined: boolean;
  superclasses: string[];
  rows: ClassRow[];
  /** The class's place among the classes, for its color; the model graph colors its objects the same way. */
  tone: number;
  width: number;
  height: number;
  /** The width the layout keeps free for it: the card and the labels of its loops. */
  layoutWidth: number;
}

export interface EnumCard {
  id: string;
  kind: "enum";
  name: string;
  literals: string[];
  width: number;
  height: number;
  layoutWidth: number;
}

export type MetaCard = ClassCard | EnumCard;

export type MetaEdgeKind = "extends" | "reference" | "contains";

export interface MetaEdge {
  id: string;
  source: string;
  target: string;
  kind: MetaEdgeKind;
  /** A pair of opposite references (or one that is its own opposite): no direction. */
  twoWay: boolean;
  /** Where a containment's diamond sits: at the class that contains. */
  diamond: "source" | "target" | null;
  label: string;
  /** For two opposite references between two classes: each name, drawn next to the class it leads to. */
  endLabels: { source: string; target: string } | null;
  /** The edge in a sentence, for its tooltip. */
  title: string;
}

export interface MetamodelGraph {
  cards: MetaCard[];
  edges: MetaEdge[];
}

export const CLASS_WIDTH = 232;
export const ENUM_WIDTH = 200;
const HEADER = 38;
const ROW = 20;
const PADDING = 14;

export const classId = (name: string) => `class:${name}`;
export const enumId = (name: string) => `enum:${name}`;

function withMultiplicity(name: string, multiplicity: string | null): string {
  return multiplicity === null ? name : `${name} [${multiplicity}]`;
}

/** The tone of each class by its place among the classes. */
export function classTones(metamodel: Metamodel): Map<string, number> {
  return new Map(metamodel.classes.map((item, index) => [item.name, index % TONE_COUNT]));
}

export function metamodelGraph(metamodel: Metamodel): MetamodelGraph {
  const classes = new Map(metamodel.classes.map((item) => [item.name, item]));
  const edges: MetaEdge[] = [];
  const consumed = new Set<ClassFeature>();
  // The opposite of each reference: the feature its `opposite` names in the class it leads to, or one there whose `opposite` names it
  const partners = new Map<ClassFeature, ClassFeature>();
  for (const owner of metamodel.classes) {
    for (const feature of owner.features) {
      if (feature.target !== "class" || feature.opposite === null || partners.has(feature)) {
        continue;
      }
      const partner = classes.get(feature.type)?.features.find((other) => other !== feature && other.name === feature.opposite && !partners.has(other));
      if (partner !== undefined) {
        partners.set(feature, partner);
        partners.set(partner, feature);
      }
    }
  }

  for (const owner of metamodel.classes) {
    for (const superclass of owner.superclasses) {
      if (classes.has(superclass)) {
        edges.push({
          id: `extends:${owner.name}>${superclass}`,
          source: classId(owner.name),
          target: classId(superclass),
          kind: "extends",
          twoWay: false,
          diamond: null,
          label: "",
          endLabels: null,
          title: `${owner.name} extends ${superclass}`,
        });
      }
    }
    for (const feature of owner.features) {
      if (feature.target !== "class" || consumed.has(feature)) {
        continue;
      }
      consumed.add(feature);
      const source = classId(owner.name);
      const target = classId(feature.type);
      const own = withMultiplicity(feature.name, feature.multiplicity);
      const id = `ref:${owner.name}.${feature.name}`;
      const partner = partners.get(feature);
      if (feature.opposite !== null || partner !== undefined) {
        if (partner !== undefined) {
          consumed.add(partner);
        }
        const oppositeName = partner?.name ?? (feature.opposite as string);
        const self = oppositeName === feature.name && feature.type === owner.name;
        const other = partner === undefined ? oppositeName : withMultiplicity(partner.name, partner.multiplicity);
        const containing = feature.kind === "contains" || partner?.kind === "container" ? "source" : feature.kind === "container" || partner?.kind === "contains" ? "target" : null;
        edges.push({
          id,
          source,
          target,
          kind: containing === null ? "reference" : "contains",
          twoWay: true,
          diamond: self ? null : containing,
          // Between two classes, the source's reference leads to the target, so its name sits at the target and the
          // opposite's at the source; a loop has one label
          label: self ? own : source === target ? `${own} / ${other}` : "",
          endLabels: source === target ? null : { source: other, target: own },
          title: self
            ? `${owner.name}.${feature.name} leads to ${feature.type} and is its own opposite`
            : `${owner.name}.${feature.name} leads to ${feature.type}; ${feature.type}.${oppositeName} is its opposite`,
        });
        continue;
      }
      edges.push({
        id,
        source,
        target,
        kind: feature.kind === "contains" || feature.kind === "container" ? "contains" : "reference",
        twoWay: false,
        diamond: feature.kind === "contains" ? "source" : feature.kind === "container" ? "target" : null,
        label: own,
        endLabels: null,
        title: feature.kind === "contains" ? `${owner.name} contains ${feature.type} through ${own}` : feature.kind === "container" ? `${owner.name} is contained in ${feature.type} (${own})` : `${owner.name}.${own} leads to ${feature.type}`,
      });
    }
  }

  const loops = loopCounts(edges);
  const tones = classTones(metamodel);
  const cards: MetaCard[] = [
    ...metamodel.classes.map((item): ClassCard => {
      const id = classId(item.name);
      const rows = item.features.filter((feature) => feature.target !== "class").map((feature) => ({ name: feature.name, type: feature.type, multiplicity: feature.multiplicity }));
      const loopCount = loops.get(id) ?? 0;
      const content = HEADER + (item.defined ? 0 : ROW) + rows.length * ROW + PADDING;
      return {
        id,
        kind: "class",
        name: item.name,
        abstract: item.abstract,
        defined: item.defined,
        superclasses: item.superclasses,
        rows,
        tone: tones.get(item.name) ?? 0,
        width: CLASS_WIDTH,
        height: Math.max(content, loopCount * LOOP_HEIGHT + PADDING),
        layoutWidth: CLASS_WIDTH + (loopCount > 0 ? LOOP_ROOM : 0),
      };
    }),
    ...metamodel.enums.map((item): EnumCard => ({
      id: enumId(item.name),
      kind: "enum",
      name: item.name,
      literals: item.literals,
      width: ENUM_WIDTH,
      height: HEADER + Math.max(1, item.literals.length) * ROW + PADDING,
      layoutWidth: ENUM_WIDTH,
    })),
  ];
  return { cards, edges };
}

/** "4 classes, 1 enum, 5 predicates, 7 constraints", then the other declarations a text has. */
export function metamodelSummary(metamodel: Metamodel): string {
  const constraints = metamodel.predicates.filter((item) => item.error).length;
  const parts = [
    counted(metamodel.classes.filter((item) => item.defined).length, "class", "classes"),
    counted(metamodel.enums.length, "enum"),
    counted(metamodel.predicates.length - constraints, "predicate"),
    counted(constraints, "constraint"),
  ];
  const kinds: [string, string, string][] = [
    ["datatype", "datatype", "datatypes"],
    ["function", "function", "functions"],
    ["rule", "rule", "rules"],
    ["aggregator", "aggregator", "aggregators"],
    ["primitive", "primitive", "primitives"],
    ["annotation", "annotation declaration", "annotation declarations"],
    ["import", "import", "imports"],
  ];
  for (const [kind, singular, plural] of kinds) {
    const count = metamodel.declarations.filter((item) => item.kind === kind).length;
    if (count > 0) {
      parts.push(counted(count, singular, plural));
    }
  }
  const used = metamodel.classes.filter((item) => !item.defined).length;
  if (used > 0) {
    parts.push(`${counted(used, "class", "classes")} used but not defined here`);
  }
  const module = metamodel.declarations.find((item) => item.kind === "module");
  return `${module !== undefined ? `Module ${module.name}: ` : ""}${parts.join(", ")}.`;
}

/** Superclasses over their subclasses. */
const ROW_GAP = 120;
const CARD_GAP = 48;
/** At most this many cards side by side; a longer layer goes on in a row below. */
export const MAX_PER_ROW = 6;
const SWEEPS = 4;

/**
 * Positions (top left) for the class diagram: layers by inheritance depth (a class one layer below
 * its deepest superclass), the order inside a layer from a few barycenter sweeps over all edges, a
 * layer wider than `MAX_PER_ROW` cards wrapped, every row centered, and the enums in rows below the
 * classes. The same graph always gives the same positions.
 */
export function layoutMetamodel(graph: MetamodelGraph): Map<string, Point> {
  const classes = graph.cards.filter((card): card is ClassCard => card.kind === "class");
  const enums = graph.cards.filter((card): card is EnumCard => card.kind === "enum");
  const byId = new Map(graph.cards.map((card) => [card.id, card]));
  const depth = new Map(classes.map((card) => [card.id, 0]));
  const supers = graph.edges.filter((edge) => edge.kind === "extends" && depth.has(edge.source) && depth.has(edge.target));
  for (let round = 0; round < classes.length; round++) {
    let changed = false;
    for (const edge of supers) {
      const next = (depth.get(edge.target) as number) + 1;
      if (next > (depth.get(edge.source) as number) && next < classes.length) {
        depth.set(edge.source, next);
        changed = true;
      }
    }
    if (!changed) {
      break;
    }
  }
  const deepest = Math.max(-1, ...depth.values());
  const layers: MetaCard[][] = Array.from({ length: deepest + 1 }, (_, level) => classes.filter((card) => depth.get(card.id) === level));

  const neighbors = new Map<string, string[]>();
  for (const edge of graph.edges) {
    if (edge.source !== edge.target && byId.has(edge.source) && byId.has(edge.target)) {
      neighbors.set(edge.source, [...(neighbors.get(edge.source) ?? []), edge.target]);
      neighbors.set(edge.target, [...(neighbors.get(edge.target) ?? []), edge.source]);
    }
  }
  const centers = new Map<string, number>();
  const layerOf = new Map<string, number>();
  const spread = (layer: MetaCard[]) => {
    const total = layer.reduce((sum, card) => sum + card.layoutWidth, 0) + CARD_GAP * (layer.length - 1);
    let x = -total / 2;
    for (const card of layer) {
      centers.set(card.id, x + card.width / 2);
      x += card.layoutWidth + CARD_GAP;
    }
  };
  layers.forEach((layer, index) => {
    layer.forEach((card) => layerOf.set(card.id, index));
    spread(layer);
  });
  const sweep = (index: number, above: boolean) => {
    const keyed = layers[index].map((card, position) => {
      const reached = (neighbors.get(card.id) ?? []).filter((id) => layerOf.has(id) && (above ? (layerOf.get(id) as number) < index : (layerOf.get(id) as number) > index));
      const mean = reached.length === 0 ? (centers.get(card.id) as number) : reached.reduce((sum, id) => sum + (centers.get(id) as number), 0) / reached.length;
      return { card, mean, position };
    });
    keyed.sort((a, b) => a.mean - b.mean || a.position - b.position);
    layers[index] = keyed.map((item) => item.card);
    spread(layers[index]);
  };
  for (let round = 0; round < SWEEPS; round++) {
    for (let index = 1; index < layers.length; index++) {
      sweep(index, true);
    }
    for (let index = layers.length - 2; index >= 0; index--) {
      sweep(index, false);
    }
  }

  const rows: MetaCard[][] = [];
  const wrap = (cards: MetaCard[]) => {
    for (let start = 0; start < cards.length; start += MAX_PER_ROW) {
      rows.push(cards.slice(start, start + MAX_PER_ROW));
    }
  };
  layers.forEach(wrap);
  wrap(enums);

  const positions = new Map<string, Point>();
  let y = 0;
  for (const row of rows) {
    const total = row.reduce((sum, card) => sum + card.layoutWidth, 0) + CARD_GAP * (row.length - 1);
    let x = -total / 2;
    for (const card of row) {
      positions.set(card.id, { x, y });
      x += card.layoutWidth + CARD_GAP;
    }
    y += Math.max(...row.map((card) => card.height)) + ROW_GAP;
  }
  return positions;
}
