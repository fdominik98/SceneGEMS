import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ExploredFec } from "../../../domain/designSpace/explorationResult";
import { useExplorationPageStore } from "../pages/pageStore";
import { DesignSpaceExplorationControls } from "./DesignSpaceExplorationControls";
import { DesignSpaceSidebar } from "./DesignSpaceSidebar";
import { ExploredFecList } from "./ExploredFecList";
import { INITIAL_EXPLORATION_INPUT, useExplorationInputStore } from "./explorationInputStore";
import { useExplorationStore } from "./explorationStore";

/** The design space exploration page with the control node's default mocked: a current control node, and one that predates the route (404, so null). */

const mocks = vi.hoisted(() => ({ designSpace: { data: undefined as unknown, isSuccess: false, isError: false, error: null as unknown } }));

vi.mock("../../campaigns/useCampaignData", () => ({ useDesignSpaceDefault: () => mocks.designSpace }));
vi.mock("@uiw/react-codemirror", () => ({
  default: ({ value, onChange, readOnly }: { value: string; onChange?: (value: string) => void; readOnly?: boolean }) => (
    <textarea aria-label={readOnly ? "FEC text" : "Specification text"} readOnly={readOnly} value={value} onChange={(event) => onChange?.(event.target.value)} />
  ),
}));

const DEFAULT = { specification: "abstract class Vessel.\n", scope: "TS = 2, StaticObstacle = 0" };
const RESOURCES = { jobType: "design_space_exploration", components: ["design_space_exploration"], workerNodes: 1, slots: 2, freeSlots: 2, blocker: null };

function shipped(data: unknown) {
  mocks.designSpace = { data, isSuccess: true, isError: false, error: null };
}

function fec(index: number): ExploredFec {
  return { fecId: `explored/0000${index}`, index, vesselCount: 2, obstacleCount: 0, artifact: { sha256: String(index).repeat(64), size_bytes: 40, kind: "functional_scenario", media_type: "text/plain", pointer: null } };
}

function renderControls(overrides: Partial<Parameters<typeof DesignSpaceExplorationControls>[0]> = {}) {
  const props = { resources: RESOURCES, busy: false, onExplore: vi.fn(), onStop: vi.fn(), onShowSpecification: vi.fn(), onExport: vi.fn(), exporting: false, onNext: vi.fn(), ...overrides };
  render(<DesignSpaceExplorationControls {...props} />);
  return props;
}

beforeEach(() => {
  useExplorationInputStore.setState({ ...INITIAL_EXPLORATION_INPUT });
  useExplorationStore.getState().clear();
  useExplorationPageStore.setState({ input: null, loaded: null, output: null, status: "idle", message: null, activeEntryId: null });
  mocks.designSpace = { data: undefined, isSuccess: false, isError: false, error: null };
});

afterEach(() => vi.unstubAllGlobals());

describe("the specification pane", () => {
  it("starts an empty editor from the control node's default, with its scope", async () => {
    shipped(DEFAULT);
    render(<DesignSpaceSidebar />);
    expect(screen.getByRole("heading", { name: "Metamodel and well-formedness constraints" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Specification text")).toHaveValue(DEFAULT.specification));
    expect(useExplorationInputStore.getState()).toMatchObject({ specificationLabel: "the control node's default", scope: DEFAULT.scope });
  });

  it("says so in plain words when an older control node ships no default, and leaves the editor empty", () => {
    shipped(null);
    render(<DesignSpaceSidebar />);
    expect(screen.getByRole("status")).toHaveTextContent("This control node ships no default design space");
    expect(screen.getByLabelText("Specification text")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Load the default" })).toBeDisabled();
  });

  it("asks before the default replaces an edited text", async () => {
    const user = userEvent.setup();
    shipped(DEFAULT);
    useExplorationInputStore.setState({ specification: "class Mine.\n", specificationLabel: null, scope: "TS = 1" });
    const confirm = vi.fn(() => false);
    vi.stubGlobal("confirm", confirm);
    render(<DesignSpaceSidebar />);
    await user.click(screen.getByRole("button", { name: "Load the default" }));
    expect(confirm).toHaveBeenCalledOnce();
    expect(useExplorationInputStore.getState().specification).toBe("class Mine.\n");
    confirm.mockReturnValue(true);
    await user.click(screen.getByRole("button", { name: "Load the default" }));
    // The scope the operator entered stays
    expect(useExplorationInputStore.getState()).toMatchObject({ specification: DEFAULT.specification, scope: "TS = 1" });
  });
});

describe("the step panel", () => {
  it("is step 1 of 4 and waits for a specification and a valid scope", async () => {
    const user = userEvent.setup();
    const props = renderControls();
    expect(screen.getByText("Step 1 of 4")).toBeInTheDocument();
    const explore = screen.getByRole("button", { name: "Explore" });
    expect(explore).toBeDisabled();
    expect(explore).toHaveAttribute("title", expect.stringContaining("Write or load the metamodel"));

    useExplorationInputStore.setState({ specification: "class OS.\n" });
    await user.type(screen.getByLabelText("Scope"), "TS = 2,");
    expect(screen.getByRole("alert")).toHaveTextContent("The entry 2 is empty");
    expect(screen.getByRole("button", { name: "Explore" })).toBeDisabled();
    await user.type(screen.getByLabelText("Scope"), " StaticObstacle = 0");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Explore" }));
    expect(props.onExplore).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "Edit in the specification pane" }));
    expect(props.onShowSpecification).toHaveBeenCalledOnce();
  });

  it("says why it cannot run when no machine offers the exploration", () => {
    useExplorationInputStore.setState({ specification: "class OS.\n", scope: "TS = 2" });
    renderControls({ resources: { ...RESOURCES, workerNodes: 0, blocker: "No machine of the active cluster offers design space exploration." } });
    expect(screen.getByRole("list", { name: "Before it can run" })).toHaveTextContent("No machine of the active cluster offers design space exploration.");
    expect(screen.getByRole("button", { name: "Explore" })).toBeDisabled();
  });

  it("shows the result and hands a FEC on to scene generation", async () => {
    const user = userEvent.setup();
    useExplorationStore.getState().show({ campaignId: "c1", result: { stop_reason: "cap_reached", models_found: 2, max_models: 2 }, fecs: [fec(0), fec(1)] });
    const props = renderControls();
    const result = screen.getByRole("group", { name: "Result" });
    expect(within(result).getByText("The first 2 FECs: the cap of 2 was reached, there may be more.")).toBeInTheDocument();
    await user.click(within(result).getByRole("button", { name: "Next: Scene Generation" }));
    expect(props.onNext).toHaveBeenCalledOnce();
    await user.click(within(result).getByRole("button", { name: "Export the FECs (ZIP of .problem files)" }));
    expect(props.onExport).toHaveBeenCalledOnce();
  });

  it("offers Stop while it explores", async () => {
    const user = userEvent.setup();
    useExplorationStore.getState().setRunning({ message: "generating models: 17 of at most 100 found after 4.2 s", progress: 0.17 });
    const props = renderControls({ busy: true });
    expect(screen.getByRole("group", { name: "Result" })).toHaveTextContent("generating models: 17 of at most 100 found after 4.2 s");
    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(props.onStop).toHaveBeenCalledOnce();
  });
});

describe("the list of explored FECs", () => {
  it("says what the page does before a run", () => {
    render(<ExploredFecList client={null} />);
    expect(screen.getByRole("heading", { name: "No exploration yet" })).toBeInTheDocument();
  });

  it("lists the FECs, reads the texts of the rows in view and shows the selected FEC whole", async () => {
    const user = userEvent.setup();
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => new Response(String(input).endsWith("1".repeat(64)) ? "declare os, ts1.\nheadOn(os, ts1).\nheadOn(ts1, os).\n" : "declare os.\n"));
    vi.stubGlobal("fetch", fetchImpl);
    const client = { artifactUrl: (sha: string) => `http://control-node/cluster/artifacts/${sha}` };
    const many = Array.from({ length: 200 }, (_value, index) => ({ ...fec(index), fecId: `explored/${String(index).padStart(5, "0")}` }));
    useExplorationStore.getState().show({ campaignId: "c1", result: { stop_reason: "exhausted", models_found: 200 }, fecs: many });
    render(<ExploredFecList client={client} />);
    expect(screen.getByText("200 FECs: all FECs of the design space.")).toBeInTheDocument();
    const list = screen.getByRole("listbox", { name: "Explored FECs" });
    // Only the rows in view are drawn and read
    expect(within(list).getAllByRole("option").length).toBeLessThan(30);
    await waitFor(() => expect(within(list).getByText("os and ts1 head on")).toBeInTheDocument());
    expect(fetchImpl.mock.calls.length).toBeLessThan(30);

    await user.click(within(list).getByRole("option", { name: /explored\/00001/ }));
    expect(useExplorationStore.getState().selectedFecId).toBe("explored/00001");
    // The graph first, the text one click away
    expect(await screen.findByRole("region", { name: "Model graph of explored/00001" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Text" }));
    expect(screen.getByLabelText("FEC text")).toHaveValue("declare os, ts1.\nheadOn(os, ts1).\nheadOn(ts1, os).\n");
  });

  it("says that a specification without a model has no FEC", () => {
    useExplorationStore.getState().show({ campaignId: "c1", result: { stop_reason: "unsatisfiable", models_found: 0 }, fecs: [] });
    render(<ExploredFecList client={null} />);
    expect(screen.getByText("No FEC: the specification has no model within the scope.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No FEC to list" })).toBeInTheDocument();
  });
});
