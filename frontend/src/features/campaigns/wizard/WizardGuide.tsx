import { plural } from "../campaignFormat";
import type { WizardGuide as Guide } from "./guideModel";
import type { WizardStepId } from "./wizardState";

/** How many pages the guide lists; the rest are summed up in a last line. */
const ITEMS_SHOWN = 4;

const READY_TEXT: Record<Guide["next"], string> = {
  review: "Review the config and create the campaign.",
  checking: "The control node is checking the config.",
  create: "The control node accepted the config: create the campaign on the Review page.",
  fix_refusal: "The control node refused the config: its reasons are on the Review page.",
  check_failed: "The control node could not check the config: try again on the Review page.",
};

export interface WizardGuideProps {
  guide: Guide;
  /** The page shown; the wizard leaves the guide out on the Review page, which says the same itself. */
  current: WizardStepId;
  onGoTo: (step: WizardStepId) => void;
}

/**
 * What is left to do before the campaign can be created: the pages that miss something, each a
 * button to its page, or that nothing is missing and the way to the Review page. It names every
 * open item at once, also on pages not opened yet, and says that the other pages need nothing.
 */
export function WizardGuide({ guide, current, onGoTo }: WizardGuideProps) {
  if (guide.items.length === 0) {
    return (
      <section className="wiz-guide wiz-guide--ready panel" aria-label="What is left to do">
        <p className="wiz-guide-lead" role="status">
          <strong>Nothing is missing.</strong> {READY_TEXT[guide.next]}
        </p>
        <button type="button" className="primary-btn accent" onClick={() => onGoTo("review")}>
          Go to the review
        </button>
      </section>
    );
  }
  const shown = guide.items.slice(0, ITEMS_SHOWN);
  const hidden = guide.items.length - shown.length;
  return (
    <section className="wiz-guide panel" aria-label="What is left to do">
      <p className="wiz-guide-lead" role="status">
        <strong>{plural(guide.count, "thing")} left to do</strong> before the campaign can be created. Every other page has defaults that work.
      </p>
      <ol className="wiz-guide-list">
        {shown.map((item) => (
          <li key={item.step}>
            <button type="button" className="wiz-guide-page" aria-current={item.step === current ? "step" : undefined} onClick={() => onGoTo(item.step)} title={`Open the ${item.label} page`}>
              {item.label}
            </button>
            <span className="wiz-guide-message">
              {item.message}
              {item.more > 0 && <span className="meta"> and {item.more} more</span>}
            </span>
          </li>
        ))}
        {hidden > 0 && <li className="meta">and {plural(hidden, "more page")}</li>}
      </ol>
    </section>
  );
}
