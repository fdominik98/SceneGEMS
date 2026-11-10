import type { OperatorClient } from "../../../domain/cluster/operatorApi";
import { designSpaceSectionOf, type DesignSpaceSection } from "../../../domain/designSpace/designSpaceConfig";

/**
 * What an entry explored: the `design_space_exploration` section of its current config, so the
 * page shows the specification and the scope of an entry it loads from Campaign History; null when
 * the entry has none.
 */
export async function explorationInputOfEntry(client: Pick<OperatorClient, "getCampaignConfig">, campaignId: string, signal?: AbortSignal): Promise<DesignSpaceSection | null> {
  const data = await client.getCampaignConfig(campaignId, signal);
  const current = data.versions.find((version) => version.version === data.current_version) ?? data.versions[data.versions.length - 1];
  return current === undefined ? null : designSpaceSectionOf(current.config);
}
