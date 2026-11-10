import { describe, expect, it, vi } from "vitest";
import { sampleStackDocument, sampleStackDocumentWithoutChain } from "../../test/fixtures/architectureDocuments";
import { architectureSchema, getArchitecture } from "./architectureApi";
import { createOperatorClient, OperatorApiError } from "./operatorApi";

const BASE = "http://127.0.0.1:5174";

function clientWith(body: unknown) {
  const spy = vi.fn(async () => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } }));
  return { client: createOperatorClient(BASE, { fetch: spy as unknown as typeof fetch }), spy };
}

describe("architecture schema", () => {
  it("parses a document as the backend writes it", () => {
    const parsed = architectureSchema.parse({ schema_version: 1, documents: [sampleStackDocument()] });
    expect(parsed.documents[0].combinations).toHaveLength(6);
    expect(parsed.documents[0].nodes[4].evidence).toContain("12-core");
  });

  it("reads the place of a part in the chain", () => {
    const parsed = architectureSchema.parse({ schema_version: 2, documents: [sampleStackDocument()] }).documents[0];
    expect([parsed.role, parsed.step, parsed.takes, parsed.gives, parsed.job_types]).toEqual(["step", "Stacking", "parts", "a stack", ["simulation"]]);
  });

  it("gives a document of a control node from before the overview an empty place in the chain", () => {
    const parsed = architectureSchema.parse({ schema_version: 1, documents: [sampleStackDocumentWithoutChain()] }).documents[0];
    expect([parsed.role, parsed.step, parsed.takes, parsed.gives, parsed.job_types]).toEqual(["step", "", "", "", []]);
  });

  it("refuses a role it does not know", () => {
    expect(architectureSchema.safeParse({ schema_version: 2, documents: [{ ...sampleStackDocument(), role: "extra" }] }).success).toBe(false);
  });

  it("accepts a fact that is a number, a string, a boolean or null", () => {
    const document = sampleStackDocument();
    document.nodes[0].facts = [
      { key: "a", label: "A", value: 1.5, group: "capability", measured: true, unit: "x", note: null },
      { key: "b", label: "B", value: "unbounded", group: "parameter", measured: false, unit: null, note: "n" },
      { key: "c", label: "C", value: true, group: "property", measured: false, unit: null, note: null },
      { key: "d", label: "D", value: null, group: "capability", measured: false, unit: null, note: null },
    ];
    expect(architectureSchema.parse({ schema_version: 1, documents: [document] }).documents[0].nodes[0].facts).toHaveLength(4);
  });

  it("refuses an unknown status or fact group", () => {
    const status = sampleStackDocument();
    (status.nodes[0] as { status: string }).status = "retired";
    expect(architectureSchema.safeParse({ schema_version: 1, documents: [status] }).success).toBe(false);
    const group = sampleStackDocument();
    group.nodes[2].facts = [{ key: "k", label: "K", value: 1, group: "other" as "capability", measured: false, unit: null, note: null }];
    expect(architectureSchema.safeParse({ schema_version: 1, documents: [group] }).success).toBe(false);
  });
});

describe("getArchitecture", () => {
  it("reads the documents from the catalog route", async () => {
    const { client, spy } = clientWith({ schema_version: 1, documents: [sampleStackDocument()] });
    const architecture = await getArchitecture(client);
    expect(architecture.documents.map((document) => document.id)).toEqual(["stack"]);
    expect((spy.mock.calls[0] as unknown as [string])[0]).toBe(`${BASE}/cluster/catalog/architecture`);
  });

  it("rejects an answer of the wrong shape", async () => {
    const { client } = clientWith({ schema_version: 1, documents: [{ id: "x" }] });
    const error = await getArchitecture(client).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(OperatorApiError);
    expect((error as OperatorApiError).kind).toBe("schema");
  });
});
