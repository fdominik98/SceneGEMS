import JSZip from "jszip";
import { saveBlob } from "../../../components/saveBlob";
import type { ExploredFec } from "../../../domain/designSpace/explorationResult";

/** A FEC's file name in the export: `explored/00003` is `explored_00003.problem`. */
export function fecFileName(fecId: string): string {
  return `${fecId.replace(/[^\w.-]+/g, "_").replace(/_+/g, "_").replace(/^_|_$/g, "") || "fec"}.problem`;
}

/** The FECs' texts as a ZIP of `.problem` files. */
export async function explorationZip(entries: readonly { fec: ExploredFec; text: string }[]): Promise<Blob> {
  const zip = new JSZip();
  const used = new Set<string>();
  for (const { fec, text } of entries) {
    let name = fecFileName(fec.fecId);
    for (let n = 2; used.has(name); n += 1) {
      name = fecFileName(`${fec.fecId}_${n}`);
    }
    used.add(name);
    zip.file(name, text);
  }
  return zip.generateAsync({ type: "blob" });
}

export async function downloadExplorationZip(entries: readonly { fec: ExploredFec; text: string }[], campaignId: string): Promise<void> {
  if (entries.length === 0) {
    return;
  }
  saveBlob(await explorationZip(entries), `explored_fecs_${campaignId.split("-")[0] ?? campaignId}.zip`);
}
