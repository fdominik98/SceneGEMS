import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { parse } from "yaml";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { OperatorApiError } from "../../../domain/cluster/operatorApi";
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

/** The pages in the list that replaces the campaign map. */
function pages(): string[] {
  const nav = screen.getByRole("navigation", { name: "Wizard steps" });
  return within(nav)
    .getAllByRole("button")
    .map((button) => button.querySelector(".wiz-step-label")?.textContent ?? "");
}

const ALL_PAGES = ["Steps", "Input", "Domain", "Scene generation", "Trajectory generation", "Simulation", "Resources", "Policy", "Review"];

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
  it("goes through every page for the whole chain, starting with Steps and Input", async () => {
    const { user } = renderWizard();
    await user.click(screen.getByRole("button", { name: "List" }));
    expect(pages()).toEqual(ALL_PAGES);
    expect(screen.getByRole("radio", { name: /Scene generation\s*Generates scenes/ })).toBeChecked();
    expect(screen.getByText("Page 1 of 9")).toBeVisible();
  });

  it("shows a page for each step the campaign runs and hides the others", async () => {
    const { user } = renderWizard();
    await user.click(screen.getByRole("button", { name: "List" }));
    await user.click(screen.getByRole("radio", { name: /Scene generation\s*Produces scenes/ }));
    expect(pages()).toEqual(["Steps", "Input", "Domain", "Scene generation", "Resources", "Policy", "Review"]);
    await user.click(screen.getByRole("radio", { name: /Trajectory generation\s*Produces trajectories/ }));
    expect(pages()).toEqual(["Steps", "Input", "Domain", "Scene generation", "Trajectory generation", "Resources", "Policy", "Review"]);
  });

  it("shows the Input page of the first step and walks Next past the hidden pages", async () => {
    const { user } = renderWizard();
    await user.click(screen.getByRole("radio", { name: /Trajectory generation\s*Plans the trajectories/ }));
    await user.click(screen.getByRole("radio", { name: /Trajectory generation\s*Produces trajectories/ }));
    await user.click(screen.getByRole("button", { name: "Next: Input" }));
    expect(screen.getByRole("heading", { name: "From Campaign History" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Next: Domain" }));
    await user.click(screen.getByRole("button", { name: "Next: Trajectory generation" }));
    expect(screen.getByRole("heading", { name: "Trajectory generation", level: 3 })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Next: Resources" }));
    expect(screen.getByRole("button", { name: "Back" })).toBeEnabled();
    expect(screen.getByText("Page 5 of 7")).toBeVisible();
  });

  it("falls back to the first page when the stored page is no longer part of the steps", () => {
    useWizardStore.setState({ step: "runs", draft: { ...emptyDraft(), steps: ["scene_generation"] } });
    renderWizard();
    expect(screen.getByRole("textbox", { name: "Name" })).toBeVisible();
  });
});

describe("the campaign map", () => {
  it("is shown in place of the list of pages and opens the page of the box clicked", async () => {
    const { user } = renderWizard();
    const map = screen.getByRole("region", { name: "Campaign map" });
    expect(screen.queryByRole("navigation", { name: "Wizard steps" })).not.toBeInTheDocument();
    expect(within(map).getByRole("button", { name: /^Steps/ })).toHaveAttribute("aria-current", "step");

    await user.click(within(map).getByRole("button", { name: /^Scene generation/ }));
    expect(screen.getByRole("heading", { name: "Scene generation", level: 3 })).toBeVisible();
    expect(screen.getByRole("group", { name: "Monitor after scene generation" })).toBeVisible();
    expect(within(map).getByRole("button", { name: /^Scene generation/ })).toHaveAttribute("aria-current", "step");
  });

  it("follows the draft: a changed monitor and a step left out show at once", async () => {
    const { user } = renderWizard();
    const map = screen.getByRole("region", { name: "Campaign map" });
    expect(within(map).getByRole("button", { name: /^Run 1/ })).toBeVisible();
    await user.click(screen.getByRole("radio", { name: /Trajectory generation\s*Produces trajectories/ }));
    expect(within(map).getByRole("button", { name: /^Simulation\s*Not run/ })).toBeVisible();
    expect(within(map).queryByRole("button", { name: /^Run 1/ })).not.toBeInTheDocument();

    await user.click(within(map).getByRole("button", { name: /^Scene generation/ }));
    await user.click(within(screen.getByRole("group", { name: "Monitor after scene generation" })).getByRole("radio", { name: /Post hoc monitor/ }));
    expect(within(map).getByRole("button", { name: /^Scene generation/ })).toHaveTextContent("Post hoc monitor");
  });

  it("keeps the choice of the map or the list in this browser", async () => {
    const { user } = renderWizard();
    await user.click(screen.getByRole("button", { name: "List" }));
    expect(screen.getByRole("button", { name: "List" })).toHaveAttribute("aria-pressed", "true");
    expect(localStorage.getItem("scenegems:campaign-wizard-map")).toBe("false");
    await user.click(screen.getByRole("button", { name: "Map" }));
    expect(screen.getByRole("region", { name: "Campaign map" })).toBeVisible();
  });
});

describe("explanations", () => {
  it("are left out until asked for, and the choice is kept in this browser", async () => {
    const { user } = renderWizard();
    const wizard = screen.getByRole("heading", { name: "New campaign" }).closest(".wiz");
    expect(wizard).toHaveClass("wiz--terse");
    await user.click(screen.getByRole("checkbox", { name: "Show explanations" }));
    expect(wizard).not.toHaveClass("wiz--terse");
    expect(localStorage.getItem("scenegems:campaign-wizard-explanations")).toBe("true");
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
    draft.scope = [{ id: "s", classes: ["2vessel_0obstacle_scenarios/fec1"], patterns: [], quota: 2, failureBudget: 0 }];
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

  it("does not say the campaign was not created when the master did not answer in time", async () => {
    mocks.validateCampaignConfig.mockResolvedValue(VALID);
    mocks.createCampaign.mockRejectedValue(
      new OperatorApiError("timeout", "http://master.test did not answer within 60 s; the master may have created it anyway, so check Campaign History before you create it again", "/cluster/campaigns")
    );
    const draft = emptyDraft();
    draft.name = "slow master";
    draft.steps = ["scene_generation"];
    draft.scope = [{ id: "s", classes: ["2vessel_0obstacle_scenarios/fec1"], patterns: [], quota: 2, failureBudget: 0 }];
    useWizardStore.setState({ step: "review", draft });
    const { onCreated, user } = renderWizard();
    const create = await screen.findByRole("button", { name: "Create paused" });
    await waitFor(() => expect(create).toBeEnabled());
    await user.click(create);
    expect(await screen.findByText(/The master did not confirm the campaign/)).toHaveTextContent("check Campaign History before you create it again");
    expect(screen.queryByText(/was not created/)).not.toBeInTheDocument();
    expect(onCreated).not.toHaveBeenCalled();
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
