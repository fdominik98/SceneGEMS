import type { ReactNode } from "react";
import type { ActorKinematicState, ActorStaticInfo, SimulationFrame } from "../../../domain/simulation/types";
import type { VesselEncounterTag } from "../monitor/encounterPairs";
import {
  chooseScaleBar,
  courseDeg,
  formatClock,
  formatDegrees,
  formatKnots,
  formatNm,
  screenDirectionOfBearing,
  velocityOf,
  worldMatrix,
  worldToScreen,
  type Point,
  type ViewTransform,
} from "./encounterGeometry";
import { CANVAS_COLORS, ROLE_CODES, ROLE_COLORS } from "./encounterPalette";
import {
  collectManeuveringDomainDrawings,
  collectSafetyDomains,
  collectStaticAvoidanceDomains,
  MANEUVERING_DOMAIN_KITE_COLOR,
} from "./domainShapes";
import { placeLabels, polylinePoints, thinPoints, vectorTickMinutes, type CpaMark } from "./encounterScene";

const NON_SCALING = "non-scaling-stroke";

/** Children drawn in world coordinates (meters, north up), strokes in screen pixels. */
export function WorldGroup({ view, children }: { view: ViewTransform; children: ReactNode }) {
  return <g transform={worldMatrix(view)}>{children}</g>;
}

export function RangeRings({
  center,
  spacing,
  view,
}: {
  center: Point;
  spacing: number;
  view: ViewTransform;
}) {
  const maxRadius = Math.hypot(view.width, view.height);
  const step = spacing * view.scale;
  if (step < 8) {
    return null;
  }
  const rings: number[] = [];
  for (let k = 1; k * step <= maxRadius + step && rings.length < 40; k += 1) {
    rings.push(k);
  }
  const labelAngle = (-50 * Math.PI) / 180;
  const labelRadius = Math.min(view.width, view.height) / 2;
  return (
    <g aria-label="Range rings">
      {rings.map((k) => {
        const r = k * step;
        const nm = (k * spacing) / 1852;
        const label = nm < 0.1 ? `${Math.round(k * spacing)} m` : `${Number(nm.toFixed(2))} nm`;
        return (
          <g key={k}>
            <circle cx={center.x} cy={center.y} r={r} fill="none" stroke={CANVAS_COLORS.ring} strokeWidth={1} />
            {r <= labelRadius ? (
              <text
                x={center.x + Math.cos(labelAngle) * r + 3}
                y={center.y + Math.sin(labelAngle) * r - 3}
                fill={CANVAS_COLORS.ringLabel}
                fontSize={12}
              >
                {label}
              </text>
            ) : null}
          </g>
        );
      })}
    </g>
  );
}

/** True bearing scale around the own ship, with its heading and each target's bearing marked. */
export function BearingScale({
  center,
  radius,
  view,
  ownCourse,
  ownColor,
  targets,
}: {
  center: Point;
  radius: number;
  view: ViewTransform;
  ownCourse: number | null;
  ownColor: string;
  targets: { key: string; bearing: number; color: string }[];
}) {
  const ticks: ReactNode[] = [];
  for (let deg = 0; deg < 360; deg += 5) {
    const dir = screenDirectionOfBearing(view, deg);
    const length = deg % 30 === 0 ? 9 : deg % 10 === 0 ? 6 : 3;
    ticks.push(
      <line
        key={deg}
        x1={center.x + dir.x * radius}
        y1={center.y + dir.y * radius}
        x2={center.x + dir.x * (radius - length)}
        y2={center.y + dir.y * (radius - length)}
        stroke={CANVAS_COLORS.bearingTick}
        strokeWidth={deg % 30 === 0 ? 1.4 : 1}
      />
    );
    if (deg % 30 === 0) {
      ticks.push(
        <text
          key={`l${deg}`}
          x={center.x + dir.x * (radius - 19)}
          y={center.y + dir.y * (radius - 19) + 3.5}
          textAnchor="middle"
          fill={CANVAS_COLORS.bearingLabel}
          fontSize={12}
        >
          {String(deg).padStart(3, "0")}
        </text>
      );
    }
  }
  const marker = (bearing: number, color: string, key: string, size: number) => {
    const dir = screenDirectionOfBearing(view, bearing);
    const tip = { x: center.x + dir.x * radius, y: center.y + dir.y * radius };
    const back = { x: tip.x + dir.x * size * 1.4, y: tip.y + dir.y * size * 1.4 };
    const side = { x: -dir.y * size * 0.7, y: dir.x * size * 0.7 };
    return (
      <polygon
        key={key}
        points={`${tip.x},${tip.y} ${back.x + side.x},${back.y + side.y} ${back.x - side.x},${back.y - side.y}`}
        fill={color}
        stroke={CANVAS_COLORS.sea}
        strokeWidth={0.8}
      />
    );
  };
  return (
    <g aria-label="Bearing scale">
      <circle cx={center.x} cy={center.y} r={radius} fill="none" stroke={CANVAS_COLORS.bearingTick} strokeWidth={1} />
      {ticks}
      {targets.map((target) => marker(target.bearing, target.color, target.key, 5))}
      {ownCourse !== null ? marker(ownCourse, ownColor, "own-heading", 7) : null}
    </g>
  );
}

export function ScaleBar({ view }: { view: ViewTransform }) {
  const bar = chooseScaleBar((view.width * 0.22) / view.scale);
  const px = bar.meters * view.scale;
  const x = 14;
  const y = view.height - 16;
  return (
    <g aria-label="Scale bar">
      <rect x={x - 6} y={y - 18} width={px + 12} height={26} rx={3} fill={CANVAS_COLORS.labelBackground} />
      <line x1={x} y1={y} x2={x + px} y2={y} stroke={CANVAS_COLORS.labelText} strokeWidth={2} />
      <line x1={x} y1={y - 5} x2={x} y2={y + 3} stroke={CANVAS_COLORS.labelText} strokeWidth={1.5} />
      <line x1={x + px} y1={y - 5} x2={x + px} y2={y + 3} stroke={CANVAS_COLORS.labelText} strokeWidth={1.5} />
      <line x1={x + px / 2} y1={y - 3} x2={x + px / 2} y2={y} stroke={CANVAS_COLORS.labelText} strokeWidth={1} />
      <text x={x + px / 2} y={y - 7} textAnchor="middle" fill={CANVAS_COLORS.labelText} fontSize={13}>
        {bar.label}
      </text>
    </g>
  );
}

export function NorthArrow({ view, headUp }: { view: ViewTransform; headUp: boolean }) {
  const dir = screenDirectionOfBearing(view, 0);
  const cx = view.width - 30;
  const cy = 34;
  const tip = { x: cx + dir.x * 15, y: cy + dir.y * 15 };
  const tail = { x: cx - dir.x * 11, y: cy - dir.y * 11 };
  const side = { x: -dir.y * 6, y: dir.x * 6 };
  return (
    <g aria-label={headUp ? "North (head-up view)" : "North (north-up view)"}>
      <circle cx={cx} cy={cy} r={20} fill={CANVAS_COLORS.labelBackground} stroke={CANVAS_COLORS.ring} />
      <polygon
        points={`${tip.x},${tip.y} ${tail.x + side.x},${tail.y + side.y} ${cx},${cy} ${tail.x - side.x},${tail.y - side.y}`}
        fill={CANVAS_COLORS.labelText}
      />
      <text
        x={cx + dir.x * 26}
        y={cy + dir.y * 26 + 4}
        textAnchor="middle"
        fill={CANVAS_COLORS.labelText}
        fontSize={14}
        fontWeight={600}
      >
        N
      </text>
    </g>
  );
}

/** Safety domains (dashed), static avoidance discs (dotted) and give-way corridors of a frame. */
export function DomainLayer({
  frame,
  colorByActorId,
  showSafety,
  showStatic,
  showManeuvering,
  dim,
}: {
  frame: SimulationFrame;
  colorByActorId: Record<string, string>;
  showSafety: boolean;
  showStatic: boolean;
  showManeuvering: boolean;
  dim: boolean;
}) {
  const opacity = dim ? 0.45 : 0.85;
  return (
    <g opacity={opacity}>
      {showStatic
        ? collectStaticAvoidanceDomains(frame.situationContexts).map(({ key, actorId, disc }) => (
            <circle
              key={`s-${key}`}
              cx={disc.center[0]}
              cy={disc.center[1]}
              r={disc.radius}
              fill="none"
              stroke={colorByActorId[actorId] ?? CANVAS_COLORS.fallback}
              strokeWidth={1}
              strokeDasharray="1 4"
              strokeLinecap="round"
              vectorEffect={NON_SCALING}
            />
          ))
        : null}
      {showSafety
        ? collectSafetyDomains(frame.situationContexts).map(({ key, actorId, domain }) => {
            const [cx, cy] = domain.center;
            const deg = (domain.heading * 180) / Math.PI;
            const color = colorByActorId[actorId] ?? CANVAS_COLORS.fallback;
            const common = {
              fill: color,
              fillOpacity: 0.06,
              stroke: color,
              strokeWidth: 1.2,
              strokeDasharray: "6 4",
              vectorEffect: NON_SCALING,
              transform: `rotate(${deg} ${cx} ${cy})`,
            } as const;
            if (domain.shape === "rectangle") {
              const a = domain.a ?? 0;
              const b = domain.b ?? 0;
              return <rect key={`d-${key}`} x={cx - a} y={cy - b} width={2 * a} height={2 * b} {...common} />;
            }
            const rx = domain.shape === "circle" ? (domain.radius ?? 0) : (domain.a ?? 0);
            const ry = domain.shape === "circle" ? (domain.radius ?? 0) : (domain.b ?? 0);
            return <ellipse key={`d-${key}`} cx={cx} cy={cy} rx={rx} ry={ry} {...common} />;
          })
        : null}
      {showManeuvering
        ? collectManeuveringDomainDrawings(frame.situationContexts, colorByActorId).map((drawing) => (
            <g key={`m-${drawing.key}`}>
              {drawing.kite.length > 2 ? (
                <polygon
                  points={drawing.kite.map(([x, y]) => `${x},${y}`).join(" ")}
                  fill={MANEUVERING_DOMAIN_KITE_COLOR}
                  fillOpacity={0.05}
                  stroke={MANEUVERING_DOMAIN_KITE_COLOR}
                  strokeWidth={1.2}
                  strokeDasharray="8 5"
                  vectorEffect={NON_SCALING}
                />
              ) : null}
              {drawing.hold.length > 1 ? (
                <polyline
                  points={drawing.hold.map(([x, y]) => `${x},${y}`).join(" ")}
                  fill="none"
                  stroke={drawing.color}
                  strokeWidth={1.2}
                  strokeOpacity={0.7}
                  vectorEffect={NON_SCALING}
                />
              ) : null}
            </g>
          ))
        : null}
    </g>
  );
}

/** Safety radius rings (actor `safetyRadius`) in world coordinates. */
export function SafetyRadiusLayer({
  frame,
  colorByActorId,
}: {
  frame: SimulationFrame;
  colorByActorId: Record<string, string>;
}) {
  return (
    <g>
      {frame.actors.map((actor) => {
        const state = frame.statesByActorId[actor.id];
        if (!state || actor.safetyRadius <= 0) {
          return null;
        }
        return (
          <circle
            key={actor.id}
            cx={state.x}
            cy={state.y}
            r={actor.safetyRadius}
            fill="none"
            stroke={colorByActorId[actor.id] ?? CANVAS_COLORS.fallback}
            strokeOpacity={0.35}
            strokeWidth={1}
            vectorEffect={NON_SCALING}
          />
        );
      })}
    </g>
  );
}

export interface TrackDrawing {
  actorId: string;
  past: Point[];
  ahead: Point[];
}

/** Past track solid, the path ahead dashed and faint. */
export function TrackLayer({
  tracks,
  colorByActorId,
  secondary,
}: {
  tracks: TrackDrawing[];
  colorByActorId: Record<string, string>;
  secondary: boolean;
}) {
  return (
    <g>
      {tracks.map((track) => {
        const color = colorByActorId[track.actorId] ?? CANVAS_COLORS.fallback;
        return (
          <g key={track.actorId}>
            {track.ahead.length > 1 ? (
              <polyline
                points={polylinePoints(thinPoints(track.ahead))}
                fill="none"
                stroke={color}
                strokeOpacity={secondary ? 0.35 : 0.5}
                strokeWidth={1.2}
                strokeDasharray="5 5"
                vectorEffect={NON_SCALING}
              />
            ) : null}
            {track.past.length > 1 ? (
              <polyline
                points={polylinePoints(thinPoints(track.past))}
                fill="none"
                stroke={color}
                strokeOpacity={secondary ? 0.75 : 0.9}
                strokeWidth={secondary ? 2.4 : 1.8}
                strokeLinejoin="round"
                vectorEffect={NON_SCALING}
              />
            ) : null}
          </g>
        );
      })}
    </g>
  );
}

function hullPoints(length: number, breadth: number): string {
  const l2 = Math.max(length, 1) / 2;
  const b2 = Math.max(breadth, 0.5) / 2;
  const shoulder = l2 - Math.max(length, 1) * 0.3;
  return [
    [l2, 0],
    [shoulder, b2],
    [-l2, b2],
    [-l2, -b2],
    [shoulder, -b2],
  ]
    .map(([x, y]) => `${x},${y}`)
    .join(" ");
}

/** Hulls to scale (length by breadth, bow along the heading) in world coordinates. */
export function HullLayer({
  frame,
  colorByActorId,
  secondary,
}: {
  frame: SimulationFrame;
  colorByActorId: Record<string, string>;
  secondary: boolean;
}) {
  return (
    <g>
      {frame.actors.map((actor) => {
        const state = frame.statesByActorId[actor.id];
        if (!state) {
          return null;
        }
        const color = colorByActorId[actor.id] ?? CANVAS_COLORS.fallback;
        const deg = (state.heading * 180) / Math.PI;
        return (
          <polygon
            key={actor.id}
            points={hullPoints(actor.length, actor.breadth)}
            transform={`translate(${state.x} ${state.y}) rotate(${deg})`}
            fill={secondary ? "none" : color}
            fillOpacity={0.9}
            stroke={secondary ? color : CANVAS_COLORS.hullStroke}
            strokeWidth={secondary ? 1.6 : 0.8}
            vectorEffect={NON_SCALING}
          />
        );
      })}
    </g>
  );
}

const MIN_SYMBOL_PX = 12;
const HEADING_LINE_PX = 26;

export interface VesselScreenInfo {
  actor: ActorStaticInfo;
  state: ActorKinematicState;
  screen: Point;
}

/**
 * Screen-space parts of each vessel: a symbol when the hull is too small to see, the heading
 * line, the course and speed vector over `vectorSeconds` with time marks, and dots every
 * minute on the past track.
 */
export function VesselOverlay({
  vessels,
  view,
  colorByActorId,
  showSymbols,
  showVectors,
  vectorSeconds,
  historyDots,
  secondary,
  onVesselClick,
}: {
  vessels: VesselScreenInfo[];
  view: ViewTransform;
  colorByActorId: Record<string, string>;
  showSymbols: boolean;
  showVectors: boolean;
  vectorSeconds: number;
  historyDots: Record<string, Point[]>;
  secondary: boolean;
  onVesselClick?: (actorId: string) => void;
}) {
  return (
    <g>
      {vessels.map(({ actor, state, screen }) => {
        const color = colorByActorId[actor.id] ?? CANVAS_COLORS.fallback;
        const dir = screenDirectionOfBearing(view, courseDeg(state.heading));
        const normal = { x: -dir.y, y: dir.x };
        const hullPx = actor.length * view.scale;
        const halfLength = Math.max(hullPx, MIN_SYMBOL_PX) / 2;
        const bow = { x: screen.x + dir.x * halfLength, y: screen.y + dir.y * halfLength };
        const parts: ReactNode[] = [];

        for (const dot of historyDots[actor.id] ?? []) {
          parts.push(<circle key={`h${dot.x},${dot.y}`} cx={dot.x} cy={dot.y} r={1.6} fill={color} opacity={0.75} />);
        }

        if (showVectors && state.speed > 0.05) {
          const velocity = velocityOf(state);
          const end = worldToScreen(view, {
            x: state.x + velocity.x * vectorSeconds,
            y: state.y + velocity.y * vectorSeconds,
          });
          parts.push(
            <line
              key="vector"
              x1={screen.x}
              y1={screen.y}
              x2={end.x}
              y2={end.y}
              stroke={color}
              strokeWidth={secondary ? 1.4 : 2}
              strokeOpacity={secondary ? 0.7 : 1}
            />
          );
          const tickMinutes = vectorTickMinutes(state.speed, view.scale);
          if (tickMinutes !== null) {
            const count = Math.floor(vectorSeconds / (tickMinutes * 60));
            for (let k = 1; k <= count && k <= 60; k += 1) {
              const t = k * tickMinutes * 60;
              const p = worldToScreen(view, { x: state.x + velocity.x * t, y: state.y + velocity.y * t });
              const half = k * tickMinutes * 60 === vectorSeconds ? 5 : 3;
              parts.push(
                <line
                  key={`t${k}`}
                  x1={p.x + normal.x * half}
                  y1={p.y + normal.y * half}
                  x2={p.x - normal.x * half}
                  y2={p.y - normal.y * half}
                  stroke={color}
                  strokeWidth={1.4}
                />
              );
            }
          }
        }

        if (showSymbols) {
          parts.push(
            <line
              key="heading"
              x1={bow.x}
              y1={bow.y}
              x2={bow.x + dir.x * HEADING_LINE_PX}
              y2={bow.y + dir.y * HEADING_LINE_PX}
              stroke={color}
              strokeWidth={1}
              strokeOpacity={0.9}
            />
          );
          if (hullPx < MIN_SYMBOL_PX) {
            const tip = bow;
            const tail = { x: screen.x - dir.x * halfLength, y: screen.y - dir.y * halfLength };
            const w = 5;
            parts.push(
              <polygon
                key="symbol"
                points={`${tip.x},${tip.y} ${tail.x + normal.x * w},${tail.y + normal.y * w} ${tail.x - normal.x * w},${tail.y - normal.y * w}`}
                fill={secondary ? "none" : color}
                stroke={secondary ? color : CANVAS_COLORS.hullStroke}
                strokeWidth={secondary ? 1.5 : 0.8}
              />
            );
          }
        }

        return (
          <g
            key={actor.id}
            onClick={onVesselClick ? () => onVesselClick(actor.id) : undefined}
            style={onVesselClick ? { cursor: "pointer" } : undefined}
          >
            {parts}
            {onVesselClick ? <circle cx={screen.x} cy={screen.y} r={10} fill="transparent" /> : null}
          </g>
        );
      })}
    </g>
  );
}

export function CpaLayer({
  marks,
  view,
  colorByActorId,
  selectedRelationId,
}: {
  marks: CpaMark[];
  view: ViewTransform;
  colorByActorId: Record<string, string>;
  selectedRelationId: string | null;
}) {
  return (
    <g aria-label="Closest points of approach">
      {marks.map((mark) => {
        const a = worldToScreen(view, mark.pointA);
        const b = worldToScreen(view, mark.pointB);
        const selected = mark.relationId === selectedRelationId;
        const tone = mark.inside
          ? CANVAS_COLORS.cpaDanger
          : mark.collisionCourse
            ? CANVAS_COLORS.cpaWarn
            : CANVAS_COLORS.cpaNeutral;
        const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
        const text = `CPA ${formatNm(mark.dcpa)} in ${formatClock(mark.tcpa)}`;
        const width = text.length * 7.4 + 14;
        const diamond = (p: Point) =>
          `${p.x},${p.y - 5} ${p.x + 5},${p.y} ${p.x},${p.y + 5} ${p.x - 5},${p.y}`;
        return (
          <g key={mark.relationId} opacity={selected || selectedRelationId === null ? 1 : 0.55}>
            <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={tone} strokeWidth={selected ? 1.6 : 1.1} strokeDasharray="3 3" />
            <polygon points={diamond(a)} fill="none" stroke={colorByActorId[mark.aId] ?? tone} strokeWidth={1.6} />
            <polygon points={diamond(b)} fill="none" stroke={colorByActorId[mark.bId] ?? tone} strokeWidth={1.6} />
            <rect
              x={mid.x + 8}
              y={mid.y - 20}
              width={width}
              height={19}
              rx={3}
              fill={CANVAS_COLORS.labelBackground}
              stroke={tone}
              strokeWidth={0.8}
            />
            <text x={mid.x + 14} y={mid.y - 6} fill={tone} fontSize={13} fontWeight={600}>
              {text}
            </text>
          </g>
        );
      })}
    </g>
  );
}

export function SelectionLine({ a, b, label }: { a: Point; b: Point; label: string }) {
  const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  const width = label.length * 7.4 + 14;
  return (
    <g aria-label="Selected pair" pointerEvents="none">
      <circle cx={a.x} cy={a.y} r={15} fill="none" stroke={CANVAS_COLORS.selection} strokeWidth={1.2} strokeDasharray="2 3" />
      <circle cx={b.x} cy={b.y} r={15} fill="none" stroke={CANVAS_COLORS.selection} strokeWidth={1.2} strokeDasharray="2 3" />
      <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={CANVAS_COLORS.selection} strokeOpacity={0.7} strokeWidth={1} strokeDasharray="6 4" />
      <rect x={mid.x - width / 2} y={mid.y + 4} width={width} height={19} rx={3} fill={CANVAS_COLORS.labelBackground} />
      <text x={mid.x} y={mid.y + 18} textAnchor="middle" fill={CANVAS_COLORS.selection} fontSize={13}>
        {label}
      </text>
    </g>
  );
}

const LABEL_LINE = 17;
const CHAR_WIDTH = 7.4;

export function VesselLabels({
  vessels,
  colorByActorId,
  tagsByVessel,
  bounds,
}: {
  vessels: VesselScreenInfo[];
  colorByActorId: Record<string, string>;
  tagsByVessel: Record<string, VesselEncounterTag[]>;
  /** Area labels should stay in (the canvas below its toolbar). */
  bounds?: { x: number; y: number; width: number; height: number };
}) {
  const contents = vessels.map(({ actor, state, screen }) => {
    const kinematics = `${formatKnots(state.speed)} · ${formatDegrees(courseDeg(state.heading))}`;
    const tags = tagsByVessel[actor.id] ?? [];
    const tagTexts = tags.map((tag) => `${tag.abbreviation} · ${tag.otherName}`);
    const widest = Math.max(
      actor.name.length * (CHAR_WIDTH + 0.5),
      kinematics.length * CHAR_WIDTH,
      ...tagTexts.map((text) => text.length * CHAR_WIDTH + 34)
    );
    return {
      actor,
      kinematics,
      tags,
      tagTexts,
      anchor: screen,
      width: widest + 12,
      height: LABEL_LINE * (2 + tags.length) + 8,
    };
  });
  const boxes = placeLabels(contents, bounds);
  return (
    <g aria-label="Vessel labels" pointerEvents="none">
      {contents.map((content, index) => {
        const box = boxes[index]!;
        const color = colorByActorId[content.actor.id] ?? CANVAS_COLORS.labelText;
        return (
          <g key={content.actor.id}>
            <rect x={box.x} y={box.y} width={box.width} height={box.height} rx={3} fill={CANVAS_COLORS.labelBackground} />
            <rect x={box.x} y={box.y} width={2.5} height={box.height} fill={color} />
            <text x={box.x + 7} y={box.y + LABEL_LINE - 1} fill={color} fontSize={14} fontWeight={600}>
              {content.actor.name}
            </text>
            <text x={box.x + 7} y={box.y + LABEL_LINE * 2 - 1} fill={CANVAS_COLORS.labelMuted} fontSize={13}>
              {content.kinematics}
            </text>
            {content.tags.map((tag, tagIndex) => {
              const y = box.y + LABEL_LINE * (3 + tagIndex);
              const roleColor = tag.role ? ROLE_COLORS[tag.role] : "#64748b";
              return (
                <g key={`${tag.otherId}-${tagIndex}`}>
                  <rect x={box.x + 7} y={y - 12} width={24} height={15} rx={2} fill={roleColor} />
                  <text x={box.x + 19} y={y - 0.5} textAnchor="middle" fill="#0b1220" fontSize={11} fontWeight={700}>
                    {tag.role ? ROLE_CODES[tag.role] : "-"}
                  </text>
                  <text x={box.x + 36} y={y - 1} fill={CANVAS_COLORS.labelText} fontSize={13}>
                    {content.tagTexts[tagIndex]}
                  </text>
                </g>
              );
            })}
          </g>
        );
      })}
    </g>
  );
}

export interface LegendStream {
  key: string;
  label: string;
  color: string;
  secondary: boolean;
}

/** Key to the symbols; drawn in the SVG so screenshots carry it. */
export function CanvasLegend({
  view,
  streams,
  vectorMinutes,
}: {
  view: ViewTransform;
  streams: LegendStream[];
  vectorMinutes: number;
}) {
  const width = 284;
  const rowHeight = 18;
  const rows: ReactNode[] = [];
  let y = 16;
  const text = (x: number, yy: number, content: string, muted = false) => (
    <text x={x} y={yy + 4.5} fill={muted ? CANVAS_COLORS.labelMuted : CANVAS_COLORS.labelText} fontSize={12.5}>
      {content}
    </text>
  );
  const row = (key: string, content: ReactNode) => {
    rows.push(<g key={key}>{content}</g>);
    y += rowHeight;
  };
  const chip = (x: number, yy: number, role: "give-way" | "stand-on") => (
    <g>
      <rect x={x} y={yy - 7} width={22} height={14} rx={2} fill={ROLE_COLORS[role]} />
      <text x={x + 11} y={yy + 4} textAnchor="middle" fill="#0b1220" fontSize={10.5} fontWeight={700}>
        {ROLE_CODES[role]}
      </text>
    </g>
  );
  if (streams.length > 1) {
    let x = 8;
    const cells: ReactNode[] = [];
    for (const stream of streams) {
      cells.push(
        <g key={stream.key}>
          <polygon
            points={`${x + 14},${y} ${x + 2},${y - 4.5} ${x + 2},${y + 4.5}`}
            fill={stream.secondary ? "none" : stream.color}
            stroke={stream.color}
            strokeWidth={1.3}
          />
          {text(x + 18, y, stream.label)}
        </g>
      );
      x += 30 + stream.label.length * 7.2;
    }
    row("streams", cells);
  }
  row(
    "tracks",
    <>
      <line x1={8} y1={y} x2={26} y2={y} stroke={CANVAS_COLORS.labelText} strokeWidth={1.8} />
      {text(30, y, "so far")}
      <line x1={84} y1={y} x2={102} y2={y} stroke={CANVAS_COLORS.labelText} strokeOpacity={0.6} strokeDasharray="4 3" />
      {text(106, y, "ahead (plan or record)")}
    </>
  );
  row(
    "vector",
    <>
      <line x1={8} y1={y} x2={26} y2={y} stroke={CANVAS_COLORS.labelText} strokeWidth={2} />
      <line x1={14} y1={y - 3} x2={14} y2={y + 3} stroke={CANVAS_COLORS.labelText} />
      <line x1={20} y1={y - 3} x2={20} y2={y + 3} stroke={CANVAS_COLORS.labelText} />
      {text(30, y, `vector ${vectorMinutes} min, a mark each minute`)}
    </>
  );
  row(
    "cpa",
    <>
      <polygon points={`12,${y - 4} 16,${y} 12,${y + 4} 8,${y}`} fill="none" stroke={CANVAS_COLORS.cpaDanger} strokeWidth={1.3} />
      <line x1={16} y1={y} x2={22} y2={y} stroke={CANVAS_COLORS.cpaDanger} strokeDasharray="2 2" />
      <polygon points={`26,${y - 4} 30,${y} 26,${y + 4} 22,${y}`} fill="none" stroke={CANVAS_COLORS.cpaDanger} strokeWidth={1.3} />
      {text(34, y, "CPA, red inside the safety distance")}
    </>
  );
  row(
    "roles",
    <>
      {chip(8, y, "give-way")}
      {text(34, y, "give-way")}
      {chip(100, y, "stand-on")}
      {text(126, y, "stand-on")}
    </>
  );
  row("codes", text(8, y, "HO head-on, CR crossing, OT overtaking", true));
  row(
    "domains",
    <>
      <ellipse cx={17} cy={y} rx={9} ry={4} fill="none" stroke={CANVAS_COLORS.labelText} strokeDasharray="3 2" />
      {text(32, y, "safety")}
      <circle cx={92} cy={y} r={4} fill="none" stroke={CANVAS_COLORS.labelText} strokeDasharray="1 2.5" strokeLinecap="round" />
      {text(100, y, "static")}
      <polygon points={`150,${y + 3} 155,${y - 3} 163,${y - 3} 168,${y + 3}`} fill="none" stroke={MANEUVERING_DOMAIN_KITE_COLOR} strokeDasharray="3 2" />
      {text(172, y, "corridor")}
    </>
  );
  const height = y - rowHeight / 2 + 4;
  return (
    <g transform={`translate(${view.width - width - 10} ${view.height - height - 10})`} aria-label="Legend">
      <rect width={width} height={height} rx={4} fill={CANVAS_COLORS.legendBackground} stroke={CANVAS_COLORS.legendBorder} />
      {rows}
    </g>
  );
}
