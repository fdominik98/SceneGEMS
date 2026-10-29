import type { OperatorClient } from "../../../domain/cluster/operatorApi";
import { OperatorApiError } from "../../../domain/cluster/operatorApi";
import { getClassContent } from "../../../domain/cluster/presetsApi";
import type { WorkbenchTarget } from "./workbenchTarget";

/**
 * The functional scenario a generated scene was made from, so the scene page shows it in its editor
 * when it loads the scene. A case of a scenario class (`scenario/<name>`, a workbench run or an
 * uploaded file) names its input artifact; a case of a catalog class gets the class's content from
 * the master's catalog. Item classes (`item/<n>`) start later in the chain and have no scenario.
 */

export interface InputSpecification {
  /** What the scene page calls the scenario: the class id, or the name of an uploaded or written one. */
  label: string;
  text: string;
}

export type SpecificationClient = Pick<OperatorClient, "getCase" | "artifactUrl" | "request">;

const SCENARIO_CLASS_PREFIX = "scenario/";
const ITEM_CLASS_PREFIX = "item/";

async function artifactText(client: SpecificationClient, sha256: string, signal?: AbortSignal, fetchImpl: typeof fetch = (input, init) => globalThis.fetch(input, init)): Promise<string> {
  const path = `/cluster/artifacts/${sha256}`;
  const response = await fetchImpl(client.artifactUrl(sha256), { headers: { Accept: "text/plain" }, signal });
  if (!response.ok) {
    throw new OperatorApiError("http", `the functional scenario answered HTTP ${response.status}`, path, response.status);
  }
  return (await response.text()).replace(/\r\n?/g, "\n");
}

/** The specification of a scene case, or null when the case has none (an item class, or a master that does not name the input). */
export async function sceneInputSpecification(
  client: SpecificationClient,
  target: Pick<WorkbenchTarget, "campaignId" | "caseId">,
  options: { signal?: AbortSignal; fetch?: typeof fetch } = {}
): Promise<InputSpecification | null> {
  const detail = await client.getCase(target.campaignId, target.caseId, options.signal);
  const classId = detail.class_id;
  if (classId.startsWith(ITEM_CLASS_PREFIX)) {
    return null;
  }
  if (classId.startsWith(SCENARIO_CLASS_PREFIX)) {
    if (!detail.input_artifact) {
      return null;
    }
    return { label: classId.slice(SCENARIO_CLASS_PREFIX.length), text: await artifactText(client, detail.input_artifact, options.signal, options.fetch) };
  }
  return { label: classId, text: await getClassContent(client, classId, options.signal) };
}
