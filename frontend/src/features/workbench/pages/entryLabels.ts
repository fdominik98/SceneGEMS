/** The first block of an entry id: enough to tell entries apart on a page; the whole id goes in a tooltip. */
export function shortEntryId(campaignId: string): string {
  return campaignId.split("-")[0] ?? campaignId;
}

/** How a page names a case of an entry: its 1-based index in the class (the master's case id is no number people count by). */
export function caseLabel(caseIndex: number, campaignId: string): string {
  return `case ${caseIndex + 1} of entry ${shortEntryId(campaignId)}`;
}
