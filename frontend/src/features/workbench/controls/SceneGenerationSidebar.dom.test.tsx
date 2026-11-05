import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useUiStore } from "../../../app/uiStore";
import { sampleCatalogClasses } from "../../../test/fixtures/campaignCatalog";
import { SceneGenerationSidebar } from "./SceneGenerationSidebar";

const mocks = vi.hoisted(() => ({ catalog: { data: undefined as unknown, isLoading: false, isError: false, error: null as unknown } }));

vi.mock("../../campaigns/useCampaignData", () => ({ useCatalogClasses: () => mocks.catalog }));
vi.mock("@uiw/react-codemirror", () => ({ default: ({ value }: { value: string }) => <textarea aria-label="Specification text" readOnly value={value} /> }));

function renderSidebar() {
  const props = {
    functionalSpecText: "",
    functionalSpecLabel: null,
    onFunctionalSpecTextChange: vi.fn(),
    onLoadFunctionalSpecFromPreset: vi.fn(),
    loadScenarioText: vi.fn(),
    onLoadFunctionalSpecFromFile: vi.fn(),
    onExportFunctionalSpec: vi.fn(),
    onVisualizeFromEvaluation: vi.fn(),
  };
  render(<SceneGenerationSidebar {...props} />);
  return props;
}

describe("SceneGenerationSidebar", () => {
  beforeEach(() => {
    localStorage.clear();
    useUiStore.setState({ sceneGenerationTab: "single", sceneGenerationPaneView: "specification" });
    mocks.catalog = { data: { items: sampleCatalogClasses }, isLoading: false, isError: false, error: null };
  });

  it("says that a specification is a FEC and loads a FEC of the catalog", async () => {
    const user = userEvent.setup();
    const props = renderSidebar();
    expect(screen.getByText("Each functional scenario specification is one functional equivalence class (FEC).")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "FEC specification" })).toBeInTheDocument();
    expect(screen.getByText("Find a FEC")).toBeInTheDocument();
    expect(screen.getByText(`${sampleCatalogClasses.length} FECs`)).toBeInTheDocument();

    const list = screen.getByRole("combobox", { name: "Load a FEC of the master's catalog" });
    expect(within(list).getByRole("option", { name: "Load FEC…" })).toBeInTheDocument();
    await user.selectOptions(list, sampleCatalogClasses[1].fec_id);
    expect(props.onLoadFunctionalSpecFromPreset).toHaveBeenCalledWith(sampleCatalogClasses[1].fec_id);
  });

  it("offers a batch of several FECs", async () => {
    const user = userEvent.setup();
    renderSidebar();
    await user.click(screen.getByRole("tab", { name: "Batch (several FECs)" }));
    expect(screen.getByText(/Select the FECs to run/)).toBeInTheDocument();
  });

  it("says when the FEC catalog could not be read", () => {
    mocks.catalog = { data: undefined, isLoading: false, isError: true, error: new Error("HTTP 503") };
    renderSidebar();
    expect(screen.getByText("The master's FEC catalog could not be read: HTTP 503")).toBeInTheDocument();
  });
});
