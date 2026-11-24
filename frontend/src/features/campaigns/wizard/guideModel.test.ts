import { describe, expect, it } from "vitest";
import { checkDraft } from "./draftChecks";
import { missingCapabilityMessage, wizardGuide } from "./guideModel";
import type { Reason } from "./reasons";
import { visibleWizardSteps } from "./stepPlan";
import { emptyDraft, type WizardStepId } from "./wizardState";

function reason(step: WizardStepId, message: string, source: Reason["source"] = "local"): Reason {
  return { raw: message, step, entry: null, field: null, path: null, message, source };
}

const PAGES = visibleWizardSteps(["scene_generation", "trajectory_generation", "simulation"]);

describe("what is left to do in the wizard", () => {
  it("lists the pages that miss something in page order, each with its first item", () => {
    const guide = wizardGuide(PAGES, [reason("runs", "Repeats is at least 1."), reason("steps", "Give the campaign a name."), reason("runs", "Choose a stack.")], 0, "incomplete");
    expect(guide.items).toEqual([
      { step: "steps", label: "Steps", message: "Give the campaign a name.", more: 0 },
      { step: "runs", label: "Simulation", message: "Repeats is at least 1.", more: 1 },
    ]);
    expect(guide.count).toBe(3);
  });

  it("counts what no usable machine offers on the Resources page", () => {
    const guide = wizardGuide(PAGES, [reason("resources", "Choose at least one machine, or use every machine.")], 2, "incomplete");
    expect(guide.items).toEqual([{ step: "resources", label: "Resources", message: "Choose at least one machine, or use every machine.", more: 1 }]);
    expect(wizardGuide(PAGES, [], 1, "unchecked").items[0].message).toBe(missingCapabilityMessage(1));
    expect(missingCapabilityMessage(3)).toMatch(/offers 3 of the things/);
  });

  it("leaves out a problem of a page the chosen steps do not show", () => {
    const pages = visibleWizardSteps(["scene_generation"]);
    expect(wizardGuide(pages, [reason("runs", "Choose a stack.")], 0, "unchecked").items).toEqual([]);
  });

  it("says what comes next once nothing is missing, by what the control node said", () => {
    expect(wizardGuide(PAGES, [], 0, "unchecked")).toEqual({ items: [], count: 0, next: "review" });
    expect(wizardGuide(PAGES, [], 0, "checking").next).toBe("checking");
    expect(wizardGuide(PAGES, [], 0, "accepted").next).toBe("create");
    expect(wizardGuide(PAGES, [], 0, "failed").next).toBe("check_failed");
    // A refusal names its fields: they are listed like the browser's own findings
    const refused = wizardGuide(PAGES, [reason("policy", "seed must be an integer", "server")], 0, "refused");
    expect(refused.items[0]).toMatchObject({ step: "policy", message: "seed must be an integer" });
  });

  it("asks a new draft for a name and an input and nothing else", () => {
    const draft = emptyDraft();
    const guide = wizardGuide(visibleWizardSteps(draft.steps), checkDraft(draft, null), 0, "incomplete");
    expect(guide.items.map((item) => item.step)).toEqual(["steps", "input"]);
    expect(guide.items[0].message).toBe("Give the campaign a name.");
  });
});
