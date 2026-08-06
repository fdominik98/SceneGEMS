import { Fragment, type ReactNode } from "react";
import { formatRelationId, renderRelationId } from "./actorNameFormat";

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
  "mass",
  "safetyRadius",
  "maxSpeed",
  "maxAngularSpeed",
  "maxAcceleration",
  "rudderMass",
  "rudderLength",
  "rudderWidth",
  "rudderHeight",
  "propellerDiameter",
  "thrusterMass",
  "motorLength",
] as const;

export const KINEMATIC_FIELD_PRIORITY = ["x", "y", "speed", "heading"] as const;

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

function sortKeys(keys: string[], priority: readonly string[]): string[] {
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

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

interface DynamicValueProps {
  value: unknown;
  depth: number;
}

export function DynamicValue({ value, depth }: DynamicValueProps): ReactNode {
  if (value === null || value === undefined) {
    return <span className="frame-dyn-empty">:</span>;
  }
  if (typeof value === "string" && value.includes("->")) {
    return <span className="frame-dyn-scalar">{renderRelationId(value)}</span>;
  }
  if (typeof value === "boolean" || typeof value === "number" || typeof value === "string") {
    return <span className="frame-dyn-scalar">{formatScalar(value)}</span>;
  }
  if (typeof value === "bigint") {
    return <span className="frame-dyn-scalar">{value.toString()}</span>;
  }
  if (Array.isArray(value)) {
    if (value.length === 0) {
      return <span className="frame-dyn-empty">[]</span>;
    }
    if (depth >= 2 || value.length > 12) {
      return <span className="frame-dyn-folded">[{value.length} items]</span>;
    }
    const allScalar = value.every(
      (item) =>
        item === null ||
        typeof item === "boolean" ||
        typeof item === "number" ||
        typeof item === "string"
    );
    if (allScalar) {
      return (
        <span className="frame-dyn-scalar frame-dyn-inline-list">
          {value.map((item) => formatScalar(item)).join(", ")}
        </span>
      );
    }
    return (
      <ul className="frame-dyn-nested-list">
        {value.slice(0, 8).map((item, i) => (
          <li key={i}>
            <DynamicValue value={item} depth={depth + 1} />
          </li>
        ))}
        {value.length > 8 ? (
          <li className="meta">+{value.length - 8} more…</li>
        ) : null}
      </ul>
    );
  }
  if (isPlainObject(value)) {
    const entries = Object.entries(value);
    if (entries.length === 0) {
      return <span className="frame-dyn-empty">{"{}"}</span>;
    }
    if (depth >= 2) {
      return <span className="frame-dyn-folded">{`{${entries.length} fields}`}</span>;
    }
    return (
      <DynamicFieldGrid
        data={value}
        depth={depth + 1}
        className="frame-kv-grid frame-kv-grid--nested"
      />
    );
  }
  return <span className="frame-dyn-scalar">{String(value)}</span>;
}

interface DynamicFieldGridProps {
  data: Record<string, unknown>;
  /** Nesting depth for folding large structures. */
  depth?: number;
  omitKeys?: Set<string>;
  priorityKeys?: readonly string[];
  className?: string;
}

export function DynamicFieldGrid({
  data,
  depth = 0,
  omitKeys = new Set(),
  priorityKeys = [],
  className = "frame-kv-grid",
}: DynamicFieldGridProps) {
  const keys = Object.keys(data).filter((k) => !omitKeys.has(k) && data[k] !== undefined);
  if (keys.length === 0) {
    return <p className="meta frame-dyn-empty">No fields</p>;
  }
  const sorted = priorityKeys.length > 0 ? sortKeys(keys, priorityKeys) : sortKeys(keys, []);

  return (
    <dl className={className}>
      {sorted.map((key) => (
        <Fragment key={key}>
          <dt className="frame-kv-label">
            {key.includes("->") ? formatRelationId(key) : humanizeKey(key)}
          </dt>
          <dd className="frame-kv-value">
            {key === "relationId" && typeof data[key] === "string" ? (
              <span className="frame-dyn-scalar">{renderRelationId(data[key] as string)}</span>
            ) : (
              <DynamicValue value={data[key]} depth={depth} />
            )}
          </dd>
        </Fragment>
      ))}
    </dl>
  );
}
