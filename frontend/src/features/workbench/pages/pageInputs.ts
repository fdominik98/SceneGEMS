import type { ConfigArtifactRef } from "../../../domain/cluster/campaignApi";
import { uploadArtifact, type UploadKind } from "../../../domain/cluster/historyApi";
import type { OperatorClient } from "../../../domain/cluster/operatorApi";
import type { EntryItem } from "./entryConfig";
import type { PageInput } from "./pageStore";

/**
 * The input of a run as its entry's config names it. An input that is on the control node already (a
 * history output, or an output of the previous page that came from an entry) is used as it is;
 * otherwise its content is uploaded (`POST /cluster/artifacts`) and the entry takes the upload.
 */

/** What the config's reference says of an uploaded file of each kind. */
const UPLOADED: Record<UploadKind, Pick<ConfigArtifactRef, "kind" | "pointer">> = {
  functional_scenario: { kind: "functional_scenario", pointer: null },
  scene: { kind: "scene", pointer: null },
  // A trajectory file is a full scenario: its trajectories sit under `/trajectories`.
  trajectories: { kind: "trajectories", pointer: "/trajectories" },
};

export class InputMissingError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InputMissingError";
  }
}

/** Uploads a text as an artifact of a kind and answers the reference the config writes. */
export async function uploadedRef(client: Pick<OperatorClient, "request">, content: string, kind: UploadKind, contentType = "application/json", signal?: AbortSignal): Promise<ConfigArtifactRef> {
  const uploaded = await uploadArtifact(client as OperatorClient, content, kind, contentType, signal);
  return { sha256: uploaded.sha256, size_bytes: uploaded.size_bytes, kind: UPLOADED[kind].kind, media_type: uploaded.media_type, pointer: UPLOADED[kind].pointer };
}

/**
 * The item a run's entry takes: the input's own reference when it has one, else its content
 * uploaded. `content` is what the page shows of the input (null when it has none, after a reload
 * of a file input).
 */
export async function resolveInputItem(
  client: Pick<OperatorClient, "request">,
  input: PageInput,
  content: string | null,
  kind: UploadKind,
  signal?: AbortSignal
): Promise<EntryItem> {
  if (input.ref !== null) {
    return { name: input.label.slice(0, 256), ref: input.ref, source: input.source };
  }
  if (content === null) {
    throw new InputMissingError("The input is not on the control node and its file is not loaded any more: choose it again.");
  }
  return { name: input.label.slice(0, 256), ref: await uploadedRef(client, content, kind, "application/json", signal), source: input.source };
}
