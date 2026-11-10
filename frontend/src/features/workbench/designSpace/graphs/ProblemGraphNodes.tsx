import type { CSSProperties } from "react";
import type { Node, NodeProps } from "@xyflow/react";
import { useTheme } from "../../../../app/theme";
import { shipColorOfName } from "../../scene/shipColors";
import type { ClassCard, EnumCard } from "./metamodelLayout";
import type { ModelCard } from "./modelLayout";
import { CardHandles } from "./ProblemGraphCanvas";

/**
 * The cards of the problem graphs: a class, an enum, an object. They follow the node of Refinery's own graph view and of
 * the paper's FEC figure: a dark outline, a colored header with the name, and under it one row per thing the node is,
 * each with a tag. An object that is a vessel (`os`, `ts1`, ...) has the color the vessel has everywhere else in the
 * console; any other card takes the tone of its class's place among the classes.
 */

export type ClassFlowNode = Node<{ card: ClassCard }, "class">;
export type EnumFlowNode = Node<{ card: EnumCard }, "enum">;
export type ObjectFlowNode = Node<{ card: ModelCard }, "object">;

function withMultiplicity(type: string, multiplicity: string | null): string {
  return multiplicity === null ? type : `${type} [${multiplicity}]`;
}

/** The tag in front of a row: filled for what the node is by declaration, outlined for a value it has. */
function RowTag({ kind }: { kind: "type" | "fact" | "value" }) {
  return (
    <svg className={`pg-row-tag pg-row-tag--${kind}`} width="14" height="10" viewBox="0 0 14 10" aria-hidden="true">
      <path d="M 0.75 0.75 H 9 L 13.25 5 L 9 9.25 H 0.75 Z" />
    </svg>
  );
}

export function ClassNode({ data: { card } }: NodeProps<ClassFlowNode>) {
  return (
    <div className={`pg-card pg-tone-${card.tone}${card.defined ? "" : " is-undefined"}${card.abstract ? " is-abstract" : ""}`} style={{ width: card.width, height: card.height }}>
      <CardHandles />
      <div className="pg-card-head">
        <span className="pg-card-title" title={card.name}>
          {card.name}
        </span>
        {card.abstract ? <span className="pg-tag">abstract</span> : null}
      </div>
      <div className="pg-card-body">
        {card.defined ? null : <p className="pg-card-note">not defined in this text</p>}
        {card.rows.length > 0 ? (
          <ul className="pg-card-rows" aria-label={`Attributes of ${card.name}`}>
            {card.rows.map((row) => (
              <li key={row.name} title={`${row.name}: ${withMultiplicity(row.type, row.multiplicity)}`}>
                <RowTag kind="value" />
                <span className="pg-row-text">
                  <span className="pg-row-name">{row.name}</span>: <span className="pg-row-type">{withMultiplicity(row.type, row.multiplicity)}</span>
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}

export function EnumNode({ data: { card } }: NodeProps<EnumFlowNode>) {
  return (
    <div className="pg-card pg-card--enum" style={{ width: card.width, height: card.height }}>
      <CardHandles />
      <div className="pg-card-head">
        <span className="pg-card-title" title={card.name}>
          {card.name}
        </span>
        <span className="pg-tag">enum</span>
      </div>
      <div className="pg-card-body">
        <ul className="pg-card-rows" aria-label={`Literals of ${card.name}`}>
          {card.literals.length === 0 ? (
            <li className="pg-card-note">no literals</li>
          ) : (
            card.literals.map((literal) => (
              <li key={literal} title={literal}>
                <RowTag kind="type" />
                <span className="pg-row-text">{literal}</span>
              </li>
            ))
          )}
        </ul>
      </div>
    </div>
  );
}

export function ObjectNode({ data: { card } }: NodeProps<ObjectFlowNode>) {
  const theme = useTheme();
  const vesselColor = shipColorOfName(card.name, theme);
  const style: CSSProperties & Record<"--pg-node-color", string | undefined> = { width: card.width, height: card.height, "--pg-node-color": vesselColor ?? undefined };
  const rows = card.types.length + card.possibleTypes.length + card.values.length + card.facts.length;
  return (
    <div className={`pg-card pg-card--object${card.tone === null ? "" : ` pg-tone-${card.tone}`}`} style={style}>
      <CardHandles />
      <div className="pg-card-head">
        <span className="pg-card-title" title={card.name}>
          {card.name}
        </span>
      </div>
      <div className="pg-card-body">
        {rows > 0 ? (
          <ul className="pg-card-rows" aria-label={`What ${card.name} is`}>
            {card.types.map((type) => (
              <li key={`t:${type}`} title={`${card.name} is a ${type}`}>
                <RowTag kind="type" />
                <span className="pg-row-text pg-row-class">{type}</span>
              </li>
            ))}
            {card.possibleTypes.map((type) => (
              <li key={`p:${type}`} className="is-possible" title={`${card.name} may be a ${type}`}>
                <RowTag kind="type" />
                <span className="pg-row-text pg-row-class">{type}?</span>
              </li>
            ))}
            {card.facts.map((fact, index) => (
              <li key={`f${index}`} className={fact.possible ? "is-possible" : undefined} title={fact.possible ? `${fact.relation} (possibly)` : fact.relation}>
                <RowTag kind="fact" />
                <span className="pg-row-text pg-row-fact">
                  {fact.relation}
                  {fact.possible ? "?" : ""}
                </span>
              </li>
            ))}
            {card.values.map((value, index) => (
              <li key={`v${index}`} className={value.possible ? "is-possible" : undefined} title={`${value.relation}: ${value.value}${value.possible ? " (possibly)" : ""}`}>
                <RowTag kind="value" />
                <span className="pg-row-text">
                  <span className="pg-row-name">{value.relation}</span>: <span className="pg-row-type">{value.value}</span>
                  {value.possible ? "?" : ""}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
