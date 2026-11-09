import { describe, expect, it, vi } from "vitest";
import { sampleCampaignDetail } from "../../test/fixtures/clusterViews";
import { sampleCatalogClasses, sampleCatalogStacks, sampleValidationResult } from "../../test/fixtures/campaignCatalog";
import { sampleFormat2Config, sampleScenarioConfig } from "../../test/fixtures/historyViews";
import {
  campaignInputSchema,
  catalogClassSchema,
  catalogStackSchema,
  catalogStacksSchema,
  createCampaign,
  CREATE_TIMEOUT_MS,
  getCatalogStacks,
  inputItemSourceSchema,
  listCatalogClasses,
  stepMonitorSchema,
  validateCampaignConfig,
  validationResultSchema,
  type CampaignConfigFormat2,
} from "./campaignApi";
import { createOperatorClient, OperatorApiError } from "./operatorApi";

const BASE = "http://127.0.0.1:5174";

function jsonResponse(body: unknown, init: { status?: number; headers?: Record<string, string> } = {}): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json", ...init.headers },
  });
}

function clientWith(fetchImpl: (url: string, init?: RequestInit) => Promise<Response>) {
  const spy = vi.fn(fetchImpl);
  return { client: createOperatorClient(BASE, { fetch: spy as unknown as typeof fetch }), spy };
}

describe("catalog schemas", () => {
  it("parses the sample class catalog", () => {
    for (const entry of sampleCatalogClasses) {
      expect(catalogClassSchema.parse(entry).fec_id).toBe(entry.fec_id);
    }
  });

  it("parses the stacks catalog with its groups, monitors and generators", () => {
    const parsed = catalogStacksSchema.parse(sampleCatalogStacks);
    expect(parsed.stacks.map((stack) => stack.id)).toEqual([
      "kinematic.replay",
      "kinematic.usv_navigation",
      "ardupilot_sim.replay",
      "ardupilot_sim.usv_navigation",
      "gazebo_custom.replay",
      "gazebo_custom.usv_navigation",
    ]);
    expect(parsed.stacks[1].groups[0].parameters.map((parameter) => parameter.key)).toContain("goal");
    expect(parsed.stacks[0].environment.wind).toBe("unsupported");
    expect(parsed.stacks.map((stack) => stack.supports_early_stop)).toEqual([true, true, false, false, false, false]);
    expect(parsed.stacks[4].stack_section).toEqual({ simulation_layer: "gazebo", control_layer: "custom", mode: "replay" });
    const older = catalogStackSchema.parse({ ...sampleCatalogStacks.stacks[0], control_layer: undefined, stack_section: undefined }); // an older master leaves both out
    expect([older.control_layer, older.stack_section]).toEqual([undefined, undefined]);
    expect(parsed.stacks[2].groups[0].key).toBe("geofence");
    expect(catalogStackSchema.parse({ ...sampleCatalogStacks.stacks[0], supports_early_stop: undefined }).supports_early_stop).toBe(true); // an older master leaves it out
    expect(parsed.trajectory_generators.find((generator) => generator.id === "straight")?.params_field).toBeNull();
    expect(parsed.monitors.find((monitor) => monitor.id === "live")?.supports_early_stop).toBe(true);
    expect(parsed.unavailable_stacks[0].reasons[0]).toMatch(/Gazebo/);
  });

  it("rejects a parameter type it does not know", () => {
    const broken = structuredClone(sampleCatalogStacks) as typeof sampleCatalogStacks;
    (broken.stacks[0].parameters[0] as { type: string }).type = "matrix";
    expect(catalogStacksSchema.safeParse(broken).success).toBe(false);
  });

  it("accepts parameters without the optional bounds (the server leaves them out)", () => {
    const parsed = catalogStacksSchema.parse(sampleCatalogStacks);
    const timeStep = parsed.trajectory_generators[0].parameters[0];
    expect(timeStep.maximum).toBeUndefined();
    expect(timeStep.minimum).toBe(1);
  });
});

describe("validation result schema", () => {
  it("parses the sample answer", () => {
    const parsed = validationResultSchema.parse(sampleValidationResult);
    expect(parsed.cases_planned).toBe(30);
    expect(parsed.fecs).toHaveLength(2);
    expect(parsed.runs[0].repeatability_tier).toBe("exact");
  });

  it("reads an unlimited failure budget as null", () => {
    const [first, ...rest] = sampleValidationResult.fecs;
    const parsed = validationResultSchema.parse({ ...sampleValidationResult, fecs: [{ ...first, failure_budget: null }, ...rest] });
    expect(parsed.fecs[0].failure_budget).toBeNull();
  });

  it("requires valid to be true", () => {
    expect(validationResultSchema.safeParse({ ...sampleValidationResult, valid: false }).success).toBe(false);
  });

  it("allows an unnamed run and a run without a tier", () => {
    const parsed = validationResultSchema.parse({ ...sampleValidationResult, runs: [{ run_index: 0, name: null, repeatability_tier: null, warnings: ["w"] }] });
    expect(parsed.runs[0].warnings).toEqual(["w"]);
  });
});

describe("catalog calls", () => {
  it("reads the classes with their total and joins pages", async () => {
    const page = (offset: number) => sampleCatalogClasses.slice(offset, offset + 4);
    const { client, spy } = clientWith(async (url) => {
      const offset = Number(new URL(url).searchParams.get("offset"));
      return jsonResponse(page(offset), { headers: { "X-Total-Count": String(sampleCatalogClasses.length) } });
    });
    const result = await listCatalogClasses(client, { folder: "2vessel_0obstacle_scenarios" });
    expect(result.total).toBe(sampleCatalogClasses.length);
    expect(result.items).toHaveLength(sampleCatalogClasses.length);
    expect(spy.mock.calls).toHaveLength(2);
    expect(spy.mock.calls[0][0]).toBe(`${BASE}/cluster/catalog/fecs?folder=2vessel_0obstacle_scenarios&limit=1000&offset=0`);
    expect(spy.mock.calls[1][0]).toContain("offset=4");
  });

  it("stops on an empty page even when the total is larger", async () => {
    const { client, spy } = clientWith(async () => jsonResponse([], { headers: { "X-Total-Count": "50" } }));
    expect((await listCatalogClasses(client)).items).toEqual([]);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("reads the stacks", async () => {
    const { client, spy } = clientWith(async () => jsonResponse(sampleCatalogStacks));
    const stacks = await getCatalogStacks(client);
    expect(stacks.resolver.available).toBe(5);
    expect(spy.mock.calls[0][0]).toBe(`${BASE}/cluster/catalog/stacks`);
  });
});

describe("validate and create", () => {
  it("posts the YAML as the config of a JSON body", async () => {
    const { client, spy } = clientWith(async () => jsonResponse(sampleValidationResult));
    const result = await validateCampaignConfig(client, "name: x\n");
    expect(result.config_hash).toBe("9f2c1d");
    const [url, init] = spy.mock.calls[0];
    expect(url).toBe(`${BASE}/cluster/campaigns/validate`);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(init?.body as string)).toEqual({ config: "name: x\n" });
  });

  it("surfaces the reasons of a refused config", async () => {
    const detail = { message: "the campaign config is not valid", reasons: ["scope.0: no class 'x' in the catalog", "execution.runs.0 (a): stack unavailable"] };
    const { client } = clientWith(async () => jsonResponse({ detail }, { status: 422 }));
    const error = await validateCampaignConfig(client, "x").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(OperatorApiError);
    expect((error as OperatorApiError).status).toBe(422);
    expect((error as OperatorApiError).reasons).toEqual(detail.reasons);
  });

  it("creates paused unless asked to start, and parses the new campaign", async () => {
    const { client, spy } = clientWith(async () => jsonResponse({ ...sampleCampaignDetail(), desired_state: "paused", actual_state: "created" }, { status: 201 }));
    const created = await createCampaign(client, "name: x\n");
    expect(created.actual_state).toBe("created");
    expect(JSON.parse(spy.mock.calls[0][1]?.body as string)).toEqual({ config: "name: x\n", start: false });
    await createCampaign(client, "name: x\n", { start: true, name: "other" });
    expect(JSON.parse(spy.mock.calls[1][1]?.body as string)).toEqual({ config: "name: x\n", start: true, name: "other" });
    expect(spy.mock.calls[1][0]).toBe(`${BASE}/cluster/campaigns`);
  });

  it("sends kind and origin in the request, and leaves them out otherwise", async () => {
    const { client, spy } = clientWith(async () => jsonResponse(sampleCampaignDetail(), { status: 201 }));
    await createCampaign(client, "format: 2\n", { start: true, kind: "workbench", origin: "scene_generation" });
    expect(JSON.parse(spy.mock.calls[0][1]?.body as string)).toEqual({ config: "format: 2\n", start: true, kind: "workbench", origin: "scene_generation" });
    await createCampaign(client, "format: 2\n");
    expect(JSON.parse(spy.mock.calls[1][1]?.body as string)).toEqual({ config: "format: 2\n", start: false });
  });

  it("waits longer than other calls, and on a timeout says to check Campaign History first", async () => {
    vi.useFakeTimers();
    try {
      const { client } = clientWith(
        (_url, init) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
          })
      );
      let settled = false;
      const pending = createCampaign(client, "name: x\n").catch((caught: unknown) => {
        settled = true;
        return caught;
      });
      await vi.advanceTimersByTimeAsync(10_000);
      expect(settled).toBe(false);
      await vi.advanceTimersByTimeAsync(CREATE_TIMEOUT_MS - 10_000);
      const error = (await pending) as OperatorApiError;
      expect(error).toBeInstanceOf(OperatorApiError);
      expect(error.kind).toBe("timeout");
      expect(error.message).toContain("check Campaign History before you create it again");
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("config format 2 types", () => {
  it("parses the input of a campaign that continues from history and from a file", () => {
    const input = campaignInputSchema.parse(sampleFormat2Config.input);
    expect(input.items).toHaveLength(2);
    expect(input.items?.[0].source).toEqual({ campaign_id: "c1", case_id: 5, step: "scene_generation" });
    expect(input.items?.[1].source).toEqual({ file: "head_on.json" });
    expect(input.items?.[1].ref.size_bytes).toBeUndefined();
  });

  it("parses scenarios given as content with their quota and failure budget", () => {
    const input = campaignInputSchema.parse(sampleScenarioConfig.input);
    expect(input.functional_scenarios?.[0]).toMatchObject({ name: "my_head_on", quota: 3, failure_budget: 1 });
    expect(input.items).toBeUndefined();
  });

  it("rejects an item source that names a step outside the chain, and a monitor it does not know", () => {
    expect(inputItemSourceSchema.safeParse({ campaign_id: "c1", case_id: 5, step: "monitor" }).success).toBe(false);
    expect(stepMonitorSchema.safeParse("live").success).toBe(false);
    expect(stepMonitorSchema.parse("post_hoc")).toBe("post_hoc");
  });

  it("types a format 2 config with its Phase 6 sections", () => {
    const config: CampaignConfigFormat2 = {
      format: 2,
      name: "x",
      steps: ["scene_generation", "trajectory_generation"],
      scene_generation: { monitor: "post_hoc" },
      trajectories: { generator: "straight", monitor: "empty" },
    };
    expect(config.steps).toEqual(["scene_generation", "trajectory_generation"]);
  });
});
