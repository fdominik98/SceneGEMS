import { useMemo } from "react";
import type { NodeTypes } from "@xyflow/react";
import { Disclosure } from "../../../../components/Disclosure";
import { EmptyState } from "../../../../components/EmptyState";
import { readProblem, type MetaPredicate } from "../../../../domain/designSpace/problemModel";
import { cardHandles } from "./flowParts";
import { placeEdges } from "./graphGeometry";
import { layoutMetamodel, metamodelGraph, metamodelSummary } from "./metamodelLayout";
import { LegendLine, ProblemGraphCanvas, SyntaxNotice, type ProblemFlowEdge } from "./ProblemGraphCanvas";
import { ClassNode, EnumNode, type ClassFlowNode, type EnumFlowNode } from "./ProblemGraphNodes";
import { useDebouncedValue } from "./useDebouncedValue";

const NODE_TYPES: NodeTypes = { class: ClassNode, enum: EnumNode };

/** The parse waits until typing pauses. */
const PARSE_DELAY_MS = 250;

function signatureOf(predicate: MetaPredicate): string {
  return `${predicate.name}(${predicate.parameters.map((parameter) => (parameter.type === null ? parameter.name : `${parameter.type} ${parameter.name}`)).join(", ")})`;
}

function PredicateList({ title, predicates }: { title: string; predicates: MetaPredicate[] }) {
  if (predicates.length === 0) {
    return null;
  }
  return (
    <div className="pg-predicates">
      <h5>{title}</h5>
      <ul aria-label={title}>
        {predicates.map((predicate) => (
          <li key={`${predicate.name}:${predicate.line}`}>
            <code>{signatureOf(predicate)}</code>
            {predicate.shadow ? " (shadow)" : ""}
            <span className="meta"> line {predicate.line}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * The metamodel of a specification as a class diagram: classes with their attributes, enums with
 * their literals, inheritance and references between the classes. It follows the text as it is
 * edited, a moment after typing pauses; the predicates and the constraints are listed by name.
 */
export function MetamodelGraph({ text }: { text: string }) {
  const shown = useDebouncedValue(text, PARSE_DELAY_MS);
  const read = useMemo(() => readProblem(shown), [shown]);
  const { nodes, edges } = useMemo(() => {
    const graph = metamodelGraph(read.metamodel);
    const positions = layoutMetamodel(graph);
    const placement = placeEdges(graph.edges);
    const nodes = graph.cards.map(
      (card): ClassFlowNode | EnumFlowNode =>
        ({
          id: card.id,
          type: card.kind,
          position: positions.get(card.id) ?? { x: 0, y: 0 },
          width: card.width,
          height: card.height,
          handles: cardHandles(card.width),
          data: { card },
        }) as ClassFlowNode | EnumFlowNode
    );
    const edges: ProblemFlowEdge[] = graph.edges.map((edge) => ({
      id: edge.id,
      type: "problem",
      source: edge.source,
      target: edge.target,
      data: {
        label: edge.label,
        endLabels: edge.endLabels,
        title: edge.title,
        style: edge.kind,
        twoWay: edge.twoWay,
        possible: false,
        diamond: edge.diamond,
        placement: placement.get(edge.id) ?? { kind: "line", offset: 0 },
      },
    }));
    return { nodes, edges };
  }, [read]);

  if (shown.trim().length === 0) {
    return (
      <div className="pg-graph pg-graph--empty">
        <EmptyState title="Nothing to draw">
          <p className="meta">The specification is empty. Write or load one, and the graph shows its classes and enums.</p>
        </EmptyState>
      </div>
    );
  }

  const { metamodel } = read;
  const constraints = metamodel.predicates.filter((item) => item.error);
  const predicates = metamodel.predicates.filter((item) => !item.error);
  const others = metamodel.declarations.filter((item) => item.kind !== "module");
  return (
    <div className="pg-graph">
      <p className="pg-summary">{metamodelSummary(metamodel)}</p>
      <SyntaxNotice syntax={read.syntax} />
      {metamodel.predicates.length + others.length > 0 ? (
        <Disclosure variant="link" headingLevel={null} title="Show the predicates and constraints" openTitle="Hide the predicates and constraints" className="pg-disclosure">
          <div className="pg-predicate-lists">
            <PredicateList title="Predicates" predicates={predicates} />
            <PredicateList title="Constraints (error predicates)" predicates={constraints} />
            {others.length > 0 ? (
              <div className="pg-predicates">
                <h5>Other declarations</h5>
                <ul aria-label="Other declarations">
                  {others.map((item) => (
                    <li key={`${item.kind}:${item.name}:${item.line}`}>
                      {item.kind} <code>{item.name}</code>
                      <span className="meta"> line {item.line}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <p className="meta">Their bodies are in the text.</p>
          </div>
        </Disclosure>
      ) : null}
      {nodes.length === 0 ? (
        <EmptyState title="No class or enum to draw">
          <p className="meta">The text declares no class and no enum{read.syntax.errorCount > 0 ? " that could be read" : ""}.</p>
        </EmptyState>
      ) : (
        <ProblemGraphCanvas
          label="Metamodel graph"
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          legend={
            <>
              <LegendLine style="extends" marker="triangle">
                extends: from a class to its superclass
              </LegendLine>
              <LegendLine style="reference" marker="arrow">
                reference, with its name and multiplicity
              </LegendLine>
              <LegendLine style="contains" marker="diamond">
                containment: the diamond is at the class that contains
              </LegendLine>
              <LegendLine style="reference" marker="arrow" twoWay>
                an arrowhead at both ends: two references that are each other's opposite, each name next to the class it leads to
              </LegendLine>
              <li>dashed card: a class the text uses but does not define</li>
            </>
          }
        />
      )}
    </div>
  );
}
