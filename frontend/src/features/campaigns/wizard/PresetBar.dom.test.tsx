import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { catalogClassSchema, catalogStacksSchema } from "../../../domain/cluster/campaignApi";
import { sampleCatalogClasses, sampleCatalogStacks } from "../../../test/fixtures/campaignCatalog";
import type { BuilderCatalog } from "./configBuilder";
import { PresetBar } from "./PresetBar";
import { WithQueries } from "./wizardTestHarness";
import { draftOf } from "./wizardTestData";
import type { WizardDraft } from "./wizardState";

// The wizard's preset bar against a fake operator API.

const parsed = catalogStacksSchema.parse(sampleCatalogStacks);
const catalog: BuilderCatalog = { stacks: parsed.stacks, generators: parsed.trajectory_generators };
const classes = sampleCatalogClasses.map((entry) => catalogClassSchema.parse(entry));

const SHIPPED = {
  preset_id: "01_smoke_test",
  name: "Smoke test: one case per two-vessel class",
  description: "Checks that every step works on the cluster.",
  builtin: true,
  steps: ["scene_generation", "trajectory_generation", "simulation"],
  config: {
    format: 2,
    name: "Smoke test: one case per two-vessel class",
    steps: ["scene_generation", "trajectory_generation", "simulation"],
    scope: [{ patterns: ["2vessel_0obstacle_scenarios"], quota: 1, failure_budget: 1 }],
    execution: { runs: [{ name: "kinematic replay", stack: { simulation_layer: "kinematic", mode: "replay" }, monitor: "post_hoc" }] },
  },
  created_at: null,
  updated_at: null,
};
const SAVED = { ...SHIPPED, preset_id: "p-1", name: "nightly", builtin: false, description: "", created_at: "2026-10-29T09:30:00+00:00", updated_at: "2026-10-29T09:30:00+00:00" };
const SITL_PRESET = {
  ...SHIPPED,
  preset_id: "06_sitl",
  name: "SITL replay",
  config: {
    ...SHIPPED.config,
    scope: [{ patterns: ["2vessel_0obstacle_scenarios"], quota: 2, failure_budget: 2 }],
    execution: { runs: [{ stack: { simulation_layer: "ardupilot_sim", mode: "replay" }, monitor: "post_hoc" }] },
  },
};
const THREE_VESSELS = {
  ...SHIPPED,
  preset_id: "03_three",
  name: "Three-vessel encounters",
  config: { ...SHIPPED.config, scope: [{ patterns: ["3vessel_*_scenarios"], quota: 3, failure_budget: 3 }] },
};

let presets: Record<string, unknown>[];
let requests: { method: string; path: string; body: unknown }[];

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

async function fakeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = new URL(String(input));
  const method = init?.method ?? "GET";
  requests.push({ method, path: url.pathname, body: init?.body ? JSON.parse(String(init.body)) : null });
  if (url.pathname === "/cluster/campaign-presets" && method === "POST") {
    const body = JSON.parse(String(init?.body)) as { name: string; description: string; config: Record<string, unknown> };
    if (presets.some((preset) => preset.name === body.name)) {
      return json({ detail: `a saved preset is named '${body.name}'; replace it or choose another name` }, 409);
    }
    const saved = { ...SAVED, preset_id: "p-2", name: body.name, description: body.description, config: body.config };
    presets = [...presets, saved];
    return json(saved, 201);
  }
  if (url.pathname === "/cluster/campaign-presets/p-1" && method === "DELETE") {
    presets = presets.filter((preset) => preset.preset_id !== "p-1");
    return new Response(null, { status: 204 });
  }
  if (url.pathname === "/cluster/campaign-presets") {
    return json(presets);
  }
  return json({ detail: "not found" }, 404);
}

function setup(draft: WizardDraft = draftOf()) {
  const loaded: WizardDraft[] = [];
  render(
    <WithQueries>
      <PresetBar draft={draft} catalog={catalog} classes={classes} onLoad={(next) => loaded.push(next)} />
    </WithQueries>
  );
  return { loaded, user: userEvent.setup() };
}

/** Opens the preset catalog once the presets are read. */
async function openCatalog(user: ReturnType<typeof userEvent.setup>): Promise<HTMLElement> {
  await user.click(await screen.findByRole("button", { name: /^Browse \d+ presets$/ }));
  return screen.getByRole("dialog", { name: "Campaign presets" });
}

function presetCard(dialog: HTMLElement, name: string): HTMLElement {
  return within(dialog).getByRole("article", { name });
}

function presetNames(dialog: HTMLElement): (string | null)[] {
  return within(dialog)
    .queryAllByRole("article")
    .map((card) => card.getAttribute("aria-label"));
}

/** Opens the save form; the disclosure remembers its state per browser, so it may be open already. */
async function openSaving(user: ReturnType<typeof userEvent.setup>) {
  const toggle = screen.queryByRole("button", { name: "Save this draft as a preset" });
  if (toggle) {
    await user.click(toggle);
  }
}

beforeEach(() => {
  presets = [SHIPPED, SAVED];
  requests = [];
  vi.stubGlobal("fetch", vi.fn(fakeFetch));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the preset bar", () => {
  it("lists the shipped and the saved presets apart and loads one into the wizard", async () => {
    const { loaded, user } = setup();
    const dialog = await openCatalog(user);
    expect(within(dialog).getByRole("region", { name: "Shipped with the control node" })).toBeVisible();
    expect(within(dialog).getByRole("region", { name: "Saved on this cluster" })).toBeVisible();
    const card = presetCard(dialog, SHIPPED.name);
    expect(within(card).getByText(/Checks that every step works on the cluster/)).toBeVisible();
    await user.click(within(card).getByRole("button", { name: "Load into the wizard" }));
    expect(loaded).toHaveLength(1);
    expect(loaded[0].name).toBe("Smoke test: one case per two-vessel class");
    expect(loaded[0].scope[0].patterns).toEqual(["2vessel_0obstacle_scenarios"]);
    expect(loaded[0].runs[0].stackId).toBe("kinematic.replay");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(`Started from the preset "${SHIPPED.name}"`);
  });

  it("filters the presets by the vessels of their scope and by their stack", async () => {
    presets = [SHIPPED, SITL_PRESET, THREE_VESSELS, SAVED];
    const { user } = setup();
    const dialog = await openCatalog(user);

    await user.click(within(dialog).getByRole("checkbox", { name: /3 vessels/ }));
    expect(presetNames(dialog)).toEqual([THREE_VESSELS.name]);

    await user.click(within(dialog).getByRole("checkbox", { name: /3 vessels/ }));
    await user.click(within(dialog).getByRole("checkbox", { name: /Replay on ArduPilot SITL/ }));
    expect(presetNames(dialog)).toEqual([SITL_PRESET.name]);
    expect(within(dialog).getByRole("status")).toHaveTextContent("1 of 4 presets");
  });

  it("states what a preset selects and runs on its card", async () => {
    presets = [SITL_PRESET];
    const { user } = setup();
    const dialog = await openCatalog(user);
    const card = presetCard(dialog, SITL_PRESET.name);
    expect(within(card).getByText("2 vessels, no obstacles")).toBeVisible();
    expect(within(card).getByText("3 FECs, 6 cases")).toBeVisible();
    expect(within(card).getByText("Replay on ArduPilot SITL")).toBeVisible();
    expect(within(card).getByText("Whole chain")).toBeVisible();
  });

  it("warns on the card of a preset whose stack the control node cannot run", async () => {
    presets = [{ ...SHIPPED, config: { ...SHIPPED.config, execution: { runs: [{ stack: { simulation_layer: "somewhere", mode: "replay" } }] } } }];
    const { user } = setup();
    const dialog = await openCatalog(user);
    expect(within(dialog).getByText(/A run needs a stack this control node cannot run/)).toBeVisible();
  });

  it("asks before replacing a draft that has entries", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const { loaded, user } = setup(draftOf((draft) => void (draft.name = "mine")));
    const dialog = await openCatalog(user);
    await user.click(within(presetCard(dialog, SHIPPED.name)).getByRole("button", { name: "Load into the wizard" }));
    expect(confirm).toHaveBeenCalled();
    expect(loaded).toHaveLength(0);
    expect(screen.getByRole("dialog")).toBeVisible();
  });

  it("waits for the control node's stacks before loading", async () => {
    render(
      <WithQueries>
        <PresetBar draft={draftOf()} catalog={null} onLoad={() => undefined} />
      </WithQueries>
    );
    const dialog = await openCatalog(userEvent.setup());
    expect(within(presetCard(dialog, SHIPPED.name)).getByRole("button", { name: "Load into the wizard" })).toBeDisabled();
  });

  it("says so when the control node offers no presets", async () => {
    presets = [];
    setup();
    expect(await screen.findByRole("button", { name: "The control node offers no presets" })).toBeDisabled();
  });

  it("saves the draft as a preset without its input", async () => {
    const draft = draftOf((next) => {
      next.name = "two-vessel nightly";
      next.input.scenarios = [{ id: "s", fileName: "a.problem", name: "a", ref: { sha256: "a".repeat(64), size_bytes: 1, kind: "functional_scenario" }, quota: 1, failureBudget: 0, uploadedAt: 0 }];
    });
    const { user } = setup(draft);
    await openSaving(user);
    await user.type(screen.getByRole("textbox", { name: "Description" }), "every night");
    await user.click(screen.getByRole("button", { name: "Save as preset" }));
    expect(await screen.findByText('Saved the preset "two-vessel nightly" on the control node.')).toBeVisible();
    const post = requests.find((request) => request.method === "POST");
    expect(post?.body).toMatchObject({ name: "two-vessel nightly", description: "every night", replace: false });
    expect((post?.body as { config: Record<string, unknown> }).config.input).toBeUndefined();
  });

  it("says why a taken name was refused", async () => {
    const { user } = setup(draftOf((draft) => void (draft.name = "nightly")));
    await openSaving(user);
    await user.click(screen.getByRole("button", { name: "Save as preset" }));
    expect(await screen.findByText(/a saved preset is named 'nightly'/)).toBeVisible();
  });

  it("deletes a saved preset but offers no delete for a shipped one", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const { user } = setup();
    const dialog = await openCatalog(user);
    expect(within(presetCard(dialog, SHIPPED.name)).queryByRole("button", { name: "Delete the preset" })).not.toBeInTheDocument();
    await user.click(within(presetCard(dialog, "nightly")).getByRole("button", { name: "Delete the preset" }));
    expect(await screen.findByText('Deleted the preset "nightly".')).toBeVisible();
    expect(requests.some((request) => request.method === "DELETE" && request.path === "/cluster/campaign-presets/p-1")).toBe(true);
    await waitFor(() => expect(presetNames(dialog)).toEqual([SHIPPED.name]));
  });
});
