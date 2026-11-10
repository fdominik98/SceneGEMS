import type { ConfigArtifactRef } from "../../../domain/cluster/campaignApi";
import type { OutputRow } from "../../../domain/cluster/historyApi";
import type { ArtifactRef, CampaignStep } from "../../../domain/cluster/schemas";
import { newEntryId, UPLOAD_LIFETIME_MS, type InputItemDraft, type ScenarioFileDraft } from "./wizardState";

/**
 * The input of a campaign as the wizard collects it: items made from outputs of Campaign History or
 * from uploaded files, and scenario files. Pure, so the pickers and the tests share the rules.
 */

/** An artifact as the config's `ref` writes it (a null pointer is left out). */
export function configRefOf(ref: ArtifactRef): ConfigArtifactRef {
  const result: ConfigArtifactRef = { sha256: ref.sha256, size_bytes: ref.size_bytes, kind: ref.kind, media_type: ref.media_type };
  if (ref.pointer !== null && ref.pointer !== undefined) {
    result.pointer = ref.pointer;
  }
  return result;
}

/** A file name without its folder and last extension, for a name in the campaign. */
export function baseName(fileName: string): string {
  const name = fileName.split(/[\\/]/).pop() ?? fileName;
  const dot = name.lastIndexOf(".");
  return (dot > 0 ? name.slice(0, dot) : name).trim();
}

/** `name`, or `name 2`, `name 3` ... when `taken` has it already. */
export function uniqueName(name: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  if (!used.has(name)) {
    return name;
  }
  for (let n = 2; ; n += 1) {
    if (!used.has(`${name} ${n}`)) {
      return `${name} ${n}`;
    }
  }
}

/** A scenario file after its upload: quota 1 and failure budget 0 until the operator changes them. The class id is `scenario/<name>`, so the name has no slash. */
export function scenarioFromUpload(fileName: string, ref: ArtifactRef, taken: Iterable<string>, now: number): ScenarioFileDraft {
  const name = uniqueName(baseName(fileName).replace(/\//g, "_") || "scenario", taken);
  return { id: newEntryId("scenario"), fileName, name, ref: configRefOf(ref), quota: 1, failureBudget: 0, uploadedAt: now };
}

/** An item after the upload of a scene or trajectory file; its source is the file name. */
export function itemFromUpload(fileName: string, ref: ArtifactRef, taken: Iterable<string>, now: number): InputItemDraft {
  const name = uniqueName(baseName(fileName) || "file", taken);
  return { id: newEntryId("item"), name, ref: configRefOf(ref), source: { file: fileName }, uploadedAt: now };
}

/** Whether an output can be a campaign's input of these kinds: it exists, was not found invalid, and has the right kind. */
export function outputUsable(output: OutputRow, kinds: readonly string[]): boolean {
  return output.artifact !== null && output.valid !== false && kinds.includes(output.artifact.kind);
}

/** Why an output cannot be used, or null when it can. */
export function outputProblem(output: OutputRow, kinds: readonly string[]): string | null {
  if (output.artifact === null) {
    return output.reason ?? "no output";
  }
  if (output.valid === false) {
    return "not valid";
  }
  if (!kinds.includes(output.artifact.kind)) {
    return `a ${output.artifact.kind.replace(/_/g, " ")}, not usable here`;
  }
  return null;
}

/** An item for an output of a step of an entry; null when the output cannot be used. */
export function itemFromOutput(entryName: string, campaignId: string, step: CampaignStep, output: OutputRow, kinds: readonly string[], taken: Iterable<string>): InputItemDraft | null {
  if (!outputUsable(output, kinds) || output.artifact === null) {
    return null;
  }
  const run = output.run_index !== null ? ` run ${output.run_index + 1}${output.repeat_index ? ` repeat ${output.repeat_index + 1}` : ""}` : "";
  const name = uniqueName(`${entryName} case ${output.case_index}${run}`, taken);
  return {
    id: newEntryId("item"),
    name,
    ref: configRefOf(output.artifact),
    source: { campaign_id: campaignId, case_id: output.case_id, step },
    uploadedAt: null,
  };
}

/** Whether an item already stands for this output (same entry, case and step; a simulation output also the same run record by hash). */
export function sameOutput(item: InputItemDraft, campaignId: string, step: CampaignStep, output: OutputRow): boolean {
  const source = item.source;
  if (!("campaign_id" in source) || source.campaign_id !== campaignId || source.case_id !== output.case_id || source.step !== step) {
    return false;
  }
  return output.artifact === null || item.ref.sha256 === output.artifact.sha256;
}

/** Whole hours an upload still has on the control node (at most 24, as a clock that lags the upload may be earlier than it), or 0 once it has expired; `null` for an item that is not an upload. */
export function uploadHoursLeft(uploadedAt: number | null, now: number): number | null {
  if (uploadedAt === null) {
    return null;
  }
  return Math.min(UPLOAD_LIFETIME_MS / 3_600_000, Math.max(0, Math.ceil((uploadedAt + UPLOAD_LIFETIME_MS - now) / 3_600_000)));
}

/** The note under an uploaded file: when it expires, and that a created campaign keeps it. */
export function uploadNote(uploadedAt: number | null, now: number): string {
  const hours = uploadHoursLeft(uploadedAt, now);
  if (hours === null) {
    return "Kept by the control node with the entry it came from.";
  }
  if (hours === 0) {
    return "Expired: the control node has removed the upload. Upload the file again.";
  }
  return `Uploaded; the control node deletes it in about ${hours === 1 ? "1 hour" : `${hours} hours`} unless a campaign uses it.`;
}
