import type { CampaignStep } from "../../../domain/cluster/schemas";
import { Field, FieldIssues } from "./fields";
import { reasonsOfEntry, splitByField } from "./reasons";
import { CAMPAIGN_STEP_LABELS, CAMPAIGN_STEP_OUTPUTS, CHAIN, firstStep, itemKindsFor, lastStep, stepRange } from "./stepPlan";
import type { StepProps } from "./stepTypes";

const STEP_HINTS: Record<CampaignStep, string> = {
  scene_generation: "Generates scenes from FECs of the catalog or from functional scenario files.",
  trajectory_generation: "Plans the trajectories of scenes, generated here or taken from Campaign History or files.",
  simulation: "Simulates trajectories, generated here or taken from Campaign History or files, once per run you define.",
};

/** Steps: the campaign's name and the consecutive part of the chain it runs. Each step's own settings are on the step's page. */
export function StepsStep({ draft, update, reasons }: StepProps) {
  const first = firstStep(draft.steps);
  const last = lastStep(draft.steps);
  const own = splitByField(reasonsOfEntry(reasons, null), ["name", "description", "steps"]);

  const choose = (nextFirst: CampaignStep, nextLast: CampaignStep) =>
    update((next) => {
      next.steps = stepRange(nextFirst, nextLast);
      // Items of the wrong kind for the new first step cannot be used: leave them out
      const kinds = itemKindsFor(next.steps);
      next.input.items = next.input.items.filter((item) => kinds.includes(item.ref.kind));
    });

  return (
    <div className="wiz-step">
      <div className="wiz-columns">
        <div className="wiz-column">
          <Field label="Name" htmlFor="wiz-name" hint="Shown in Campaign History." issues={own.byField.get("name")}>
            <input id="wiz-name" type="text" value={draft.name} maxLength={256} placeholder="head-on scenes, planned" onChange={(event) => update((next) => void (next.name = event.target.value))} />
          </Field>
          <Field label="Description" htmlFor="wiz-description" hint="Optional." issues={own.byField.get("description")}>
            <textarea id="wiz-description" rows={2} value={draft.description} onChange={(event) => update((next) => void (next.description = event.target.value))} />
          </Field>
        </div>
        <div className="wiz-column">
          <p className="wiz-notice wiz-explain" role="note">
            A campaign runs one, two or all three steps of the chain scene generation, trajectory generation, simulation, always next to each other. It starts with the first step you choose and stops after the last.
          </p>
        </div>
      </div>

      <div className="wiz-row">
        <fieldset className="wiz-choice">
          <legend>Start with</legend>
          {CHAIN.map((step) => (
            <label key={step} className={`wiz-option${first === step ? " wiz-option--on" : ""}`}>
              <input type="radio" name="wiz-first-step" checked={first === step} onChange={() => choose(step, CHAIN.indexOf(last) < CHAIN.indexOf(step) ? step : last)} />
              <span>
                <strong>{CAMPAIGN_STEP_LABELS[step]}</strong>
                <span className="wiz-hint">{STEP_HINTS[step]}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <fieldset className="wiz-choice">
          <legend>Stop after</legend>
          {CHAIN.map((step) => {
            const before = CHAIN.indexOf(step) < CHAIN.indexOf(first);
            return (
              <label key={step} className={`wiz-option${last === step ? " wiz-option--on" : ""}${before ? " wiz-option--off" : ""}`}>
                <input type="radio" name="wiz-last-step" disabled={before} checked={last === step} onChange={() => choose(first, step)} />
                <span>
                  <strong>{CAMPAIGN_STEP_LABELS[step]}</strong>
                  <span className="wiz-hint">{before ? "Comes before the first step." : `Produces ${CAMPAIGN_STEP_OUTPUTS[step]}.`}</span>
                </span>
              </label>
            );
          })}
        </fieldset>
      </div>
      <FieldIssues reasons={own.byField.get("steps")} />

      <p className="wiz-plan" role="status" aria-label="The chosen steps">
        This campaign runs <strong>{draft.steps.map((step) => CAMPAIGN_STEP_LABELS[step].toLowerCase()).join(", then ")}</strong>.
        {first !== "scene_generation" && " Its input comes from earlier results or files (next page)."}
      </p>
      <FieldIssues reasons={own.rest} showField />
    </div>
  );
}
