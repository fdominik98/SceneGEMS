import { useState } from "react";
import { Disclosure } from "../../components/Disclosure";
import type { CampaignControl } from "../../domain/cluster/operatorApi";
import { OperatorApiError } from "../../domain/cluster/operatorApi";
import type { CampaignSummary } from "../../domain/cluster/schemas";
import { CONTROL_SPECS, controlAvailability, isFinalState, type ControlSpec } from "./campaignModel";
import { useCampaignControl } from "./useCampaignFeed";

/** The message of a refused control, with what the control node said. */
function refusal(error: unknown): { title: string; detail: string } {
  if (error instanceof OperatorApiError) {
    if (error.status === 409) {
      return { title: "The control node refused this change", detail: error.message };
    }
    if (error.status === 404) {
      return { title: "The campaign is not on this control node", detail: error.message };
    }
    if (error.unreachable) {
      return { title: "The control node did not answer", detail: error.message };
    }
    return { title: `The control node answered ${error.status ?? "with an error"}`, detail: error.message };
  }
  return { title: "The change failed", detail: error instanceof Error ? error.message : String(error) };
}

function ControlButton({ spec, enabled, reason, busy, onPress }: { spec: ControlSpec; enabled: boolean; reason: string | null; busy: boolean; onPress: () => void }) {
  return (
    <button
      type="button"
      className={`camp-control-btn camp-control-btn--${spec.tone}`}
      disabled={!enabled || busy}
      onClick={onPress}
      title={enabled ? spec.description : (reason ?? undefined)}
      aria-describedby={`camp-control-${spec.control}`}
    >
      {spec.label}
      <span id={`camp-control-${spec.control}`} className="sr-only">
        {enabled ? spec.description : reason}
      </span>
    </button>
  );
}

export interface ControlsBarProps {
  campaign: CampaignSummary;
  onChanged: (summary: CampaignSummary) => void;
  /** Why the campaign cannot start on the cluster's machines, or null. */
  startBlocker?: string | null;
}

/** Start, pause, drain, resume and stop, each with what it does; a stop is confirmed, a refusal is shown in full. */
export function ControlsBar({ campaign, onChanged, startBlocker = null }: ControlsBarProps) {
  const [confirming, setConfirming] = useState<CampaignControl | null>(null);
  const mutation = useCampaignControl(campaign.campaign_id, onChanged);
  const availability = controlAvailability(campaign, startBlocker);
  const held = startBlocker !== null && !isFinalState(campaign.actual_state) && campaign.desired_state !== "running" && campaign.desired_state !== "stopped";

  const run = (control: CampaignControl) => {
    setConfirming(null);
    mutation.mutate(control);
  };

  const press = (spec: ControlSpec) => {
    mutation.reset();
    if (spec.confirm) {
      setConfirming(spec.control);
    } else {
      run(spec.control);
    }
  };

  const pending = confirming ? CONTROL_SPECS.find((spec) => spec.control === confirming) : undefined;
  const failure = mutation.isError ? refusal(mutation.error) : null;

  return (
    <section className="panel camp-controls" aria-label="Campaign controls">
      <div className="camp-controls-row">
        {CONTROL_SPECS.map((spec) => (
          <ControlButton
            key={spec.control}
            spec={spec}
            enabled={availability[spec.control].enabled}
            reason={availability[spec.control].reason}
            busy={mutation.isPending}
            onPress={() => press(spec)}
          />
        ))}
      </div>
      {held && (
        <p className="camp-start-blocked" role="status">
          <strong>Start and Resume are off.</strong> {startBlocker}
        </p>
      )}
      <Disclosure
        id="campaign:control-help"
        variant="link"
        headingLevel={null}
        title="What do these buttons do?"
        openTitle="Hide the explanations"
      >
        <dl className="camp-control-help">
          {CONTROL_SPECS.map((spec) => (
            <div key={spec.control}>
              <dt>{spec.label}</dt>
              <dd>{availability[spec.control].enabled ? spec.description : availability[spec.control].reason}</dd>
            </div>
          ))}
        </dl>
      </Disclosure>
      {pending && (
        <div className="camp-confirm" role="alertdialog" aria-label={`Confirm ${pending.label.toLowerCase()}`}>
          <p>
            <strong>{pending.label} {campaign.name}?</strong> {pending.description}
          </p>
          <div className="camp-confirm-actions">
            <button type="button" className="camp-control-btn camp-control-btn--danger" onClick={() => run(pending.control)}>
              {pending.label} the campaign
            </button>
            <button type="button" onClick={() => setConfirming(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {mutation.isPending && <p className="meta" role="status">Sending to the control node...</p>}
      {failure && (
        <div className="camp-refusal" role="alert">
          <strong>{failure.title}.</strong> <span>{failure.detail}</span>
          <button type="button" onClick={() => mutation.reset()}>
            Dismiss
          </button>
        </div>
      )}
    </section>
  );
}
