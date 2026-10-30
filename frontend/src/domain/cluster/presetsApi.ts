import { z } from "zod";
import type { OperatorClient } from "./operatorApi";
import { campaignStepSchema } from "./schemas";

/**
 * What the master offers to start from, and the cluster's own settings (`setting_routes.py`,
 * `catalog_routes.py`): the functional scenarios of its class catalog as text, the domain presets
 * of `backend/assets/domain_config/`, the cluster's domain configuration (saved on the master,
 * global for the cluster), and the campaign presets (shipped with the master image, or saved by
 * operators). The frontend keeps no presets of its own.
 */

const CATALOG_PATH = "/cluster/catalog";
const DOMAIN_PATH = "/cluster/domain";
const CAMPAIGN_PRESETS_PATH = "/cluster/campaign-presets";

/** The three texts of a domain configuration, by their campaign config keys. */
export const DOMAIN_KEYS = ["colregs_constants", "vessel_types", "obstacle_types"] as const;
export type DomainKey = (typeof DOMAIN_KEYS)[number];
export type DomainTexts = Record<DomainKey, string>;

export const DOMAIN_LABELS: Record<DomainKey, string> = {
  colregs_constants: "COLREGS constants",
  vessel_types: "Vessel types",
  obstacle_types: "Static obstacle types",
};

const domainTextsShape = {
  colregs_constants: z.string(),
  vessel_types: z.string(),
  obstacle_types: z.string(),
};

export const clusterDomainSchema = z.object({
  ...domainTextsShape,
  /** False while the cluster never saved one: the texts are the master's default presets. */
  saved: z.boolean(),
  updated_at: z.string().nullable(),
  /** False on a master without its database, which serves the defaults read-only. */
  editable: z.boolean(),
});
export type ClusterDomain = z.infer<typeof clusterDomainSchema>;

export const domainPresetSchema = z.object({ name: z.string(), default: z.boolean(), content: z.string() });
export type DomainPreset = z.infer<typeof domainPresetSchema>;

export const domainPresetsSchema = z.object({
  colregs_constants: z.array(domainPresetSchema),
  vessel_types: z.array(domainPresetSchema),
  obstacle_types: z.array(domainPresetSchema),
});
export type DomainPresets = z.infer<typeof domainPresetsSchema>;

export const campaignPresetSchema = z.object({
  preset_id: z.string(),
  name: z.string(),
  description: z.string(),
  /** Shipped with the master image (read-only), or saved by an operator. */
  builtin: z.boolean(),
  steps: z.array(campaignStepSchema),
  /** The campaign config as the preset states it, defaults left out and without an input section. */
  config: z.record(z.string(), z.unknown()),
  created_at: z.string().nullable(),
  updated_at: z.string().nullable(),
});
export type CampaignPreset = z.infer<typeof campaignPresetSchema>;

/** A class's functional scenario (`.problem` text with LF line endings). */
export async function getClassContent(client: Pick<OperatorClient, "request">, classId: string, signal?: AbortSignal): Promise<string> {
  const path = `${CATALOG_PATH}/fecs/${classId.split("/").map(encodeURIComponent).join("/")}`;
  return (await client.request("GET", path, z.string(), { signal })).data;
}

export async function getDomainPresets(client: OperatorClient, signal?: AbortSignal): Promise<DomainPresets> {
  return (await client.request("GET", `${CATALOG_PATH}/domain-presets`, domainPresetsSchema, { signal })).data;
}

export async function getClusterDomain(client: OperatorClient, signal?: AbortSignal): Promise<ClusterDomain> {
  return (await client.request("GET", DOMAIN_PATH, clusterDomainSchema, { signal })).data;
}

/** Replaces the cluster's domain configuration. Rejects with the reasons (422) for a text that is not a YAML mapping. */
export async function saveClusterDomain(client: OperatorClient, texts: DomainTexts): Promise<ClusterDomain> {
  const body: DomainTexts = { colregs_constants: texts.colregs_constants, vessel_types: texts.vessel_types, obstacle_types: texts.obstacle_types };
  return (await client.request("POST", DOMAIN_PATH, clusterDomainSchema, { body })).data;
}

export async function listCampaignPresets(client: OperatorClient, signal?: AbortSignal): Promise<CampaignPreset[]> {
  return (await client.request("GET", CAMPAIGN_PRESETS_PATH, z.array(campaignPresetSchema), { signal })).data;
}

export interface SavePresetRequest {
  name: string;
  description: string;
  /** A campaign config without an input section. */
  config: Record<string, unknown>;
  /** Replace a saved preset of the same name (a shipped one is never replaced). */
  replace?: boolean;
}

/** Saves a preset on the master. A taken name rejects with status 409, a config that is not valid with 422 and its reasons. */
export async function saveCampaignPreset(client: OperatorClient, preset: SavePresetRequest): Promise<CampaignPreset> {
  const body = { name: preset.name, description: preset.description, config: preset.config, replace: preset.replace ?? false };
  return (await client.request("POST", CAMPAIGN_PRESETS_PATH, campaignPresetSchema, { body })).data;
}

export async function deleteCampaignPreset(client: OperatorClient, presetId: string): Promise<void> {
  await client.request("DELETE", `${CAMPAIGN_PRESETS_PATH}/${encodeURIComponent(presetId)}`, z.null());
}

/** Text with LF line endings, as the master stores domain contents (so an edit that only changed line endings is no change). */
export function normalizeNewlines(text: string): string {
  return text.replace(/\r\n?/g, "\n");
}

/** The preset whose content a text is, or null when it was edited or came from elsewhere. */
export function matchingPreset(presets: readonly DomainPreset[], text: string): DomainPreset | null {
  const normalized = normalizeNewlines(text);
  return presets.find((preset) => normalizeNewlines(preset.content) === normalized) ?? null;
}
