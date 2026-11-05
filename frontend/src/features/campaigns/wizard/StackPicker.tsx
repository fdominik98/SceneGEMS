import { useState } from "react";
import type { CatalogStack } from "../../../domain/cluster/campaignApi";
import { CatalogDialog } from "./CatalogDialog";
import { controlValue, repeatabilityValue, simulationValue, softwareValue, STACK_CATALOG, supportValues } from "./stackCatalog";

function StackCard({ stack, chosen, onPick }: { stack: CatalogStack; chosen: boolean; onPick: () => void }) {
  const tags = [simulationValue(stack), controlValue(stack), softwareValue(stack), ...supportValues(stack)].map((entry) => entry.label);
  return (
    <button type="button" className={`wiz-catalog-item${chosen ? " wiz-catalog-item--chosen" : ""}`} disabled={!stack.available} aria-current={chosen ? "true" : undefined} onClick={onPick}>
      <span className="wiz-catalog-item-head">
        <strong>{stack.label}</strong>
        {chosen && <span className="wiz-catalog-badge wiz-catalog-badge--chosen">In this run</span>}
      </span>
      <span className="wiz-catalog-item-text">{stack.description}</span>
      <span className="wiz-catalog-tags">
        {tags.map((tag) => (
          <span key={tag} className="wiz-catalog-tag">
            {tag}
          </span>
        ))}
        <span className="wiz-catalog-tag">Repeatability: {repeatabilityValue(stack).label.toLowerCase()}</span>
      </span>
      {!stack.available && <span className="wiz-catalog-warning">{stack.reasons.join("; ") || "The master gave no reason."}</span>}
    </button>
  );
}

/** A run's stack: shows the one picked and opens the stack catalog to pick another. */
export function StackPicker({ id, stacks, stackId, onPick }: { id: string; stacks: readonly CatalogStack[]; stackId: string; onPick: (stackId: string) => void }) {
  const [open, setOpen] = useState(false);
  const chosen = stacks.find((stack) => stack.id === stackId);
  const name = chosen?.available ? chosen.label : stackId !== "" ? `${chosen?.label ?? stackId} (not available)` : "Choose a stack";

  const pick = (stack: CatalogStack) => {
    setOpen(false);
    // The same stack again changes nothing: its parameters stay
    if (stack.id !== stackId) {
      onPick(stack.id);
    }
  };

  return (
    <>
      <button id={id} type="button" className="wiz-catalog-open" aria-haspopup="dialog" aria-label={`Stack: ${name}`} title="Browse the stacks" onClick={() => setOpen(true)}>
        <span className="wiz-catalog-open-name">{name}</span>
        <span className="wiz-catalog-open-action">Browse</span>
      </button>
      {open && (
        <CatalogDialog
          title="Simulation stacks"
          noun="stack"
          storageKey="stacks"
          items={stacks}
          model={STACK_CATALOG}
          onClose={() => setOpen(false)}
          renderItem={(stack) => <StackCard stack={stack} chosen={stack.id === stackId} onPick={() => pick(stack)} />}
        />
      )}
    </>
  );
}
