import JSZip from "jszip";
import type { BatchRunResult } from "../../domain/sceneGeneration/batchGenerationStore";
import { formatScenarioJsonForExport } from "../../domain/sceneGeneration/parseEvaluationDataFile";

function sanitizeFileName(label: string): string {
  return label.replace(/[^\w.-]+/g, "_").replace(/_+/g, "_").replace(/^_|_$/g, "") || "scene";
}

export async function downloadValidBatchScenesZip(results: BatchRunResult[]): Promise<void> {
  const valid = results.filter((r) => r.status === "success" && r.evaluationData && r.scene);
  if (valid.length === 0) {
    return;
  }
  const zip = new JSZip();
  const usedNames = new Set<string>();
  for (const result of valid) {
    const base = sanitizeFileName(result.label);
    let fileName = `${base}_generated_scene.json`;
    let suffix = 1;
    while (usedNames.has(fileName)) {
      fileName = `${base}_${suffix}_generated_scene.json`;
      suffix += 1;
    }
    usedNames.add(fileName);
    zip.file(
      fileName,
      formatScenarioJsonForExport(result.evaluationData, result.scene!)
    );
  }
  const blob = await zip.generateAsync({ type: "blob" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `batch_scenes_${new Date().toISOString().slice(0, 10)}.zip`;
  anchor.click();
  URL.revokeObjectURL(url);
}
