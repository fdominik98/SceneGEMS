import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { campaignRowSchema } from "../../../domain/cluster/schemas";
import { outputRowSchema, type OutputRow } from "../../../domain/cluster/historyApi";
import { OperatorApiError } from "../../../domain/cluster/operatorApi";
import { sampleArtifactRef, sampleCampaignRow, sampleDroppedOutput, sampleSceneOutput, sampleTrajectoryOutput, sampleWorkbenchRow } from "../../../test/fixtures/historyViews";
import { InputStep } from "./InputStep";
import { parseReasons } from "./reasons";
import type { CatalogState } from "./stepTypes";
import { StepHarness, WithQueries } from "./wizardTestHarness";
import { draftOf } from "./wizardTestData";
import type { WizardDraft } from "./wizardState";

const mocks = vi.hoisted(() => ({
  client: { baseUrl: "http://master.test" },
  uploadArtifact: vi.fn(),
  listHistory: vi.fn(),
  listOutputs: vi.fn(),
}));

vi.mock("../useCampaignData", () => ({ useOperatorClient: () => mocks.client }));
vi.mock("../../../domain/cluster/historyApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../domain/cluster/historyApi")>()),
  uploadArtifact: mocks.uploadArtifact,
  listHistory: mocks.listHistory,
  listOutputs: mocks.listOutputs,
}));

const catalog: CatalogState = { classes: [], classesError: null, classesLoading: false, stacks: undefined, stacksError: null, stacksLoading: false, retry: () => undefined };
const SCENE_SHA = "5".repeat(64);

function ref(overrides: Record<string, unknown> = {}) {
  return sampleArtifactRef({ sha256: SCENE_SHA, ...overrides });
}

function setup(change: (draft: WizardDraft) => void, reasons = parseReasons([])) {
  const seen: WizardDraft[] = [];
  render(
    <WithQueries>
      <StepHarness Page={InputStep} extra={{ catalog }} initial={draftOf(change)} reasons={reasons} onDraft={(draft) => seen.push(draft)} />
    </WithQueries>
  );
  return { latest: () => seen[seen.length - 1], user: userEvent.setup() };
}

function file(name: string, text: string): File {
  return new File([text], name, { type: "application/json" });
}

beforeEach(() => {
  mocks.uploadArtifact.mockReset();
  mocks.listHistory.mockReset();
  mocks.listOutputs.mockReset();
});

describe("Input for a start with scene generation", () => {
  it("uploads a scenario file as a functional scenario and shows it with a quota and failure budget", async () => {
    mocks.uploadArtifact.mockResolvedValue(ref({ kind: "functional_scenario", media_type: "text/plain", size_bytes: 812 }));
    const { latest, user } = setup(() => undefined);
    await user.upload(screen.getByLabelText("Add scenario files"), file("my_head_on.problem", "problem p { }"));
    await waitFor(() => expect(latest().input.scenarios).toHaveLength(1));
    expect(mocks.uploadArtifact).toHaveBeenCalledWith(mocks.client, "problem p { }", "functional_scenario", "text/plain");
    expect(latest().input.scenarios[0]).toMatchObject({ name: "my_head_on", fileName: "my_head_on.problem", quota: 1, failureBudget: 0, ref: { sha256: SCENE_SHA, kind: "functional_scenario" } });

    const card = screen.getByRole("region", { name: "Scenario file 1" });
    expect(within(card).getByText(/the master deletes it in about 24 hours unless a campaign uses it/)).toBeVisible();
    const quota = within(card).getByRole("spinbutton", { name: "Quota" });
    await user.clear(quota);
    await user.type(quota, "4");
    expect(latest().input.scenarios[0].quota).toBe(4);
    await user.click(within(card).getByRole("button", { name: "Remove file" }));
    expect(latest().input.scenarios).toEqual([]);
  });

  it("says that uploaded files expire after 24 hours", () => {
    setup(() => undefined);
    expect(screen.getAllByText(/kept for 24 hours/).length).toBeGreaterThan(0);
  });

  it("shows why an upload failed and lets it be dismissed", async () => {
    mocks.uploadArtifact.mockRejectedValue(new OperatorApiError("http", "the file is larger than the limit", "/cluster/artifacts", 413));
    const { latest, user } = setup(() => undefined);
    await user.upload(screen.getByLabelText("Add scenario files"), file("big.problem", "x"));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("big.problem");
    expect(latest()).toBeUndefined();
    await user.click(within(alert).getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows the master's reasons on the scenario file they name", () => {
    setup(
      (draft) => {
        draft.input.scenarios = [{ id: "s1", fileName: "a.problem", name: "a", ref: { sha256: SCENE_SHA, size_bytes: 3, kind: "functional_scenario" }, quota: 1, failureBudget: 0, uploadedAt: Date.now() }];
      },
      parseReasons(["input.functional_scenarios.0 (a): no artifact abc in the artifact store"])
    );
    expect(within(screen.getByRole("region", { name: "Scenario file 1" })).getByRole("alert")).toHaveTextContent("no artifact abc in the artifact store");
  });

  it("keeps the catalog scope below the scenario files", () => {
    setup(() => undefined);
    expect(screen.getByRole("heading", { name: "Catalog FECs" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Functional scenario files" })).toBeVisible();
  });
});

describe("Input for a later start", () => {
  const entries = [
    campaignRowSchema.parse(sampleCampaignRow({ campaign_id: "c1", name: "Head-on scenes" })),
    campaignRowSchema.parse(sampleWorkbenchRow({ campaign_id: "w1", name: "Trajectory run", steps: ["trajectory_generation"] })),
  ];
  const scenes: OutputRow[] = [
    outputRowSchema.parse(sampleSceneOutput({ case_id: 5, case_index: 0, artifact: ref({ sha256: "1".repeat(64) }) })),
    outputRowSchema.parse(sampleSceneOutput({ case_id: 6, case_index: 1, artifact: ref({ sha256: "2".repeat(64) }) })),
    outputRowSchema.parse(sampleDroppedOutput({ case_id: 7, case_index: 2 })),
  ];

  function history() {
    mocks.listHistory.mockResolvedValue({ items: entries, total: entries.length });
    mocks.listOutputs.mockImplementation(async (_client, _id, filters: { offset?: number }) => ({ items: (filters.offset ?? 0) === 0 ? scenes : [], total: scenes.length }));
  }

  it("lists the entries that have scenes, then their outputs, and adds a chosen scene as an item with its source", async () => {
    history();
    const { latest, user } = setup((draft) => void (draft.steps = ["trajectory_generation"]));
    expect(await screen.findByText("Head-on scenes")).toBeVisible();
    // The workbench entry ran trajectory generation only: it has no scenes
    expect(screen.queryByText("Trajectory run")).not.toBeInTheDocument();
    expect(mocks.listHistory).toHaveBeenCalledWith(mocks.client, { q: undefined, limit: 50 }, expect.anything());

    await user.click(screen.getByRole("button", { name: "Choose Head-on scenes" }));
    expect(await screen.findByText("3 outputs in scene generation")).toBeVisible();
    expect(mocks.listOutputs).toHaveBeenCalledWith(mocks.client, "c1", { step: "scene_generation", limit: 25, offset: 0 }, expect.anything());
    // A dropped case has no scene to start from
    expect(screen.getByRole("button", { name: "Add case 2" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Add case 1" }));
    expect(latest().input.items).toHaveLength(1);
    expect(latest().input.items[0]).toMatchObject({
      name: "Head-on scenes case 1",
      ref: { sha256: "2".repeat(64), kind: "scene" },
      source: { campaign_id: "c1", case_id: 6, step: "scene_generation" },
      uploadedAt: null,
    });
    expect(screen.getByRole("button", { name: "Added case 1" })).toBeDisabled();
    expect(screen.getByRole("row", { name: "Input item 1" })).toBeVisible();
  });

  it("searches the entries by name once typing pauses, not on every key", async () => {
    history();
    const { user } = setup((draft) => void (draft.steps = ["trajectory_generation"]));
    await screen.findByText("Head-on scenes");
    const reads = mocks.listHistory.mock.calls.length;
    await user.type(screen.getByRole("searchbox", { name: "Find an entry by name" }), "head");
    await waitFor(() => expect(mocks.listHistory).toHaveBeenLastCalledWith(mocks.client, { q: "head", limit: 50 }, expect.anything()));
    // one read for the whole word, none for "h", "he" or "hea"
    expect(mocks.listHistory.mock.calls.slice(reads).map((call) => call[1].q)).toEqual(["head"]);
  });

  it("adds every usable output of the entry at once and skips the unusable one", async () => {
    history();
    const { latest, user } = setup((draft) => void (draft.steps = ["trajectory_generation"]));
    await user.click(await screen.findByRole("button", { name: "Choose Head-on scenes" }));
    await user.click(await screen.findByRole("button", { name: "Add every output (3)" }));
    await waitFor(() => expect(latest().input.items).toHaveLength(2));
    expect(latest().input.items.map((item) => item.name)).toEqual(["Head-on scenes case 0", "Head-on scenes case 1"]);
    expect(await screen.findByText("Added 2 outputs.")).toBeVisible();
    // Adding again finds nothing new
    await user.click(screen.getByRole("button", { name: "Add every output (3)" }));
    expect(await screen.findByText("Added 0 outputs.")).toBeVisible();
    expect(latest().input.items).toHaveLength(2);
  });

  it("offers the planned trajectories and the recorded runs of an entry to a simulation start, step by step", async () => {
    const both = campaignRowSchema.parse(sampleCampaignRow({ campaign_id: "c9", name: "Full chain", steps: ["scene_generation", "trajectory_generation", "simulation"] }));
    mocks.listHistory.mockResolvedValue({ items: [both], total: 1 });
    const planned = outputRowSchema.parse(sampleTrajectoryOutput());
    mocks.listOutputs.mockResolvedValue({ items: [planned], total: 1 });
    const { latest, user } = setup((draft) => void (draft.steps = ["simulation"]));
    await user.click(await screen.findByRole("button", { name: "Choose Full chain" }));
    const steps = await screen.findByRole("group", { name: "Step of the entry" });
    expect(within(steps).getAllByRole("button").map((button) => button.textContent)).toEqual(["Trajectory generation", "Simulation"]);
    expect(await screen.findByText("1 output in trajectory generation")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Add case 0" }));
    expect(latest().input.items[0]).toMatchObject({ ref: { kind: "trajectory_data", pointer: "/trajectories" }, source: { campaign_id: "c9", step: "trajectory_generation" } });
    await user.click(within(steps).getByRole("button", { name: "Simulation" }));
    await waitFor(() => expect(mocks.listOutputs).toHaveBeenLastCalledWith(mocks.client, "c9", { step: "simulation", limit: 25, offset: 0 }, expect.anything()));
  });

  it("uploads a scene file as one item that expires unless a campaign uses it", async () => {
    history();
    mocks.uploadArtifact.mockResolvedValue(ref({ kind: "scene", size_bytes: 321 }));
    const { latest, user } = setup((draft) => void (draft.steps = ["trajectory_generation"]));
    await user.upload(screen.getByLabelText("Add scene files (JSON)"), file("head_on.json", "{\"scene\": 1}"));
    await waitFor(() => expect(latest().input.items).toHaveLength(1));
    expect(mocks.uploadArtifact).toHaveBeenCalledWith(mocks.client, "{\"scene\": 1}", "scene", "application/json");
    expect(latest().input.items[0]).toMatchObject({ name: "head_on", source: { file: "head_on.json" }, ref: { kind: "scene", size_bytes: 321 } });
    expect(latest().input.items[0].uploadedAt).not.toBeNull();
    expect(screen.getByText(/the master deletes it in about 24 hours unless a campaign uses it/)).toBeVisible();
  });

  it("uploads trajectory files for a simulation start", async () => {
    history();
    mocks.uploadArtifact.mockResolvedValue(ref({ kind: "trajectories" }));
    const { latest, user } = setup((draft) => void (draft.steps = ["simulation"]));
    await user.upload(screen.getByLabelText("Add trajectory files (JSON)"), file("plan.json", "{\"trajectories\": []}"));
    await waitFor(() => expect(latest().input.items).toHaveLength(1));
    expect(mocks.uploadArtifact).toHaveBeenCalledWith(mocks.client, "{\"trajectories\": []}", "trajectories", "application/json");
  });

  it("refuses a scene file that is not JSON before uploading it", async () => {
    history();
    const { user } = setup((draft) => void (draft.steps = ["trajectory_generation"]));
    await user.upload(screen.getByLabelText("Add scene files (JSON)"), file("bad.json", "{oops"));
    expect(await screen.findByRole("alert")).toHaveTextContent("bad.json: The file is not valid JSON.");
    expect(mocks.uploadArtifact).not.toHaveBeenCalled();
  });

  it("renames and removes items, and shows the master's reason on the item it names", async () => {
    history();
    const { latest, user } = setup(
      (draft) => {
        draft.steps = ["trajectory_generation"];
        draft.input.items = [
          { id: "i1", name: "first", ref: { sha256: SCENE_SHA, size_bytes: 3, kind: "scene" }, source: { file: "a.json" }, uploadedAt: Date.now() },
          { id: "i2", name: "second", ref: { sha256: "6".repeat(64), size_bytes: 3, kind: "scene" }, source: { campaign_id: "c1", case_id: 2, step: "scene_generation" }, uploadedAt: null },
        ];
      },
      parseReasons(["input.items.1 (second): no artifact 666 in the artifact store"])
    );
    expect(within(screen.getByRole("row", { name: "Input item 2" })).getByRole("alert")).toHaveTextContent("no artifact 666");
    const name = screen.getByRole("textbox", { name: "Name of item 1" });
    await user.clear(name);
    await user.type(name, "renamed");
    expect(latest().input.items[0].name).toBe("renamed");
    await user.click(screen.getByRole("button", { name: "Remove item 2" }));
    expect(latest().input.items.map((item) => item.id)).toEqual(["i1"]);
    await user.click(screen.getByRole("button", { name: "Remove item 1" }));
    expect(latest().input.items).toEqual([]);
    expect(screen.getByText(/Nothing chosen yet/)).toBeVisible();
  });

  it("says when Campaign History did not load and loads again on request", async () => {
    mocks.listHistory.mockRejectedValueOnce(new OperatorApiError("http", "master error", "/cluster/campaigns", 500)).mockResolvedValue({ items: entries, total: 2 });
    const { user } = setup((draft) => void (draft.steps = ["trajectory_generation"]));
    expect(await screen.findByRole("alert")).toHaveTextContent("Campaign History did not load");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Head-on scenes")).toBeVisible();
  });
});
