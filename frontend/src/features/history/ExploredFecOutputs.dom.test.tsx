import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useUiStore } from "../../app/uiStore";
import { useSceneSpecificationHandoff } from "../workbench/pages/sceneSpecificationHandoff";
import { useWorkbenchTargetStore } from "../workbench/pages/workbenchTarget";
import { ExploredFecOutputs } from "./ExploredFecOutputs";

const mocks = vi.hoisted(() => ({ outputs: { data: undefined as unknown, isLoading: false, error: null as unknown, isFetching: false, refetch: () => Promise.resolve() } }));

vi.mock("./useHistoryData", () => ({ useStepOutputs: () => mocks.outputs }));
vi.mock("../campaigns/useCampaignData", () => ({ useOperatorClient: () => ({ artifactUrl: (sha: string) => `http://control-node/cluster/artifacts/${sha}` }) }));

function row(index: number) {
  return {
    case_id: 4,
    case_index: index,
    fec_id: `explored/0000${index}`,
    state: "complete",
    reason: null,
    artifact: { sha256: String(index).repeat(64), size_bytes: 40, kind: "functional_scenario", media_type: "text/plain", pointer: null },
    valid: true,
    complete: null,
    run_index: null,
    repeat_index: null,
    run_record_id: null,
    verdict: null,
    input_source: null,
    vessel_count: 2,
    obstacle_count: index,
  };
}

describe("the explored FECs of an entry", () => {
  beforeEach(() => {
    useWorkbenchTargetStore.setState({ pending: {} });
    useSceneSpecificationHandoff.setState({ pending: null });
    useUiStore.setState({ section: "history", workbenchView: "simulation" });
    mocks.outputs = { data: { items: [row(0), row(1)], total: 2 }, isLoading: false, error: null, isFetching: false, refetch: () => Promise.resolve() };
  });

  it("lists each FEC with its counts and opens it on the exploration page", async () => {
    const user = userEvent.setup();
    render(<ExploredFecOutputs campaignId="c1" running={false} />);
    const second = screen.getByText("explored/00001").closest("tr") as HTMLElement;
    expect(within(second).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["explored/00001", "2", "1", "Open in workbenchTo scene generation"]);
    await user.click(within(second).getByRole("button", { name: "Open in workbench" }));
    expect(useWorkbenchTargetStore.getState().pending.designSpaceExploration).toMatchObject({ campaignId: "c1", caseId: 4, step: "design_space_exploration", fecId: "explored/00001" });
    expect(useUiStore.getState()).toMatchObject({ section: "workbench", workbenchView: "designSpaceExploration" });
  });

  it("sends a FEC to the scene page's editor", async () => {
    const user = userEvent.setup();
    render(<ExploredFecOutputs campaignId="c1" running={false} />);
    await user.click(within(screen.getByText("explored/00000").closest("tr") as HTMLElement).getByRole("button", { name: "To scene generation" }));
    expect(useSceneSpecificationHandoff.getState().pending?.label).toBe("explored/00000");
    expect(useUiStore.getState().workbenchView).toBe("sceneGeneration");
  });

  it("waits for the exploration to end", () => {
    mocks.outputs = { ...mocks.outputs, data: { items: [], total: 0 } };
    render(<ExploredFecOutputs campaignId="c1" running />);
    expect(screen.getByText("They appear here once the exploration has ended.")).toBeInTheDocument();
  });
});
