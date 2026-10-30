import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { nodeViewSchema } from "../../domain/cluster/schemas";
import { sampleNode } from "../../test/fixtures/clusterViews";
import { NodeCard } from "./NodeCard";

function renderCard(overrides: Record<string, unknown>) {
  const node = nodeViewSchema.parse(sampleNode(overrides));
  render(<NodeCard node={node} operatorUrl="http://127.0.0.1:5174" nowMs={Date.parse("2026-10-26T10:00:00+00:00")} instancesOpen={false} onToggleInstances={() => {}} />);
}

describe("NodeCard image mismatches", () => {
  it("names each image that differs when the node is out of date", () => {
    renderCard({
      out_of_date: true,
      fingerprint_mismatches: [
        { image: "scenegems-node:latest", required: "fp-node-aaaa", actual: "fp-node-bbbb" },
        { image: "scenegems-gazebo-harmonic:latest", required: "fp-gazebo-123456", actual: null },
      ],
    });
    const note = screen.getByRole("status");
    expect(note).toHaveTextContent("Out of date:");
    expect(note).toHaveTextContent("scenegems-node:latest");
    expect(note).toHaveTextContent("scenegems-gazebo-harmonic:latest");
    expect(note).toHaveTextContent("missing on the node");
  });

  it("shows no note for a node that matches the release", () => {
    renderCard({});
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
