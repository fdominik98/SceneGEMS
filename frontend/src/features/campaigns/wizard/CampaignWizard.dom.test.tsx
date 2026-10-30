import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { parse } from "yaml";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CampaignWizard } from "./CampaignWizard";
import { emptyDraft, useWizardStore, WIZARD_STORAGE_KEY } from "./wizardState";
import { WithQueries } from "./wizardTestHarness";

const mocks = vi.hoisted(() => ({
  client: { baseUrl: "http://master.test" },
  createCampaign: vi.fn(),
  validateCampaignConfig: vi.fn(),
}));

vi.mock("../useCampaignData", () => {
  const idle = { data: undefined, error: null, isLoading: false, refetch: () => Promise.resolve() };
  return { useOperatorClient: () => mocks.client, useCatalogClasses: () => idle, useCatalogStacks: () => idle, retryUnlessUnreachable: () => false };
});
// The preset bar reads the master's presets; these tests start from an empty draft
vi.mock("./useCampaignPresets", () => {
  const idle = { mutate: () => undefined, isPending: false, isError: false, error: null };
  return { useCampaignPresets: () => ({ data: [], isLoading: false, isError: false, error: null }), useSaveCampaignPreset: () => idle, useDeleteCampaignPreset: () => idle };
});
vi.mock("../../../domain/cluster/campaignApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../domain/cluster/campaignApi")>()),
  createCampaign: mocks.createCampaign,
  validateCampaignConfig: mocks.validateCampaignConfig,
}));

const VALID = { valid: true, name: "n", config_hash: "f".repeat(64), fecs: [], cases_planned: 2, runs: [] };

function pages(): string[] {
  const nav = screen.getByRole("navigation", { name: "Wizard steps" });
  return within(nav)
    .getAllByRole("button")
    .map((button) => button.querySelector(".wiz-step-label")?.textContent ?? "");
}

beforeEach(() => {
  localStorage.removeItem(WIZARD_STORAGE_KEY);
  useWizardStore.getState().reset();
  mocks.createCampaign.mockReset();
  mocks.validateCampaignConfig.mockReset();
});

function renderWizard(onCreated = vi.fn()) {
  render(
    <WithQueries>
      <CampaignWizard onClose={() => undefined} onCreated={onCreated} />
    </WithQueries>
  );
  return { onCreated, user: userEvent.setup() };
}

describe("the wizard's pages follow the chosen steps", () => {
  it("goes through every page for the whole chain, starting with Steps and Input", () => {
    renderWizard();
    expect(pages()).toEqual(["Steps", "Input", "Domain", "Trajectories", "Runs", "Resources", "Policy", "Review"]);
    expect(screen.getByRole("radio", { name: /Scene generation\s*Generates scenes/ })).toBeChecked();
  });

  it("hides the trajectories and runs pages for scene generation alone, and the runs page without simulation", async () => {
    const { user } = renderWizard();
    await user.click(screen.getByRole("radio", { name: /Scene generation\s*Produces scenes/ }));
    expect(pages()).toEqual(["Steps", "Input", "Domain", "Resources", "Policy", "Review"]);
    await user.click(screen.getByRole("radio", { name: /Trajectory generation\s*Produces trajectories/ }));
    expect(pages()).toEqual(["Steps", "Input", "Domain", "Trajectories", "Resources", "Policy", "Review"]);
  });

  it("shows the Input page of the first step and walks Next past the hidden pages", async () => {
    const { user } = renderWizard();
    await user.click(screen.getByRole("radio", { name: /Trajectory generation\s*Plans the trajectories/ }));
    await user.click(screen.getByRole("radio", { name: /Trajectory generation\s*Produces trajectories/ }));
    await user.click(screen.getByRole("button", { name: "Next: Input" }));
    expect(screen.getByRole("heading", { name: "From Campaign History" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Next: Domain" }));
    await user.click(screen.getByRole("button", { name: "Next: Trajectories" }));
    await user.click(screen.getByRole("button", { name: "Next: Resources" }));
    expect(screen.getByRole("button", { name: "Back" })).toBeEnabled();
  });

  it("falls back to the first page when the stored page is no longer part of the steps", () => {
    useWizardStore.setState({ step: "runs", draft: { ...emptyDraft(), steps: ["scene_generation"] } });
    renderWizard();
    expect(screen.getByRole("textbox", { name: "Name" })).toBeVisible();
  });
});

describe("creating the campaign", () => {
  it("sends the format 3 config with kind campaign and origin wizard", async () => {
    mocks.validateCampaignConfig.mockResolvedValue(VALID);
    mocks.createCampaign.mockResolvedValue({ campaign_id: "new-1" });
    const draft = emptyDraft();
    draft.name = "scenes only";
    draft.steps = ["scene_generation"];
    draft.sceneMonitor = "post_hoc";
    draft.scope = [{ id: "s", classes: ["2vessel_0obstacle_scenarios/functional_model1"], patterns: [], quota: 2, failureBudget: 0 }];
    useWizardStore.setState({ step: "review", draft });
    const { onCreated, user } = renderWizard();

    await waitFor(() => expect(mocks.validateCampaignConfig).toHaveBeenCalled());
    const sent = mocks.validateCampaignConfig.mock.calls[0][1] as string;
    expect(parse(sent)).toMatchObject({ format: 3, name: "scenes only", steps: ["scene_generation"], scene_generation: { monitor: "post_hoc" } });
    expect(parse(sent)).not.toHaveProperty("execution");
    expect(parse(sent)).not.toHaveProperty("trajectories");

    const create = await screen.findByRole("button", { name: "Create paused" });
    await waitFor(() => expect(create).toBeEnabled());
    await user.click(create);
    await waitFor(() => expect(mocks.createCampaign).toHaveBeenCalled());
    expect(mocks.createCampaign).toHaveBeenCalledWith(mocks.client, sent, { start: false, kind: "campaign", origin: "wizard" });
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("new-1"));
    expect(useWizardStore.getState().draft.name).toBe("");
  });

  it("does not check the master while a later start has no input, and says what is missing", async () => {
    const draft = emptyDraft();
    draft.name = "needs input";
    draft.steps = ["simulation"];
    useWizardStore.setState({ step: "review", draft });
    renderWizard();
    expect(await screen.findByText(/Not ready to check/)).toBeVisible();
    expect(screen.getByText(/Add at least one of the trajectories the campaign starts from/)).toBeVisible();
    expect(mocks.validateCampaignConfig).not.toHaveBeenCalled();
  });
});
