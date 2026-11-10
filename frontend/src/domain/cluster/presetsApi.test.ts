import { describe, expect, it, vi } from "vitest";
import { createOperatorClient } from "./operatorApi";
import {
  deleteCampaignPreset,
  getClassContent,
  getClusterDomain,
  getDesignSpaceDefault,
  getDomainPresets,
  listCampaignPresets,
  matchingPreset,
  saveCampaignPreset,
  saveClusterDomain,
} from "./presetsApi";

const BASE = "http://127.0.0.1:5174";

function client(answer: (url: URL, init: RequestInit) => Response) {
  const calls: { url: URL; init: RequestInit }[] = [];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    calls.push({ url, init: init ?? {} });
    return answer(url, init ?? {});
  });
  return { client: createOperatorClient(BASE, { fetch: fetchImpl as unknown as typeof fetch }), calls };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const DOMAIN = { colregs_constants: "A: 1\n", vessel_types: "Ferry: {}\n", obstacle_types: "Buoy: {}\n" };
const PRESET = {
  preset_id: "01_smoke_test",
  name: "Smoke test",
  description: "One case per class.",
  builtin: true,
  steps: ["scene_generation", "trajectory_generation", "simulation"],
  config: { format: 2, name: "Smoke test" },
  created_at: null,
  updated_at: null,
};

describe("the master's presets", () => {
  it("reads a class's functional scenario as text, its id kept as a path", async () => {
    const { client: operator, calls } = client(() => new Response("OS(os1).\n", { headers: { "Content-Type": "text/plain" } }));
    expect(await getClassContent(operator, "2vessel_0obstacle_scenarios/fec1")).toBe("OS(os1).\n");
    expect(calls[0].url.pathname).toBe("/cluster/catalog/fecs/2vessel_0obstacle_scenarios/fec1");
  });

  it("reads the domain presets per text", async () => {
    const presets = { colregs_constants: [{ name: "general_maritime_constants", default: true, content: "A: 1\n" }], vessel_types: [], obstacle_types: [] };
    const { client: operator, calls } = client(() => json(presets));
    expect(await getDomainPresets(operator)).toEqual(presets);
    expect(calls[0].url.pathname).toBe("/cluster/catalog/domain-presets");
  });

  it("reads and saves the cluster's domain configuration", async () => {
    const view = { ...DOMAIN, saved: true, updated_at: "2026-10-29T09:30:00+00:00", editable: true };
    const { client: operator, calls } = client(() => json(view));
    expect(await getClusterDomain(operator)).toEqual(view);
    expect(await saveClusterDomain(operator, { ...DOMAIN, extra: "dropped" } as typeof DOMAIN)).toEqual(view);
    expect(calls[1].init.method).toBe("POST");
    expect(JSON.parse(String(calls[1].init.body))).toEqual(DOMAIN);
  });

  it("lists, saves and deletes campaign presets", async () => {
    const { client: operator, calls } = client((_url, init) => (init.method === "DELETE" ? new Response(null, { status: 204 }) : json(init.method === "POST" ? { ...PRESET, builtin: false, preset_id: "p-1" } : [PRESET])));
    expect(await listCampaignPresets(operator)).toEqual([PRESET]);
    const saved = await saveCampaignPreset(operator, { name: "Mine", description: "", config: { format: 2, name: "mine" } });
    expect(saved.preset_id).toBe("p-1");
    expect(JSON.parse(String(calls[1].init.body))).toEqual({ name: "Mine", description: "", config: { format: 2, name: "mine" }, replace: false });
    await deleteCampaignPreset(operator, "p-1");
    expect(calls[2].url.pathname).toBe("/cluster/campaign-presets/p-1");
  });

  it("rejects a taken preset name with the master's status", async () => {
    const { client: operator } = client(() => json({ detail: "a saved preset is named 'Mine'" }, 409));
    await expect(saveCampaignPreset(operator, { name: "Mine", description: "", config: {} })).rejects.toMatchObject({ status: 409 });
  });
});

describe("matchingPreset", () => {
  const presets = [
    { name: "general", default: true, content: "A: 1\nB: 2\n" },
    { name: "strict", default: false, content: "A: 5\n" },
  ];

  it("finds the preset a text is, line endings aside", () => {
    expect(matchingPreset(presets, "A: 1\r\nB: 2\r\n")?.name).toBe("general");
    expect(matchingPreset(presets, "A: 5\n")?.name).toBe("strict");
    expect(matchingPreset(presets, "A: 6\n")).toBeNull();
  });

  it("reads the default design space, and none from a master that has no route for it", async () => {
    const shipped = { specification: "class OS.\n", scope: "TS = 2, StaticObstacle = 0" };
    const { client: operator, calls } = client(() => json(shipped));
    expect(await getDesignSpaceDefault(operator)).toEqual(shipped);
    expect(calls[0].url.pathname).toBe("/cluster/catalog/design-space");
    const { client: old } = client(() => json({ detail: "Not Found" }, 404));
    expect(await getDesignSpaceDefault(old)).toBeNull();
    const { client: broken } = client(() => json({ detail: "boom" }, 500));
    await expect(getDesignSpaceDefault(broken)).rejects.toThrow();
  });
});
