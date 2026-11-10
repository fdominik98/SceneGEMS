import { useEffect, useState } from "react";
import { useOperatorClient } from "../useCampaignData";
import { ItemInput } from "./ItemInput";
import { ScenarioFiles } from "./ScenarioFiles";
import { ScopeStep } from "./ScopeStep";
import { inputKindOf } from "./stepPlan";
import type { CatalogState, StepProps } from "./stepTypes";

const CLOCK_MS = 60_000;

/** The time, refreshed every minute, for the expiry notes of uploaded files. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), CLOCK_MS);
    return () => clearInterval(timer);
  }, []);
  return now;
}

/**
 * Input: what the first step starts from. Scene generation takes classes of the catalog and/or
 * functional scenario files; trajectory generation takes scenes and simulation takes trajectories,
 * from Campaign History or uploaded files.
 */
export function InputStep(props: StepProps & { catalog: CatalogState }) {
  const client = useOperatorClient();
  const now = useNow();
  const kind = inputKindOf(props.draft.steps);
  if (kind === "explored") {
    return (
      <div className="wiz-step">
        <p className="wiz-notice" role="note">
          This campaign starts with the design space exploration: its FECs come from the exploration, so there are no catalog FECs, functional scenarios or
          items to choose here. Set the specification and the scope on the Design space exploration page.
        </p>
      </div>
    );
  }
  if (kind !== "catalog_or_scenarios") {
    return <ItemInput draft={props.draft} update={props.update} reasons={props.reasons} client={client} now={now} />;
  }
  return (
    <div className="wiz-step">
      <ScenarioFiles draft={props.draft} update={props.update} reasons={props.reasons} client={client} now={now} />
      <ScopeStep {...props} />
    </div>
  );
}
