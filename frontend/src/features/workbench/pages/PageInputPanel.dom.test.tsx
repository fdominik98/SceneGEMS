import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { OperatorClient } from "../../../domain/cluster/operatorApi";
import { sampleCampaignRow, sampleSceneOutput, sampleWorkbenchRow, SCENE_SHA } from "../../../test/fixtures/historyViews";
import { PageInputPanel } from "./PageInputPanel";

function fakeClient(): OperatorClient {
  return {
    request: vi.fn(async (_method: string, path: string) => {
      if (path === "/cluster/campaigns") {
        return { data: [sampleWorkbenchRow({ name: "Scene generation: head_on", steps: ["scene_generation"] }), sampleCampaignRow({ campaign_id: "c9", name: "Sims only", steps: ["simulation"] })], total: 2 };
      }
      return { data: [sampleSceneOutput()], total: 1 };
    }),
    artifactUrl: (sha256: string) => `http://control-node/cluster/artifacts/${sha256}`,
  } as unknown as OperatorClient;
}

function renderPanel(overrides: Partial<Parameters<typeof PageInputPanel>[0]> = {}) {
  const props = {
    noun: "Scene",
    input: null,
    previousLabel: "Scene page",
    previousTitle: "Take the scene shown on the Scene Generation page",
    previousAvailable: true,
    onUsePrevious: vi.fn(),
    historyStep: "scene_generation" as const,
    client: fakeClient(),
    onPickHistory: vi.fn(),
    onPickFile: vi.fn(),
    ...overrides,
  };
  render(<PageInputPanel {...props} />);
  return props;
}

describe("PageInputPanel in the DOM", () => {
  it("says what the input is and where it came from", () => {
    renderPanel({ input: { label: "head_on.json", origin: "file", ref: null, source: { file: "head_on.json" } } });
    expect(screen.getByRole("status")).toHaveTextContent("Scene head_on.json from a file");
    expect(screen.getByRole("group", { name: "Input" })).toBeInTheDocument();
  });

  it("says when no input is chosen yet", () => {
    renderPanel();
    expect(screen.getByRole("status")).toHaveTextContent("Scene none chosen");
  });

  it("takes the previous page's output in one click", async () => {
    const user = userEvent.setup();
    const props = renderPanel();
    const previous = screen.getByRole("button", { name: "Scene page" });
    expect(previous).toHaveAttribute("title", "Take the scene shown on the Scene Generation page");
    await user.click(previous);
    expect(props.onUsePrevious).toHaveBeenCalledTimes(1);
  });

  it("cannot take the previous page's output when it shows none, nor history without a cluster", () => {
    renderPanel({ previousAvailable: false, client: null });
    expect(screen.getByRole("button", { name: "Scene page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Campaign History" })).toBeDisabled();
  });

  it("picks an output of an entry that ran the step and hands over its content", async () => {
    const user = userEvent.setup();
    const scene = { best_scene: { _data: [] } };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(scene))));
    const onPickHistory = vi.fn();
    renderPanel({ onPickHistory });
    await user.click(screen.getByRole("button", { name: "Campaign History" }));
    // The entry without the step is left out.
    expect(await screen.findByText("Scene generation: head_on")).toBeVisible();
    expect(screen.queryByText("Sims only")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Scene generation: head_on/ }));
    await user.click(await screen.findByRole("button", { name: /class-a, case 3/ }));
    await vi.waitFor(() => expect(onPickHistory).toHaveBeenCalledTimes(1));
    const [input, document] = onPickHistory.mock.calls[0];
    expect(input).toMatchObject({ origin: "history", ref: { sha256: SCENE_SHA }, source: { case_id: 5, step: "scene_generation" } });
    expect(document).toEqual(scene);
    vi.unstubAllGlobals();
  });

  it("shows why a file could not be taken", async () => {
    const user = userEvent.setup();
    renderPanel({ onPickFile: vi.fn(async () => Promise.reject(new Error("The file holds no trajectories."))) });
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(fileInput, new File(["{}"], "empty.json", { type: "application/json" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The file holds no trajectories.");
  });
});
