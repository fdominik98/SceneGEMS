import type { ReviewStatus } from "./campaignMapModel";
import type { Reason } from "./reasons";
import { WIZARD_STEP_LABELS, type WizardStepId } from "./wizardState";

/**
 * What is left to do in the wizard, as one short list: the pages that still miss something, in the
 * order of the pages, each with the first thing it misses. Most pages have defaults that work, so
 * a new campaign usually needs a name and an input and nothing else; the list says so instead of
 * leaving the operator to walk nine pages to find out.
 */

export interface GuideItem {
  step: WizardStepId;
  /** The page's name. */
  label: string;
  /** The first thing the page misses. */
  message: string;
  /** How many more things the page misses. */
  more: number;
}

export interface WizardGuide {
  /** The pages that miss something, in page order; empty when nothing is missing. */
  items: GuideItem[];
  /** How many things are missing in all. */
  count: number;
  /** What to do when nothing is missing, by what the control node said of the config. */
  next: "review" | "checking" | "create" | "fix_refusal" | "check_failed";
}

/** What the cluster cannot run of the campaign, as the Resources page lists it. */
export function missingCapabilityMessage(missing: number): string {
  return missing === 1 ? "No usable machine offers one of the things the campaign needs." : `No usable machine offers ${missing} of the things the campaign needs.`;
}

/**
 * The guide of a draft: `reasons` are every open problem (the browser's and the control node's),
 * `missingCapabilities` how many things the campaign needs that no usable machine offers.
 */
export function wizardGuide(pages: readonly WizardStepId[], reasons: readonly Reason[], missingCapabilities: number, review: ReviewStatus): WizardGuide {
  const items: GuideItem[] = [];
  let count = 0;
  for (const step of pages) {
    const messages = reasons.filter((reason) => reason.step === step).map((reason) => reason.message);
    if (step === "resources" && missingCapabilities > 0) {
      messages.push(missingCapabilityMessage(missingCapabilities));
    }
    if (messages.length > 0) {
      items.push({ step, label: WIZARD_STEP_LABELS[step], message: messages[0], more: messages.length - 1 });
      count += messages.length;
    }
  }
  const next = review === "accepted" ? "create" : review === "checking" ? "checking" : review === "refused" ? "fix_refusal" : review === "failed" ? "check_failed" : "review";
  return { items, count, next };
}
