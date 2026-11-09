import { useUiStore } from "../../app/uiStore";
import { useResultsStore } from "../../domain/cluster/resultsStore";
import type { CampaignStep } from "../../domain/cluster/schemas";

/**
 * Opens the Results section on an entry's findings: a campaign or a workbench run of Campaign
 * History (any entry id). Other sections call this from a "Show results" button:
 * `showCampaignResults(entry.campaign_id)`; `step` picks the step view, else the section shows
 * the last step the entry executed. The entry belongs to the selected cluster; after a switch to
 * another cluster the section shows that cluster's newest entry instead.
 */
export function showCampaignResults(campaignId: string, step?: CampaignStep): void {
  useResultsStore.getState().openCampaign(campaignId, step);
  useUiStore.getState().setSection("results");
}
