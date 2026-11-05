import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CatalogClass } from "../../../domain/cluster/campaignApi";
import { useBatchGenerationStore } from "../../../domain/sceneGeneration/batchGenerationStore";
import { sampleCatalogClasses } from "../../../test/fixtures/campaignCatalog";
import { BatchPresetRunner } from "./BatchPresetRunner";

function renderRunner(presets: CatalogClass[]) {
  render(<BatchPresetRunner presets={presets} onVisualizeScenario={vi.fn()} onOpenPresetInRefinery={vi.fn()} activeScene={null} />);
}

describe("BatchPresetRunner", () => {
  beforeEach(() => useBatchGenerationStore.setState({ results: [], selectedClassIds: [], running: false }));

  it("asks for the FECs to run and counts the selected ones", async () => {
    const user = userEvent.setup();
    renderRunner(sampleCatalogClasses.slice(0, 2));
    expect(screen.getByText(/Select the FECs to run/)).toHaveTextContent("0 selected");
    await user.click(screen.getByRole("checkbox", { name: sampleCatalogClasses[0].fec_id }));
    expect(screen.getByText(/Select the FECs to run/)).toHaveTextContent("1 selected");
  });

  it("says when no FEC matches the filters and that earlier selections still run", () => {
    useBatchGenerationStore.setState({ selectedClassIds: [sampleCatalogClasses[0].fec_id, sampleCatalogClasses[1].fec_id] });
    renderRunner([]);
    expect(screen.getByText(/No FEC of the master's catalog matches the filters\./)).toHaveTextContent("2 selected earlier still run.");
  });
});
