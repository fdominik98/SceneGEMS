import { z } from "zod";
import type { OperatorClient } from "./operatorApi";

/**
 * The architecture documents of the Capabilities page (`backend/.../architecture/architecture_model.py`,
 * served by `GET /cluster/catalog/architecture`). One document per part of the system, in the order of
 * the chain: the design space exploration, the scene generation, the trajectory generation, the vessel
 * stack (which simulates) and the monitoring that judges their outputs. Each has a metamodel
 * (the generic layers, interfaces and adapters an implementation fills in) and the concrete
 * implementations with the adapters between them, laid out over the same lanes, and says its place in
 * the chain: the step it performs, what it takes and gives, and the cluster job types that run it.
 */

const CATALOG_PATH = "/cluster/catalog";

export const FACT_GROUPS = ["capability", "parameter", "property"] as const;
export const factGroupSchema = z.enum(FACT_GROUPS);

/** A value of a node or edge: declared in the spec, or measured (with the evidence on the owner). */
export const factSchema = z.object({
  key: z.string(),
  label: z.string(),
  value: z.union([z.string(), z.number(), z.boolean()]).nullable(),
  group: factGroupSchema,
  measured: z.boolean(),
  unit: z.string().nullable(),
  note: z.string().nullable(),
});

export const laneSchema = z.object({ id: z.string(), label: z.string(), description: z.string() });

export const metamodelNodeSchema = z.object({
  id: z.string(),
  lane: z.string(),
  label: z.string(),
  description: z.string(),
  kind: z.string(),
  members: z.array(z.string()),
  extension: z.string().nullable(),
  code: z.string().nullable(),
});

export const metamodelEdgeSchema = z.object({
  id: z.string(),
  source: z.string(),
  target: z.string(),
  label: z.string(),
  description: z.string(),
  kind: z.string(),
  members: z.array(z.string()),
  extension: z.string().nullable(),
  code: z.string().nullable(),
});

export const STATUSES = ["available", "planned"] as const;
export const statusSchema = z.enum(STATUSES);

export const architectureNodeSchema = z.object({
  id: z.string(),
  lane: z.string(),
  label: z.string(),
  description: z.string(),
  implements: z.string().nullable(),
  status: statusSchema,
  facts: z.array(factSchema),
  ports_provided: z.array(z.string()),
  ports_required: z.array(z.string()),
  tags: z.array(z.string()),
  evidence: z.string(),
});

export const architectureEdgeSchema = z.object({
  id: z.string(),
  source: z.string(),
  target: z.string(),
  label: z.string(),
  description: z.string(),
  implements: z.string().nullable(),
  kind: z.string(),
  status: statusSchema,
  default: z.boolean(),
  facts: z.array(factSchema),
  ports_provided: z.array(z.string()),
  ports_required: z.array(z.string()),
  tags: z.array(z.string()),
  evidence: z.string(),
});

export const unsupportedLinkSchema = z.object({ source: z.string(), target: z.string(), reason: z.string() });

export const combinationSchema = z.object({
  path: z.array(z.string()),
  /** available, planned or unavailable. */
  status: z.string(),
  reasons: z.array(z.string()),
  facts: z.array(factSchema),
});

/** step: the part performs one step of the chain; support: it serves the steps (monitoring judges their outputs). */
export const DOCUMENT_ROLES = ["step", "support"] as const;
export const documentRoleSchema = z.enum(DOCUMENT_ROLES);

export const architectureDocumentSchema = z.object({
  schema_version: z.number().int(),
  id: z.string(),
  title: z.string(),
  summary: z.string(),
  lanes: z.array(laneSchema),
  metamodel_nodes: z.array(metamodelNodeSchema),
  metamodel_edges: z.array(metamodelEdgeSchema),
  nodes: z.array(architectureNodeSchema),
  edges: z.array(architectureEdgeSchema),
  unsupported: z.array(unsupportedLinkSchema),
  combinations: z.array(combinationSchema),
  notes: z.array(z.string()),
  /** The part's place in the chain; a control node from before the overview states none, so every field has a default. */
  role: documentRoleSchema.default("step"),
  /** The chain step the part performs, as the console names it; empty for a supporting part and from an older control node. */
  step: z.string().default(""),
  takes: z.string().default(""),
  gives: z.string().default(""),
  /** The cluster job types that run the part. */
  job_types: z.array(z.string()).default([]),
});

export const architectureSchema = z.object({
  schema_version: z.number().int(),
  documents: z.array(architectureDocumentSchema),
});

export type Fact = z.infer<typeof factSchema>;
export type Lane = z.infer<typeof laneSchema>;
export type MetamodelNode = z.infer<typeof metamodelNodeSchema>;
export type ArchitectureNode = z.infer<typeof architectureNodeSchema>;
export type Combination = z.infer<typeof combinationSchema>;
export type ArchitectureDocument = z.infer<typeof architectureDocumentSchema>;
export type Architecture = z.infer<typeof architectureSchema>;

export async function getArchitecture(client: OperatorClient, signal?: AbortSignal): Promise<Architecture> {
  return (await client.request("GET", `${CATALOG_PATH}/architecture`, architectureSchema, { signal })).data;
}
