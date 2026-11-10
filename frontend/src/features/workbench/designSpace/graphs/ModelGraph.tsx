import { useMemo } from "react";
import type { NodeTypes } from "@xyflow/react";
import { EmptyState } from "../../../../components/EmptyState";
import { readProblem } from "../../../../domain/designSpace/problemModel";
import { cardHandles } from "./flowParts";
import { placeEdges } from "./graphGeometry";
import { layoutModel, modelGraph, modelSummary } from "./modelLayout";
import { LegendLine, ProblemGraphCanvas, SyntaxNotice, type ProblemFlowEdge } from "./ProblemGraphCanvas";
import { ObjectNode, type ObjectFlowNode } from "./ProblemGraphNodes";

const NODE_TYPES: NodeTypes = { object: ObjectNode };

/**
 * A model (an explored FEC) as an object graph: a card per object with its types and values, an
 * edge per link labelled with its relation. The metamodel the same text repeats is not drawn; it
 * only says which names are classes and enum literals.
 */
export function ModelGraph({ text, label = "Model graph" }: { text: string; label?: string }) {
  const read = useMemo(() => readProblem(text), [text]);
  const { nodes, edges } = useMemo(() => {
    const graph = modelGraph(read);
    const positions = layoutModel(graph);
    const placement = placeEdges(graph.edges);
    const nodes: ObjectFlowNode[] = graph.cards.map((card) => ({
      id: card.id,
      type: "object",
      position: positions.get(card.id) ?? { x: 0, y: 0 },
      width: card.width,
      height: card.height,
      handles: cardHandles(card.width),
      data: { card },
    }));
    const edges: ProblemFlowEdge[] = graph.edges.map((edge) => ({
      id: edge.id,
      type: "problem",
      source: edge.source,
      target: edge.target,
      data: {
        label: edge.label,
        title: edge.title,
        style: "link",
        twoWay: edge.twoWay,
        possible: edge.possible,
        diamond: null,
        placement: placement.get(edge.id) ?? { kind: "line", offset: 0 },
      },
    }));
    return { nodes, edges };
  }, [read]);

  if (text.trim().length === 0) {
    return (
      <div className="pg-graph pg-graph--empty">
        <EmptyState title="Nothing to draw">
          <p className="meta">The text is empty.</p>
        </EmptyState>
      </div>
    );
  }
  return (
    <div className="pg-graph">
      <p className="pg-summary">{modelSummary(read)}</p>
      <SyntaxNotice syntax={read.syntax} />
      {nodes.length === 0 ? (
        <EmptyState title="No objects">
          <p className="meta">The text declares no object and asserts no fact about one.</p>
        </EmptyState>
      ) : (
        <ProblemGraphCanvas
          label={label}
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          legend={
            <>
              <LegendLine style="link" marker="arrow">
                link, from its first object to its second
              </LegendLine>
              <LegendLine style="link" marker="arrow" twoWay>
                an arrowhead at both ends: the link holds both ways
              </LegendLine>
              <LegendLine style="link" marker="arrow" possible>
                dashed: unknown, the link may hold
              </LegendLine>
              <li>a card has the object's name on its color, then its classes, its other facts in italics and its values; a "?" marks what may hold</li>
            </>
          }
        />
      )}
    </div>
  );
}
