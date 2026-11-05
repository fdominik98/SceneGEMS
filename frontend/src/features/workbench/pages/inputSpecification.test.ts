import { describe, expect, it, vi } from "vitest";
import { createOperatorClient } from "../../../domain/cluster/operatorApi";
import { sceneInputSpecification } from "./inputSpecification";

const BASE = "http://127.0.0.1:5174";
const SHA = "e".repeat(64);

function caseView(classId: string, inputArtifact: string | null) {
  return {
    case_id: 3,
    campaign_id: "wb1",
    fec_id: classId,
    case_index: 0,
    seed: 1,
    config_version: 1,
    stage: "verdict",
    state: "complete",
    scene_artifact: "a".repeat(64),
    trajectories_artifact: null,
    trajectories_complete: null,
    input_artifact: inputArtifact,
    input_source: null,
    reason: null,
    created_at: "2026-10-29T09:30:00+00:00",
    updated_at: "2026-10-29T09:30:00+00:00",
    finished_at: null,
    progress: {},
    jobs: [],
    run_records: [],
    verdicts: [],
  };
}

function operator(detail: Record<string, unknown>) {
  const paths: string[] = [];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input));
    paths.push(url.pathname);
    if (url.pathname.startsWith("/cluster/campaigns/")) {
      return new Response(JSON.stringify(detail), { headers: { "Content-Type": "application/json" } });
    }
    if (url.pathname === `/cluster/artifacts/${SHA}`) {
      return new Response("OS(os1).\r\nTS(ts1).\r\n", { headers: { "Content-Type": "text/plain" } });
    }
    if (url.pathname.startsWith("/cluster/catalog/fecs/")) {
      return new Response("OS(os1).\nTS(ts1).\nTS(ts2).\n", { headers: { "Content-Type": "text/plain" } });
    }
    return new Response("{}", { status: 404 });
  });
  return { client: createOperatorClient(BASE, { fetch: fetchImpl as unknown as typeof fetch }), fetch: fetchImpl as unknown as typeof fetch, paths };
}

describe("sceneInputSpecification", () => {
  it("reads a scenario class's uploaded functional scenario", async () => {
    const { client, fetch, paths } = operator(caseView("scenario/head_on", SHA));
    expect(await sceneInputSpecification(client, { campaignId: "wb1", caseId: 3 }, { fetch })).toEqual({ label: "head_on", text: "OS(os1).\nTS(ts1).\n" });
    expect(paths).toEqual(["/cluster/campaigns/wb1/cases/3", `/cluster/artifacts/${SHA}`]);
  });

  it("reads a catalog class's functional scenario from the master's catalog", async () => {
    const { client, fetch, paths } = operator(caseView("3vessel_0obstacle_scenarios/fec5", null));
    expect(await sceneInputSpecification(client, { campaignId: "wb1", caseId: 3 }, { fetch })).toEqual({
      label: "3vessel_0obstacle_scenarios/fec5",
      text: "OS(os1).\nTS(ts1).\nTS(ts2).\n",
    });
    expect(paths[1]).toBe("/cluster/catalog/fecs/3vessel_0obstacle_scenarios/fec5");
  });

  it("has none for an item class or a master that does not name the input", async () => {
    expect(await sceneInputSpecification(operator(caseView("item/0", SHA)).client, { campaignId: "wb1", caseId: 3 })).toBeNull();
    const older = caseView("scenario/head_on", null);
    delete (older as Partial<typeof older>).input_artifact;
    expect(await sceneInputSpecification(operator(older).client, { campaignId: "wb1", caseId: 3 })).toBeNull();
  });
});
