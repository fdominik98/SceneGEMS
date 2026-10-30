import { fireEvent, render, screen } from "@testing-library/react";
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

  it("names the out-of-date components, which get no jobs, while the others work", () => {
    renderCard({
      out_of_date: true,
      fingerprint_mismatches: [{ image: "scenegems-gazebo-harmonic:latest", required: "fp-gazebo-123456", actual: "fp-old" }],
      components: [
        { component: "asv_software/replay", images: [], state: "usable" },
        { component: "simulation_layer/gazebo", images: ["scenegems-gazebo-harmonic:latest"], state: "out_of_date" },
      ],
    });
    expect(screen.getByRole("status")).toHaveTextContent("the images of Gazebo differ from the master's release; jobs needing it go elsewhere.");
    const components = screen.getByRole("list", { name: "Components" });
    expect(components).toHaveTextContent("Replay");
    expect(components).toHaveTextContent("Gazebo out of date");
  });
});

describe("NodeCard components and slots", () => {
  it("lists the components and the slots per job type", () => {
    renderCard({});
    expect(screen.getByRole("list", { name: "Components" })).toHaveTextContent("ReplayNo control layerKinematic layerScene generation");
    fireEvent.click(screen.getByRole("button", { name: /Details/ }));
    expect(screen.getByText("Simulation")).toBeInTheDocument();
    expect(screen.getByText("8/8")).toBeInTheDocument();
  });
});
