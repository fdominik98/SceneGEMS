import { useEffect, useMemo, useRef, useState } from "react";
import { Handle, MarkerType, Position, ReactFlow, useReactFlow, useViewport, type Edge, type Node, type NodeProps, type NodeTypes } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useTheme } from "../../../app/theme";
import { drawingOffset, type CampaignMap as CampaignMapModel, type MapCard, type MapFact, type MapFrame, type MapSetting } from "./campaignMapModel";
import { WIZARD_STEP_LABELS, type WizardStepId } from "./wizardState";
import "./campaignMap.css";

/** Space around the drawing inside the canvas. */
const PAD = 16;
/** Below this the cards' text gets too small to read: the drawing stops shrinking and can be dragged sideways instead. */
const MIN_ZOOM = 0.7;

/** What a card or a setting opens: its page, and for a run card the run. */
export type MapTarget = Pick<MapCard, "page" | "runId">;

interface CardData extends Record<string, unknown> {
  card: MapCard;
  current: boolean;
  onOpen: (target: MapTarget) => void;
}

interface FrameData extends Record<string, unknown> {
  frame: MapFrame;
}

type CardNode = Node<CardData, "card">;
type FrameNode = Node<FrameData, "frame">;

function Problems({ count }: { count: number }) {
  if (count === 0) {
    return null;
  }
  return (
    <span className="cmap-problems">
      <span aria-hidden="true">{count}</span>
      <span className="sr-only">, {count === 1 ? "1 problem" : `${count} problems`}</span>
    </span>
  );
}

function Facts({ facts }: { facts: readonly MapFact[] }) {
  return (
    <>
      {facts.map((fact, index) => (
        <span key={index} className={`cmap-fact cmap-fact--${fact.tone}`}>
          {fact.text}
        </span>
      ))}
    </>
  );
}

function tooltip(title: string, facts: readonly MapFact[], page: WizardStepId, skipped: boolean): string {
  const lines = [title, ...facts.map((fact) => fact.text)];
  return `${lines.join("\n")}\n\n${skipped ? "Not part of this campaign. The Steps page adds it." : `Opens the ${WIZARD_STEP_LABELS[page]} page.`}`;
}

function CardView({ data }: NodeProps<CardNode>) {
  const { card, current, onOpen } = data;
  const skipped = card.kind === "skipped";
  return (
    <div className={`cmap-card cmap-card--${card.kind}${current ? " is-current" : ""}${card.problems > 0 ? " has-problems" : ""}`} style={{ width: card.width, height: card.height }}>
      <Handle type="target" position={Position.Left} className="cmap-handle" isConnectable={false} />
      <button type="button" className="cmap-card-button" aria-current={current ? "step" : undefined} title={tooltip(card.title, card.facts, card.page, skipped)} onClick={() => onOpen({ page: card.page, runId: card.runId })}>
        <span className="cmap-card-head">
          <span className="cmap-card-title">{card.title}</span>
          <Problems count={card.problems} />
        </span>
        <Facts facts={card.facts} />
      </button>
      <Handle type="source" position={Position.Right} className="cmap-handle" isConnectable={false} />
    </div>
  );
}

function FrameView({ data }: NodeProps<FrameNode>) {
  return (
    <div className="cmap-frame" style={{ width: data.frame.width, height: data.frame.height }}>
      <span className="cmap-frame-title">{data.frame.title}</span>
    </div>
  );
}

const NODE_TYPES: NodeTypes = { card: CardView, frame: FrameView };

/** Keeps the drawing at the zoom and offset that fit it into the canvas. */
function Fit({ x, y, zoom }: { x: number; y: number; zoom: number }) {
  const { setViewport } = useReactFlow();
  useEffect(() => {
    void setViewport({ x, y, zoom });
  }, [setViewport, x, y, zoom]);
  return null;
}

/** Shades the edges of a canvas narrower than the drawing where the drawing goes on, wherever it is dragged to. */
function Fades({ width, drawn }: { width: number; drawn: number }) {
  const { x } = useViewport();
  return (
    <>
      {x < PAD - 1 && <div className="cmap-fade cmap-fade--left" aria-hidden="true" />}
      {x + drawn > width - PAD + 1 && <div className="cmap-fade cmap-fade--right" aria-hidden="true" />}
    </>
  );
}

/** The width of an element, followed as it changes; 0 until it is measured. */
function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") {
      return undefined;
    }
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

export interface CampaignMapProps {
  map: CampaignMapModel;
  /** The page shown under the map: its cards are highlighted. */
  current: WizardStepId;
  onOpen: (target: MapTarget) => void;
}

function SettingButton({ setting, current, onOpen }: { setting: MapSetting; current: boolean; onOpen: (target: MapTarget) => void }) {
  return (
    <li>
      <button
        type="button"
        className={`cmap-setting${current ? " is-current" : ""}${setting.problems > 0 ? " has-problems" : ""}`}
        aria-current={current ? "step" : undefined}
        title={tooltip(setting.title, setting.facts, setting.page, false)}
        onClick={() => onOpen({ page: setting.page })}
      >
        <span className="cmap-card-head">
          <span className="cmap-card-title">{setting.title}</span>
          <Problems count={setting.problems} />
        </span>
        <Facts facts={setting.facts} />
      </button>
    </li>
  );
}

/**
 * The campaign drawn as a graph above the wizard's pages: the chain from the input to the review, one card per
 * simulation run, and the settings of the whole campaign in a row under it. Each card shows what its page holds and
 * opens it; the cards of the page below are highlighted and a red count marks a page's problems.
 */
export function CampaignMap({ map, current, onOpen }: CampaignMapProps) {
  const { ref, width } = useWidth();
  const room = width - 2 * PAD;
  const zoom = width > 0 ? Math.min(1, Math.max(MIN_ZOOM, room / map.width)) : 1;
  const drawn = map.width * zoom;
  const overflowing = width > 0 && drawn > room;
  const currentCards = map.cards.filter((card) => card.page === current && card.kind !== "skipped");
  const currentRight = currentCards.length > 0 ? Math.max(...currentCards.map((card) => card.x + card.width)) : null;
  const x = width > 0 ? drawingOffset(width, drawn, zoom, currentRight, PAD) : PAD;
  const height = Math.ceil(map.height * zoom) + 2 * PAD;
  const theme = useTheme();

  const nodes = useMemo<Array<CardNode | FrameNode>>(
    () => [
      ...map.frames.map<FrameNode>((frame) => ({
        id: `frame:${frame.id}`,
        type: "frame",
        position: { x: frame.x, y: frame.y },
        width: frame.width,
        height: frame.height,
        data: { frame },
        selectable: false,
        focusable: false,
        zIndex: -1,
      })),
      ...map.cards.map<CardNode>((card) => ({
        id: card.id,
        type: "card",
        position: { x: card.x, y: card.y },
        width: card.width,
        height: card.height,
        // React Flow lets the pointer through a node that cannot be selected or dragged: the card's button takes it
        style: { pointerEvents: "all" },
        data: { card, current: card.page === current && card.kind !== "skipped", onOpen },
      })),
    ],
    [map, current, onOpen]
  );
  const edges = useMemo<Edge[]>(
    () =>
      map.edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        className: "cmap-edge",
        markerEnd: { type: MarkerType.ArrowClosed, color: "var(--accent-strong)", width: 16, height: 16 },
        focusable: false,
      })),
    [map.edges]
  );

  return (
    <div className="cmap">
      <div className={`cmap-canvas${overflowing ? " is-overflowing" : ""}`} ref={ref} style={{ height }} data-testid="campaign-map-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          colorMode={theme}
          defaultViewport={{ x, y: PAD, zoom }}
          nodesDraggable={false}
          nodesConnectable={false}
          nodesFocusable={false}
          edgesFocusable={false}
          elementsSelectable={false}
          panOnDrag={overflowing}
          panOnScroll={false}
          zoomOnScroll={false}
          zoomOnPinch={false}
          zoomOnDoubleClick={false}
          preventScrolling={false}
          proOptions={{ hideAttribution: true }}
        >
          <Fit x={x} y={PAD} zoom={zoom} />
          {overflowing && <Fades width={width} drawn={drawn} />}
        </ReactFlow>
      </div>
      <ul className="cmap-settings" aria-label="Settings of the whole campaign">
        {map.settings.map((setting) => (
          <SettingButton key={setting.id} setting={setting} current={setting.page === current} onOpen={onOpen} />
        ))}
      </ul>
    </div>
  );
}
