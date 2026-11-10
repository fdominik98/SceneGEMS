import type { InputSpecification } from "../pages/inputSpecification";

/**
 * Pure rules of the scene page's selection of catalog FECs. What a run does follows from the
 * selection alone: none selected generates one scene of the editor's text, one selected one scene of
 * that FEC, several a batch with a case per FEC (`sceneSelectionMode` in `batchGenerationStore.ts`).
 */

/** The run button's text: one scene for none or one FEC, else one per FEC. */
export function runButtonLabel(selectedCount: number): string {
  return selectedCount < 2 ? "Generate scene" : `Generate ${selectedCount} scenes`;
}

/**
 * Where the functional scenario of an opened entry's scene goes. A scene of a catalog FEC selects
 * that FEC (the pane then shows it, and a run generates it again), whether the case names the class
 * itself or a scenario uploaded under the class's id (a single run of a selected FEC). Any other
 * scenario (written, from a file, explored, or edited from a catalog FEC, whose label says so) goes
 * into the editor, which clears the selection. Without the catalog, everything goes into the editor.
 */
export function placeOfInput(spec: Pick<InputSpecification, "label">, catalogIds: ReadonlySet<string> | null): { kind: "select"; classId: string } | { kind: "editor" } {
  return catalogIds !== null && catalogIds.has(spec.label) ? { kind: "select", classId: spec.label } : { kind: "editor" };
}

/** The label "Edit a copy" gives the editor's text, so a run of it is not taken for the catalog FEC. */
export function copyLabel(classId: string): string {
  return `${classId} (copy)`;
}
