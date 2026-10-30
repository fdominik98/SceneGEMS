import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { GeneratedSceneData } from "../../../domain/simulation/types";
import { sampleFrames } from "../../../test/fixtures/sampleFrames";
import type { JobTypeResources } from "../cluster/workbenchResources";
import { useEntrySeedStore } from "../pages/entrySeedStore";
import { SceneGenerationControls } from "./SceneGenerationControls";

const RESOURCES: JobTypeResources = { jobType: "scene_generation", components: ["scene_generation"], nodes: 2, slots: 4, freeSlots: 3, blocker: null };

const VALID_SCENE: GeneratedSceneData = {
  scene: sampleFrames[0]!,
  evaluationData: {} as GeneratedSceneData["evaluationData"],
  valid: true,
};

function renderControls(overrides: Partial<Parameters<typeof SceneGenerationControls>[0]> = {}) {
  const props: Parameters<typeof SceneGenerationControls>[0] = {
    resources: RESOURCES,
    busy: false,
    batch: false,
    batchCount: 0,
    scenarioLabel: "2vessel/functional_model2",
    hasScenario: true,
    loadingLabel: null,
    domainProblem: null,
    specificationHidden: false,
    onShowSpecification: vi.fn(),
    onGenerate: vi.fn(),
    onStop: vi.fn(),
    timeoutSeconds: 240,
    onTimeoutSecondsChange: vi.fn(),
    enforceLowTcpa: false,
    onEnforceLowTcpaChange: vi.fn(),
    livePreview: true,
    onLivePreviewChange: vi.fn(),
    scene: null,
    sceneFileName: null,
    onOpenFile: vi.fn(),
    onExport: vi.fn(),
    onNext: vi.fn(),
    ...overrides,
  };
  render(<SceneGenerationControls {...props} />);
  return props;
}

describe("SceneGenerationControls", () => {
  beforeEach(() => useEntrySeedStore.setState({ fixed: null, last: null }));

  it("generates the scenario of the specification and says where it runs", async () => {
    const user = userEvent.setup();
    const props = renderControls();
    expect(screen.getByRole("group", { name: "Input" })).toHaveTextContent("Scenario 2vessel/functional_model2");
    expect(screen.getByText(/Generates as a job on the cluster: 4 slots on 2 machines, 3 free/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Generate scene" }));
    expect(props.onGenerate).toHaveBeenCalledTimes(1);
  });

  it("swaps the run button for Stop while generating", async () => {
    const user = userEvent.setup();
    const props = renderControls({ busy: true });
    expect(screen.queryByRole("button", { name: "Generate scene" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Stop" }));
    expect(props.onStop).toHaveBeenCalledTimes(1);
  });

  it("lists what blocks the run elsewhere", () => {
    renderControls({ domainProblem: "The cluster's domain configuration is incomplete.", resources: { ...RESOURCES, blocker: "No usable node generates scenes." } });
    const notices = screen.getByRole("list", { name: "Before it can run" });
    expect(notices).toHaveTextContent("The cluster's domain configuration is incomplete.");
    expect(notices).toHaveTextContent("No usable node generates scenes.");
    expect(screen.getByRole("button", { name: "Generate scene" })).toBeDisabled();
  });

  it("says in the Input row that the scenario is missing, and the run button says why it waits", async () => {
    const user = userEvent.setup();
    const props = renderControls({ hasScenario: false, scenarioLabel: null, specificationHidden: true });
    expect(screen.queryByRole("list", { name: "Before it can run" })).not.toBeInTheDocument();
    const input = screen.getByRole("group", { name: "Input" });
    expect(input).toHaveTextContent("Scenario none chosen");
    const generate = screen.getByRole("button", { name: "Generate scene" });
    expect(generate).toBeDisabled();
    expect(generate).toHaveAttribute("title", "Choose a preset or write a functional scenario in the specification pane first");
    await user.click(within(input).getByRole("button", { name: "Show the specification" }));
    expect(props.onShowSpecification).toHaveBeenCalledTimes(1);
  });

  it("waits for the presets of a batch", () => {
    renderControls({ batch: true, batchCount: 0 });
    expect(screen.getByRole("button", { name: "Generate 0 scenes" })).toBeDisabled();
    expect(screen.getByRole("group", { name: "Input" })).toHaveTextContent("Batch no presets selected");
  });

  it("counts the presets of a batch", () => {
    renderControls({ batch: true, batchCount: 3 });
    expect(screen.getByRole("button", { name: "Generate 3 scenes" })).toBeEnabled();
    expect(screen.getByRole("group", { name: "Input" })).toHaveTextContent("Batch 3 presets selected");
  });

  it("has the generation settings on one row", async () => {
    const user = userEvent.setup();
    const props = renderControls();
    const setup = screen.getByRole("group", { name: "Setup" });
    expect(within(setup).getByRole("spinbutton", { name: "Base seed" })).toBeInTheDocument();
    expect(within(setup).getByRole("spinbutton", { name: "Timeout (s)" })).toHaveValue(240);
    await user.click(within(setup).getByRole("checkbox", { name: "Low TCPA" }));
    expect(props.onEnforceLowTcpaChange).toHaveBeenCalledWith(true);
    await user.click(within(setup).getByRole("checkbox", { name: "Live preview" }));
    expect(props.onLivePreviewChange).toHaveBeenCalledWith(false);
  });

  it("goes on to trajectory generation only with a valid scene, and offers no simulation of a bare scene", async () => {
    const user = userEvent.setup();
    const props = renderControls({ scene: VALID_SCENE });
    const result = screen.getByRole("group", { name: "Result" });
    expect(result).toHaveTextContent("Scene generated complies with the specification");
    expect(screen.getByText("Valid scene")).toHaveClass("step-chip--ok");
    await user.click(within(result).getByRole("button", { name: "Next: Trajectory Generation" }));
    expect(props.onNext).toHaveBeenCalledTimes(1);
    await user.click(within(result).getByRole("button", { name: "Export the scene (JSON)" }));
    expect(props.onExport).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /Simulation/ })).not.toBeInTheDocument();
  });

  it("keeps the next step closed without a valid scene", () => {
    renderControls({ scene: { ...VALID_SCENE, valid: false } });
    expect(screen.getByRole("button", { name: "Next: Trajectory Generation" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Export the scene (JSON)" })).toBeDisabled();
    expect(screen.getByText("No valid scene")).toHaveClass("step-chip--warn");
  });

  it("opens a scene file as the shown scene", async () => {
    const user = userEvent.setup();
    const props = renderControls();
    const file = new File(["{}"], "head_on.json", { type: "application/json" });
    await user.upload(document.querySelector('input[type="file"]') as HTMLInputElement, file);
    expect(props.onOpenFile).toHaveBeenCalledWith(file);
  });
});
