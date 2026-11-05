import { useMemo } from "react";
import { Background, BaseEdge, Controls, EdgeLabelRenderer, MarkerType, MiniMap, ReactFlow, type Edge, type EdgeProps, type EdgeTypes, type NodeChange, type NodeTypes } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useTheme } from "../../app/theme";
import { usePersistedState } from "../../app/usePersistedState";
import type { ArchitectureDocument } from "../../domain/cluster/architectureApi";
import { highlightFor, parallelIndex, shortId, words, type GraphView } from "./capabilitiesModel";
import { CONCRETE_WIDTH, META_WIDTH, concreteHeight, metaHeight } from "./cardSizes";
import { FullscreenButton } from "./FullscreenButton";
import { ConcreteNode, LaneBand, MetaNode, type ConcreteFlowNode, type LaneFlowNode, type MetaFlowNode } from "./GraphNodes";
import { laneBands, layoutGraph, type LayoutEdge, type LayoutNode } from "./graphLayout";
import type { FullscreenMode } from "./useFullscreen";

export type Selection = { kind: "node" | "edge"; id: string };

interface AdapterEdgeData extends Record<string, unknown> {
  label: string;
  tone: "available" | "planned" | "alternative" | "ruled-out" | "link";
  /** How far the curve bows from the straight line, to keep parallel adapters and their labels apart. */
  offset: number;
  dimmed: boolean;
  selected: boolean;
  onSelect: () => void;
}

type AdapterFlowEdge = Edge<AdapterEdgeData, "adapter">;

const NODE_TYPES: NodeTypes = { concrete: ConcreteNode, meta: MetaNode, lane: LaneBand };

const PARALLEL_SPACING = 30;
const MAX_LABEL = 26;

function clip(text: string): string {
  return text.length > MAX_LABEL ? `${text.slice(0, MAX_LABEL - 1)}…` : text;
}

/** A curve from one card's right edge to the next card's left edge; parallel adapters bow apart so their labels do not overlap. */
function AdapterEdge({ id, sourceX, sourceY, targetX, targetY, data, markerEnd }: EdgeProps<AdapterFlowEdge>) {
  if (!data) {
    return null;
  }
  const reach = Math.max(70, Math.abs(targetX - sourceX) * 0.45);
  const off = data.offset;
  const path = `M ${sourceX},${sourceY} C ${sourceX + reach},${sourceY + off} ${targetX - reach},${targetY + off} ${targetX},${targetY}`;
  const labelX = (sourceX + 3 * (sourceX + reach) + 3 * (targetX - reach) + targetX) / 8;
  const labelY = (sourceY + 3 * (sourceY + off) + 3 * (targetY + off) + targetY) / 8;
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} interactionWidth={24} className={`cap-edge cap-edge--${data.tone}${data.dimmed ? " is-dimmed" : ""}${data.selected ? " is-selected" : ""}`} />
      <EdgeLabelRenderer>
        <button
          type="button"
          className={`cap-edge-label cap-edge-label--${data.tone}${data.dimmed ? " is-dimmed" : ""}${data.selected ? " is-selected" : ""} nodrag nopan`}
          style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          onClick={data.onSelect}
          title={data.label}
        >
          {clip(words(data.label))}
        </button>
      </EdgeLabelRenderer>
    </>
  );
}

const EDGE_TYPES: EdgeTypes = { adapter: AdapterEdge };

interface Graph {
  layoutNodes: LayoutNode[];
  layoutEdges: LayoutEdge[];
}

function describeGraph(document: ArchitectureDocument, view: GraphView): Graph {
  if (view === "metamodel") {
    return {
      layoutNodes: document.metamodel_nodes.map((node) => ({ id: node.id, lane: node.lane, width: META_WIDTH, height: metaHeight() })),
      layoutEdges: document.metamodel_edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })),
    };
  }
  return {
    layoutNodes: document.nodes.map((node) => ({ id: node.id, lane: node.lane, width: CONCRETE_WIDTH, height: concreteHeight(node) })),
    layoutEdges: document.edges.map((edge) => ({ id: edge.id, source: edge.source, target: edge.target })),
  };
}

type Point = { x: number; y: number };

/** Where the operator dragged cards to, per document and view, kept per browser. */
type MovedCards = Record<string, Record<string, Point>>;

const SNAP = 12;
const NO_MOVES: Record<string, Point> = {};

/** The laid-out positions with the cards the operator moved put where they left them, and the lane bands around the result. */
function usePlacement(document: ArchitectureDocument, view: GraphView, moved: Record<string, Point>) {
  const graph = useMemo(() => describeGraph(document, view), [document, view]);
  const laid = useMemo(
    () =>
      layoutGraph(
        document.lanes.map((lane) => lane.id),
        graph.layoutNodes,
        graph.layoutEdges
      ),
    [document.lanes, graph]
  );
  return useMemo(() => {
    const positions = new Map(laid.positions);
    for (const [id, point] of Object.entries(moved)) {
      if (positions.has(id)) {
        positions.set(id, point);
      }
    }
    return { positions, bands: laneBands(document.lanes.map((lane) => lane.id), graph.layoutNodes, positions) };
  }, [document.lanes, graph, laid, moved]);
}

interface ArchitectureGraphProps {
  document: ArchitectureDocument;
  view: GraphView;
  selection: Selection | null;
  onSelect: (selection: Selection | null) => void;
  /** Draw the connections the design rules out (concrete view). */
  showRuledOut: boolean;
  /** Whether the graph and its detail panel fill the window or the screen. */
  fullscreen: FullscreenMode;
  onToggleFullscreen: () => void;
}

/** One document as a left-to-right graph: lanes as columns, cards as the layers or interfaces, curves as the adapters between them. */
export function ArchitectureGraph({ document, view, selection, onSelect, showRuledOut, fullscreen, onToggleFullscreen }: ArchitectureGraphProps) {
  const scope = `${document.id}:${view}`;
  const [movedCards, setMovedCards] = usePersistedState<MovedCards>("capabilities-positions", {});
  const moved = movedCards[scope] ?? NO_MOVES;
  const layout = usePlacement(document, view, moved);
  const movedCount = Object.keys(moved).length;
  const concrete = view === "concrete";
  const onNodesChange = (changes: NodeChange[]) => {
    const moves = changes.flatMap((change) => (change.type === "position" && change.position !== undefined ? [[change.id, change.position] as const] : []));
    if (moves.length > 0) {
      setMovedCards((current) => ({ ...current, [scope]: { ...current[scope], ...Object.fromEntries(moves) } }));
    }
  };
  const lit = useMemo(() => highlightFor(concrete ? document.edges : document.metamodel_edges, selection), [concrete, document, selection]);

  const theme = useTheme();
  const { nodes, edges } = useMemo(() => {
    const laneNodes: LaneFlowNode[] = layout.bands.map((band) => ({
      id: `lane:${band.lane}`,
      type: "lane",
      position: { x: band.x, y: band.y },
      style: { width: band.width, height: band.height },
      width: band.width,
      height: band.height,
      data: { lane: document.lanes.find((lane) => lane.id === band.lane) ?? { id: band.lane, label: band.lane, description: "" }, index: document.lanes.findIndex((lane) => lane.id === band.lane) },
      draggable: false,
      selectable: false,
      focusable: false,
      zIndex: -2,
    }));
    const cards: Array<ConcreteFlowNode | MetaFlowNode> = concrete
      ? document.nodes.map((node) => ({
          id: node.id,
          type: "concrete",
          position: layout.positions.get(node.id) ?? { x: 0, y: 0 },
          width: CONCRETE_WIDTH,
          height: concreteHeight(node),
          data: { node, height: concreteHeight(node), selected: selection?.kind === "node" && selection.id === node.id, dimmed: lit !== null && !lit.nodes.has(node.id) },
        }))
      : document.metamodel_nodes.map((node) => ({
          id: node.id,
          type: "meta",
          position: layout.positions.get(node.id) ?? { x: 0, y: 0 },
          width: META_WIDTH,
          height: metaHeight(),
          data: {
            node,
            height: metaHeight(),
            implementations: document.nodes.filter((item) => item.implements === node.id).length,
            selected: selection?.kind === "node" && selection.id === node.id,
            dimmed: lit !== null && !lit.nodes.has(node.id),
          },
        }));
    return { nodes: [...laneNodes, ...cards], edges: buildEdges(document, view, selection, lit, showRuledOut, onSelect) };
  }, [concrete, document, layout, lit, onSelect, selection, showRuledOut, view]);

  return (
    <div className="cap-graph" data-testid="architecture-graph">
      <Legend concrete={concrete} showRuledOut={showRuledOut} movedCount={movedCount} onReset={() => setMovedCards((current) => ({ ...current, [scope]: {} }))} />
      <div className="cap-graph-canvas">
      {/* A change of the full screen mode mounts the canvas anew, so it fits the graph into its new size. */}
      <ReactFlow
        key={`${document.id}:${view}:${fullscreen}`}
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        colorMode={theme}
        fitView
        fitViewOptions={{ padding: 0.08 }}
        minZoom={0.2}
        maxZoom={1.6}
        nodesDraggable
        snapToGrid
        snapGrid={[SNAP, SNAP]}
        onNodesChange={onNodesChange}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => {
          if (node.type !== "lane") {
            onSelect(selection?.kind === "node" && selection.id === node.id ? null : { kind: "node", id: node.id });
          }
        }}
        onEdgeClick={(_, edge) => onSelect({ kind: "edge", id: edge.id })}
        onPaneClick={() => onSelect(null)}
      >
        <Background gap={24} size={1} />
        <Controls showInteractive={false} position="bottom-left" />
        <MiniMap pannable zoomable className="cap-minimap" style={{ background: "var(--bg-pane)", width: 150, height: 96 }} nodeStrokeWidth={2} nodeColor={(node) => (node.type === "lane" ? "var(--graph-minimap-lane)" : "var(--accent)")} maskColor="rgb(var(--well-rgb) / 0.7)" />
      </ReactFlow>
      {/* Outside the canvas, so it keeps the keyboard focus when the canvas mounts anew. */}
      <FullscreenButton fullscreen={fullscreen !== "off"} onToggle={onToggleFullscreen} />
      </div>
    </div>
  );
}

function buildEdges(
  document: ArchitectureDocument,
  view: GraphView,
  selection: Selection | null,
  lit: ReturnType<typeof highlightFor>,
  showRuledOut: boolean,
  onSelect: (selection: Selection | null) => void
): AdapterFlowEdge[] {
  const arrow = (color: string) => ({ type: MarkerType.ArrowClosed, color, width: 18, height: 18 });
  if (view === "metamodel") {
    const placement = parallelIndex(document.metamodel_edges);
    return document.metamodel_edges.map((edge) => ({
      id: edge.id,
      type: "adapter",
      source: edge.source,
      target: edge.target,
      markerEnd: arrow("var(--accent-strong)"),
      data: {
        label: edge.label,
        tone: "link",
        offset: offsetOf(placement.get(edge.id)),
        dimmed: lit !== null && !lit.edges.has(edge.id),
        selected: selection?.kind === "edge" && selection.id === edge.id,
        onSelect: () => onSelect({ kind: "edge", id: edge.id }),
      },
    }));
  }
  const placement = parallelIndex(document.edges);
  const edges: AdapterFlowEdge[] = document.edges.map((edge) => {
    const tone = edge.status === "planned" ? "planned" : edge.default ? "available" : "alternative";
    return {
      id: edge.id,
      type: "adapter",
      source: edge.source,
      target: edge.target,
      markerEnd: arrow(tone === "planned" ? "var(--warn-bright)" : "var(--accent)"),
      data: {
        label: edge.label,
        tone,
        offset: offsetOf(placement.get(edge.id)),
        dimmed: lit !== null && !lit.edges.has(edge.id),
        selected: selection?.kind === "edge" && selection.id === edge.id,
        onSelect: () => onSelect({ kind: "edge", id: edge.id }),
      },
    };
  });
  if (showRuledOut) {
    document.unsupported.forEach((link) => {
      const id = `ruled-out:${link.source}>${link.target}`;
      edges.push({
        id,
        type: "adapter",
        source: link.source,
        target: link.target,
        markerEnd: arrow("var(--danger-bright)"),
        data: { label: `no: ${shortId(link.target)}`, tone: "ruled-out", offset: 0, dimmed: lit !== null, selected: selection?.kind === "edge" && selection.id === id, onSelect: () => onSelect({ kind: "edge", id }) },
      });
    });
  }
  return edges;
}

function offsetOf(placed: { index: number; count: number } | undefined): number {
  return placed === undefined ? 0 : (placed.index - (placed.count - 1) / 2) * PARALLEL_SPACING;
}

function Legend({ concrete, showRuledOut, movedCount, onReset }: { concrete: boolean; showRuledOut: boolean; movedCount: number; onReset: () => void }) {
  return (
    <ul className="cap-legend" aria-label="Legend">
      {concrete ? (
        <>
          <li>
            <span className="cap-legend-line cap-legend-line--available" /> adapter
          </li>
          <li>
            <span className="cap-legend-line cap-legend-line--alternative" /> alternative adapter
          </li>
          <li>
            <span className="cap-legend-line cap-legend-line--planned" /> planned
          </li>
          {showRuledOut && (
            <li>
              <span className="cap-legend-line cap-legend-line--ruled-out" /> ruled out
            </li>
          )}
          <li>
            <span className="cap-chip-measured cap-legend-dot" /> measured, otherwise declared
          </li>
        </>
      ) : (
        <>
          <li>
            <span className="cap-legend-line cap-legend-line--link" /> generic adapter or link
          </li>
          <li>Click a card or arrow for what an implementation must provide</li>
        </>
      )}
      <li className="cap-legend-edit">
        Drag cards to rearrange them
        {movedCount > 0 && (
          <button type="button" className="cap-link cap-legend-reset" onClick={onReset}>
            Reset layout
          </button>
        )}
      </li>
    </ul>
  );
}
