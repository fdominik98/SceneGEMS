import { createContext, useContext, useEffect, useId, type ReactNode } from "react";
import {
  Background,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  Position,
  ReactFlow,
  useInternalNode,
  useReactFlow,
  type Edge,
  type EdgeProps,
  type EdgeTypes,
  type InternalNode,
  type Node,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useTheme } from "../../../../app/theme";
import { Disclosure } from "../../../../components/Disclosure";
import { counted, type ProblemSyntax } from "../../../../domain/designSpace/problemModel";
import { linePath, loopPath, type Box, type EdgePlacement } from "./graphGeometry";
import "./problemGraphs.css";

/**
 * What the metamodel graph and the model graph share: the React Flow canvas (fit to the pane, zoom
 * and pan, no editing), one edge type that joins two cards from border to border (or loops a card to
 * itself) with its label, the markers of the line styles, the legend and the syntax error notice.
 */

export type EdgeStyle = "extends" | "reference" | "contains" | "link";

export interface ProblemEdgeData extends Record<string, unknown> {
  label: string;
  /** Names drawn near each end instead of one label in the middle (two opposite references). */
  endLabels?: { source: string; target: string } | null;
  title: string;
  style: EdgeStyle;
  twoWay: boolean;
  possible: boolean;
  diamond: "source" | "target" | null;
  placement: EdgePlacement;
}

export type ProblemFlowEdge = Edge<ProblemEdgeData, "problem">;

/** The ids of the markers of one canvas: two graphs can be on a page at once. */
interface Markers {
  arrow: string;
  triangle: string;
  diamond: string;
}

const MarkersContext = createContext<Markers>({ arrow: "", triangle: "", diamond: "" });

function boxOf(node: InternalNode | undefined): Box | null {
  if (node === undefined) {
    return null;
  }
  const width = node.measured?.width ?? node.width ?? 0;
  const height = node.measured?.height ?? node.height ?? 0;
  return { ...node.internals.positionAbsolute, width, height };
}

/** How far from its card an end label sits, as a share of the edge. */
const END_LABEL_SHARE = 0.22;

function ProblemEdge({ id, source, target, data }: EdgeProps<ProblemFlowEdge>) {
  const markers = useContext(MarkersContext);
  const from = boxOf(useInternalNode(source));
  const to = boxOf(useInternalNode(target));
  if (!data || from === null || to === null) {
    return null;
  }
  const loop = data.placement.kind === "loop";
  const shape = data.placement.kind === "loop" ? loopPath(from, data.placement.index, data.placement.count) : linePath(from, to, data.placement.offset, source < target);
  const url = (marker: string) => `url(#${marker})`;
  let markerStart: string | undefined;
  let markerEnd: string | undefined;
  if (data.style === "extends") {
    markerEnd = url(markers.triangle);
  } else {
    if (data.diamond === "source") {
      markerStart = url(markers.diamond);
    }
    if (data.diamond === "target") {
      markerEnd = url(markers.diamond);
    } else {
      markerEnd = url(markers.arrow);
    }
    // A link that holds both ways points both ways
    if (data.twoWay && data.diamond === null) {
      markerStart = url(markers.arrow);
    }
  }
  return (
    <>
      <BaseEdge id={id} path={shape.path} markerStart={markerStart} markerEnd={markerEnd} interactionWidth={0} className={`pg-edge pg-edge--${data.style}${data.possible ? " is-possible" : ""}`} />
      {data.label !== "" ? (
        <EdgeLabelRenderer>
          <div
            className={`pg-edge-label pg-edge-label--${data.style}${data.possible ? " is-possible" : ""} nodrag nopan`}
            style={{ transform: `translate(${loop ? "0" : "-50%"}, -50%) translate(${shape.labelX}px, ${shape.labelY}px)` }}
            title={data.title}
          >
            {data.label}
          </div>
        </EdgeLabelRenderer>
      ) : null}
      {data.endLabels ? (
        <EdgeLabelRenderer>
          {(["source", "target"] as const).map((end) => {
            const point = shape.at(end === "source" ? END_LABEL_SHARE : 1 - END_LABEL_SHARE);
            return (
              <div
                key={end}
                className={`pg-edge-label pg-edge-label--end pg-edge-label--${data.style} nodrag nopan`}
                style={{ transform: `translate(-50%, -50%) translate(${point.x}px, ${point.y}px)` }}
                title={data.title}
              >
                {data.endLabels?.[end]}
              </div>
            );
          })}
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}

const EDGE_TYPES: EdgeTypes = { problem: ProblemEdge };

/** The hidden handles every card has: the edges compute their own ends, React Flow only needs a handle to attach them to. */
export function CardHandles() {
  return (
    <>
      <Handle type="target" position={Position.Top} className="pg-handle" isConnectable={false} />
      <Handle type="source" position={Position.Top} className="pg-handle" isConnectable={false} />
    </>
  );
}

/** Fits the view again when the drawn cards change (another FEC, an edited specification). */
function FitOnChange({ signature }: { signature: string }) {
  const { fitView } = useReactFlow();
  useEffect(() => {
    const frame = requestAnimationFrame(() => void fitView({ padding: 0.12 }));
    return () => cancelAnimationFrame(frame);
  }, [fitView, signature]);
  return null;
}

function MarkerDefs({ markers }: { markers: Markers }) {
  return (
    <svg className="pg-markers" aria-hidden="true" width="0" height="0">
      <defs>
        <marker id={markers.arrow} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" orient="auto-start-reverse" markerUnits="userSpaceOnUse">
          <path d="M 0 0 L 10 5 L 0 10 z" className="pg-marker-fill" />
        </marker>
        <marker id={markers.triangle} viewBox="0 0 12 12" refX="11" refY="6" markerWidth="15" markerHeight="15" orient="auto-start-reverse" markerUnits="userSpaceOnUse">
          <path d="M 1 1 L 11 6 L 1 11 z" className="pg-marker-hollow" />
        </marker>
        <marker id={markers.diamond} viewBox="0 0 16 10" refX="15" refY="5" markerWidth="18" markerHeight="11" orient="auto-start-reverse" markerUnits="userSpaceOnUse">
          <path d="M 1 5 L 8 1 L 15 5 L 8 9 z" className="pg-marker-fill" />
        </marker>
      </defs>
    </svg>
  );
}

/** One line of the legend: a short sample of the line style and what it means. */
export function LegendLine({ style, marker, twoWay = false, possible = false, children }: { style: EdgeStyle; marker: "arrow" | "triangle" | "diamond" | "none"; twoWay?: boolean; possible?: boolean; children: ReactNode }) {
  const markers = useContext(MarkersContext);
  const end = marker === "none" ? undefined : `url(#${markers[marker]})`;
  const start = twoWay && marker === "arrow" ? end : undefined;
  return (
    <li>
      <svg className="pg-legend-sample" width="40" height="14" aria-hidden="true">
        <path d={twoWay ? "M 8 7 L 32 7" : "M 2 7 L 36 7"} className={`pg-edge pg-edge--${style}${possible ? " is-possible" : ""}`} markerStart={start} markerEnd={end} />
      </svg>
      <span>{children}</span>
    </li>
  );
}

/** "The text has 2 syntax errors, the first on line 3; the graph shows what could be read." */
export function SyntaxNotice({ syntax }: { syntax: ProblemSyntax }) {
  if (syntax.errorCount === 0) {
    return null;
  }
  return (
    <p className="meta warning pg-notice" role="status">
      The text has {counted(syntax.errorCount, "syntax error")}
      {syntax.firstErrorLine !== null ? `, the first on line ${syntax.firstErrorLine}` : ""}; the graph shows what could be read.
    </p>
  );
}

interface CanvasProps {
  /** The accessible name of the graph's region. */
  label: string;
  nodes: Node[];
  edges: ProblemFlowEdge[];
  nodeTypes: NodeTypes;
  /** The legend's lines (`LegendLine`), drawn with this canvas's markers. */
  legend: ReactNode;
}

/** The canvas with its legend; the cards and edges come laid out. */
export function ProblemGraphCanvas({ label, nodes, edges, nodeTypes, legend }: CanvasProps) {
  const theme = useTheme();
  const base = useId().replace(/[^A-Za-z0-9_-]/g, "");
  const markers: Markers = { arrow: `pg-arrow-${base}`, triangle: `pg-triangle-${base}`, diamond: `pg-diamond-${base}` };
  const signature = nodes.map((node) => `${node.id}@${node.position.x},${node.position.y}`).join("|");
  return (
    <MarkersContext.Provider value={markers}>
      <MarkerDefs markers={markers} />
      <Disclosure id="problem-graph-legend" variant="link" headingLevel={null} title="Show the legend" openTitle="Hide the legend" className="pg-disclosure">
        <ul className="pg-legend" aria-label="Legend">
          {legend}
        </ul>
      </Disclosure>
      <section className="pg-canvas" aria-label={label}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={EDGE_TYPES}
          colorMode={theme}
          fitView
          fitViewOptions={{ padding: 0.12 }}
          minZoom={0.1}
          maxZoom={2}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          proOptions={{ hideAttribution: true }}
        >
          <FitOnChange signature={signature} />
          <Background gap={24} size={1} />
          <Controls showInteractive={false} position="bottom-left" />
        </ReactFlow>
      </section>
    </MarkersContext.Provider>
  );
}
