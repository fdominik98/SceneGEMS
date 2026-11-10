import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useUiStore } from "../../../app/uiStore";
import type { CatalogClass } from "../../../domain/cluster/campaignApi";
import { useBatchGenerationStore } from "../../../domain/sceneGeneration/batchGenerationStore";
import { sampleFrames } from "../../../test/fixtures/sampleFrames";
import { sampleCatalogClasses } from "../../../test/fixtures/campaignCatalog";
import { useCatalogTexts } from "./catalogTexts";
import { SceneGenerationSidebar } from "./SceneGenerationSidebar";

const mocks = vi.hoisted(() => ({ catalog: { data: undefined as unknown, isLoading: false, isError: false, error: null as unknown } }));

vi.mock("../../campaigns/useCampaignData", () => ({ useCatalogClasses: () => mocks.catalog }));
vi.mock("@uiw/react-codemirror", () => ({
  default: ({ value, readOnly }: { value: string; readOnly?: boolean }) => <textarea aria-label={readOnly ? "FEC text" : "Specification text"} readOnly value={value} />,
}));

const [FIRST, SECOND, THIRD] = sampleCatalogClasses.map((entry) => entry.fec_id);

/** A catalog FEC's text: its classes and two vessels with a link. */
function fecTextOf(classId: string): string {
  return `class OS.\nclass TS.\nclass Vessel { Vessel[0..*] headOn }\ndeclare os, ts1.\nOS(os).\nTS(ts1).\nheadOn(os, ts1).\n% ${classId}\n`;
}

function renderSidebar(overrides: Partial<Parameters<typeof SceneGenerationSidebar>[0]> = {}) {
  const props: Parameters<typeof SceneGenerationSidebar>[0] = {
    functionalSpecText: "",
    functionalSpecLabel: null,
    onFunctionalSpecTextChange: vi.fn(),
    loadScenarioText: vi.fn(async (classId: string) => fecTextOf(classId)),
    onLoadFunctionalSpecFromFile: vi.fn(),
    onExportFunctionalSpec: vi.fn(),
    onEditCopy: vi.fn(),
    onVisualizeFromEvaluation: vi.fn(),
    ...overrides,
  };
  const view = render(<SceneGenerationSidebar {...props} />);
  return { props, ...view };
}

function catalogOf(items: CatalogClass[]) {
  mocks.catalog = { data: { items, total: items.length }, isLoading: false, isError: false, error: null };
}

describe("the scene page's right pane", () => {
  beforeEach(() => {
    useUiStore.setState({ sceneGenerationPaneView: "specification" });
    useBatchGenerationStore.setState({ results: [], selectedClassIds: [], running: false });
    useCatalogTexts.getState().reset();
    catalogOf(sampleCatalogClasses);
  });

  it("lists the control node's FECs with their relations in words and shows the editor while none is selected", async () => {
    renderSidebar({ functionalSpecText: "declare a.\n", functionalSpecLabel: "mine.problem" });
    expect(screen.getByText("Each functional scenario specification is one functional equivalence class (FEC).")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "FEC specification" })).toBeInTheDocument();
    const list = screen.getByRole("list", { name: "FECs of the control node's catalog" });
    expect(within(list).getAllByRole("checkbox")).toHaveLength(sampleCatalogClasses.length);
    await waitFor(() => expect(within(list).getAllByText("os head on ts1")).toHaveLength(sampleCatalogClasses.length));
    const editor = screen.getByRole("region", { name: "Editor" });
    expect(within(editor).getByLabelText("Specification text")).toHaveValue("declare a.\n");
    expect(within(editor).getByRole("heading", { name: "mine.problem" })).toBeVisible();
    expect(screen.queryByRole("tab", { name: "Batch (several FECs)" })).not.toBeInTheDocument();
  });

  it("shows the editor's text as a model graph, following edits, and remembers the choice", async () => {
    const user = userEvent.setup();
    const { rerender, props } = renderSidebar({ functionalSpecText: "declare alpha.\n" });
    const editor = screen.getByRole("region", { name: "Editor" });
    await user.click(within(editor).getByRole("button", { name: "Graph" }));
    const graph = within(editor).getByRole("region", { name: "Model graph of the editor's text" });
    expect(within(graph).getByTitle("alpha")).toBeVisible();
    expect(window.localStorage.getItem("scenegems:scene-generation-editor-view")).toBe('"graph"');
    rerender(<SceneGenerationSidebar {...props} functionalSpecText={"declare alpha, beta.\n"} />);
    await waitFor(() => expect(within(screen.getByRole("region", { name: "Model graph of the editor's text" })).getByTitle("beta")).toBeVisible());
    rerender(<SceneGenerationSidebar {...props} functionalSpecText={"class A {\ndeclare gamma.\n"} />);
    expect(await screen.findByText(/syntax error/)).toBeVisible();
  });

  it("shows the one FEC selected as its model graph, its text one click away, and edits a copy in the editor", async () => {
    const user = userEvent.setup();
    const { props } = renderSidebar();
    await user.click(screen.getByRole("checkbox", { name: SECOND }));
    expect(screen.queryByRole("region", { name: "Editor" })).not.toBeInTheDocument();
    const selectedPane = screen.getByRole("region", { name: `Selected FEC ${SECOND}` });
    const graph = await within(selectedPane).findByRole("region", { name: `Model graph of ${SECOND}` });
    expect(within(graph).getByTitle("ts1")).toBeVisible();
    await user.click(within(selectedPane).getByRole("button", { name: "Text" }));
    expect(within(selectedPane).getByLabelText("FEC text")).toHaveValue(fecTextOf(SECOND));

    await user.click(within(selectedPane).getByRole("button", { name: "Edit a copy" }));
    expect(props.onEditCopy).toHaveBeenCalledWith(`${SECOND} (copy)`, fecTextOf(SECOND));
    expect(useBatchGenerationStore.getState().selectedClassIds).toEqual([]);
    expect(screen.getByRole("region", { name: "Editor" })).toBeInTheDocument();
  });

  it("runs several FECs selected as a batch, with select all shown, the hidden count and clear", async () => {
    const user = userEvent.setup();
    renderSidebar();
    await user.click(screen.getByRole("checkbox", { name: FIRST }));
    await user.click(screen.getByRole("checkbox", { name: THIRD }));
    expect(screen.getByRole("region", { name: "Selected FECs" })).toHaveTextContent("2 FECs selected: the run generates a scene of each");
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by vessel count" }), "3");
    expect(screen.getByText(/not shown by the filters/)).toHaveTextContent("2 selected, 2 of them not shown by the filters (they run too)");
    await user.click(screen.getByRole("button", { name: "Select all shown (2)" }));
    expect(useBatchGenerationStore.getState().selectedClassIds).toHaveLength(4);
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(useBatchGenerationStore.getState().selectedClassIds).toEqual([]);
  });

  it("previews a FEC without selecting it, and adds it to the selection from there", async () => {
    const user = userEvent.setup();
    renderSidebar();
    await user.click(screen.getByRole("button", { name: `Preview ${THIRD}` }));
    const preview = screen.getByRole("region", { name: `Preview of ${THIRD}` });
    expect(await within(preview).findByRole("region", { name: `Model graph of ${THIRD}` })).toBeInTheDocument();
    expect(useBatchGenerationStore.getState().selectedClassIds).toEqual([]);
    await user.click(within(preview).getByRole("button", { name: "Add to the selection" }));
    expect(useBatchGenerationStore.getState().selectedClassIds).toEqual([THIRD]);
    await user.click(within(preview).getByRole("button", { name: "Close the preview" }));
    expect(screen.getByRole("region", { name: `Selected FEC ${THIRD}` })).toBeInTheDocument();
  });

  it("says where a FEC's text cannot be read", async () => {
    const user = userEvent.setup();
    renderSidebar({ loadScenarioText: vi.fn(async (classId: string) => (classId === SECOND ? Promise.reject(new Error("HTTP 404")) : fecTextOf(classId))) });
    const row = screen.getByRole("button", { name: `Preview ${SECOND}` });
    await waitFor(() => expect(row).toHaveTextContent("text not readable"));
    await user.click(row);
    expect(within(screen.getByRole("region", { name: `Preview of ${SECOND}` })).getByText("The FEC's text could not be read: HTTP 404")).toBeVisible();
  });

  it("stays usable with all 828 FECs: only the rows in view are drawn and read", async () => {
    const many = Array.from({ length: 828 }, (_, index) => ({ ...sampleCatalogClasses[0], fec_id: `big/fec${index}` }));
    catalogOf(many);
    const loadScenarioText = vi.fn(async (classId: string) => fecTextOf(classId));
    renderSidebar({ loadScenarioText });
    const list = screen.getByRole("list", { name: "FECs of the control node's catalog" });
    expect(within(list).getAllByRole("checkbox").length).toBeLessThan(30);
    await waitFor(() => expect(loadScenarioText).toHaveBeenCalled());
    expect(loadScenarioText.mock.calls.length).toBeLessThan(30);
    expect(screen.getByRole("button", { name: "Select all shown (828)" })).toBeEnabled();
  });

  it("drops a remembered selection of FECs the control node no longer has", () => {
    useBatchGenerationStore.setState({ selectedClassIds: ["gone/fec1", FIRST] });
    renderSidebar();
    expect(useBatchGenerationStore.getState().selectedClassIds).toEqual([FIRST]);
    expect(screen.getByRole("region", { name: `Selected FEC ${FIRST}` })).toBeInTheDocument();
  });

  it("keeps the batch results after the run and marks the one on the canvas", async () => {
    const user = userEvent.setup();
    const scene = sampleFrames[0]!;
    useBatchGenerationStore.setState({
      results: [
        { classId: FIRST, label: FIRST, requestId: "r1", status: "success", evaluationData: {} as never, scene },
        { classId: SECOND, label: SECOND, requestId: "r2", status: "error", message: "no model" },
      ],
    });
    const { props } = renderSidebar({ activeScene: scene });
    const results = screen.getByRole("region", { name: "Batch generation results" });
    expect(within(results).getByRole("button", { name: /success · visualized/ })).toBeInTheDocument();
    expect(within(results).getByText("no model")).toBeVisible();
    expect(screen.getByRole("button", { name: "Export all valid (1)" })).toBeEnabled();
    await user.click(within(results).getByRole("button", { name: /success/ }));
    expect(props.onVisualizeFromEvaluation).toHaveBeenCalledWith({}, scene);
  });

  it("says when the FEC catalog could not be read", () => {
    mocks.catalog = { data: undefined, isLoading: false, isError: true, error: new Error("HTTP 503") };
    renderSidebar();
    expect(screen.getByText("The control node's FEC catalog could not be read: HTTP 503")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Editor" })).toBeInTheDocument();
  });
});
