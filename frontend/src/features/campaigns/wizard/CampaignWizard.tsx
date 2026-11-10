import { useMutation } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePersistedState } from "../../../app/usePersistedState";
import { createCampaign } from "../../../domain/cluster/campaignApi";
import { useSelectedCluster } from "../../../domain/cluster/clusterStore";
import { useNodesFeed, useNodesStore } from "../../../domain/cluster/nodesStore";
import { describeOperatorError, OperatorApiError, type OperatorClient } from "../../../domain/cluster/operatorApi";
import type { NodeView } from "../../../domain/cluster/schemas";
import { planKey, planResources, requiredCapabilities, slotsByJobType, startBlocker, type ResourcePlan } from "../resourcePlan";
import { useCatalogClasses, useCatalogStacks, useOperatorClient } from "../useCampaignData";
import { buildCampaignMap, casesPerExploredFec, reviewStatusOf } from "./campaignMapModel";
import { CampaignMap, type MapTarget } from "./CampaignMap";
import { buildCampaignConfig, configToYaml, requiredLabelsOf, type BuilderCatalog } from "./configBuilder";
import { checkDraft } from "./draftChecks";
import { DomainStep } from "./DomainStep";
import { PolicyStep } from "./PolicyStep";
import { reasonsByStep, type Reason } from "./reasons";
import { ResourcesStep } from "./ResourcesStep";
import { ReviewStep } from "./ReviewStep";
import { RunsStep } from "./RunsStep";
import { InputStep } from "./InputStep";
import { PresetBar } from "./PresetBar";
import { ExplorationStep } from "./ExplorationStep";
import { ScenesStep } from "./ScenesStep";
import { StepsStep } from "./StepsStep";
import { inputKindOf, visibleWizardSteps } from "./stepPlan";
import type { CatalogState, ClusterResources, StepProps } from "./stepTypes";
import { TrajectoriesStep } from "./TrajectoriesStep";
import { useValidation, validationFromError } from "./useValidation";
import { useWizardStore, WIZARD_STEP_LABELS, WIZARD_STEPS, type WizardStepId } from "./wizardState";
import "./wizard.css";

const AUTO_CHECK_DELAY_MS = 700;
/** How often the check of uploaded files' expiry looks at the clock. */
const CLOCK_MS = 60_000;
const EMPTY_BUILDER: BuilderCatalog = { stacks: [], generators: [] };
const NO_NODES: readonly NodeView[] = [];

/** The plan as the previous render had it while it says the same (`planKey`): the map and the problem counts built from it are kept then. */
function useSamePlan(plan: ResourcePlan | null): ResourcePlan | null {
  const key = planKey(plan);
  const [kept, setKept] = useState({ key, plan });
  if (kept.key !== key) {
    setKept({ key, plan });
    return plan;
  }
  return kept.plan;
}

/** Kept per browser: the pages shown as the campaign map or as a list, and whether the pages explain every field. */
export const MAP_SHOWN_KEY = "campaign-wizard-map";
export const EXPLANATIONS_KEY = "campaign-wizard-explanations";

export interface CampaignWizardProps {
  onClose: () => void;
  onCreated: (campaignId: string) => void;
}

function describeCreateFailure(error: unknown): string {
  if (error instanceof OperatorApiError && error.status === 422) {
    return "The master refused the config. The reasons are listed above.";
  }
  if (error instanceof OperatorApiError && error.kind === "timeout") {
    // No answer is no refusal: the campaign may exist, and the message says to look in Campaign History first
    return `The master did not confirm the campaign: ${describeOperatorError(error)}.`;
  }
  return `The campaign was not created: ${describeOperatorError(error)}`;
}

/** Brings a run's card on the Simulation page into view. */
function scrollToRun(runId: string) {
  document.getElementById(`wiz-run-${runId}`)?.scrollIntoView?.({ behavior: "smooth", block: "start" });
}

/**
 * The create wizard: the steps of the chain to run, their input, the domain, a page per step the campaign runs
 * (scene generation, trajectory generation, the simulation runs), resources and policy, then a review that validates
 * the config on the master. The campaign map above the pages draws the draft as a graph and opens the page of the box
 * clicked; the list of pages replaces it on request.
 */
export function CampaignWizard({ onClose, onCreated }: CampaignWizardProps) {
  const client = useOperatorClient();
  const storedStep = useWizardStore((state) => state.step);
  const draft = useWizardStore((state) => state.draft);
  const visited = useWizardStore((state) => state.visited);
  const setStep = useWizardStore((state) => state.setStep);
  const update = useWizardStore((state) => state.update);
  const replaceDraft = useWizardStore((state) => state.replaceDraft);
  const reset = useWizardStore((state) => state.reset);
  const [mapShown, setMapShown] = usePersistedState(MAP_SHOWN_KEY, true);
  const [explanations, setExplanations] = usePersistedState(EXPLANATIONS_KEY, false);

  // The pages of the chosen steps; a stored page that the steps no longer include falls back to the first
  const pages = useMemo(() => visibleWizardSteps(draft.steps), [draft.steps]);
  const step: WizardStepId = pages.includes(storedStep) ? storedStep : "steps";

  const classes = useCatalogClasses();
  const stacks = useCatalogStacks();
  const catalogState: CatalogState = {
    classes: classes.data?.items,
    classesError: classes.error,
    classesLoading: classes.isLoading,
    stacks: stacks.data,
    stacksError: stacks.error,
    stacksLoading: stacks.isLoading,
    retry: () => {
      void classes.refetch();
      void stacks.refetch();
    },
  };

  // The cluster's nodes: what the campaign needs is checked against them, and full usage sizes its queues to their slots
  const operatorUrl = useSelectedCluster()?.operatorUrl ?? null;
  useNodesFeed(operatorUrl);
  const nodesUrl = useNodesStore((state) => state.operatorUrl);
  const nodesReady = useNodesStore((state) => state.loaded);
  const storeNodes = useNodesStore((state) => state.nodes);
  const nodesError = useNodesStore((state) => state.error);
  const nodesLoaded = operatorUrl !== null && nodesUrl === operatorUrl && nodesReady;
  const nodes = nodesLoaded ? storeNodes : NO_NODES;
  const labels = useMemo(() => requiredLabelsOf(draft), [draft]);
  // Kept by content: heartbeats replace the node list every few seconds, the slots rarely change
  const slotsKey = JSON.stringify(slotsByJobType(nodes, labels));
  const slots = useMemo(() => JSON.parse(slotsKey) as Record<string, number>, [slotsKey]);

  const builderCatalog = useMemo<BuilderCatalog>(
    () => (stacks.data ? { stacks: stacks.data.stacks, generators: stacks.data.trajectory_generators, slots: nodesLoaded ? slots : undefined } : EMPTY_BUILDER),
    [stacks.data, nodesLoaded, slots]
  );
  const config = useMemo(() => buildCampaignConfig(draft, builderCatalog), [draft, builderCatalog]);
  const yaml = useMemo(() => configToYaml(config), [config]);
  // Uploaded files expire 24 hours after the upload: the clock makes the check see it
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), CLOCK_MS);
    return () => clearInterval(timer);
  }, []);
  const localReasons = useMemo(() => checkDraft(draft, stacks.data ? builderCatalog : null, now), [draft, builderCatalog, stacks.data, now]);

  const freshPlan = useMemo(
    () => (nodesLoaded ? planResources(requiredCapabilities(config), nodes, { nodes: draft.resources.fullUsage ? null : draft.resources.nodes, labels }) : null),
    [nodesLoaded, config, nodes, draft.resources.fullUsage, draft.resources.nodes, labels]
  );
  // Kept by content: heartbeats replace the node views every few seconds, what the plan says rarely changes
  const plan = useSamePlan(freshPlan);
  const cluster: ClusterResources = {
    selected: operatorUrl !== null,
    loaded: nodesLoaded,
    error: nodesUrl === operatorUrl ? nodesError : null,
    nodes,
    plan,
    slots,
    startBlocker: startBlocker(plan),
  };

  const { state: validation, check, adopt, reset: resetValidation } = useValidation(client);
  const [createMessage, setCreateMessage] = useState<string | null>(null);

  // A run without a stack takes the first one the master can run
  useEffect(() => {
    const first = stacks.data?.stacks.find((entry) => entry.available);
    if (first && draft.runs.some((run) => run.stackId === "")) {
      update((next) => {
        for (const run of next.runs) {
          if (run.stackId === "") {
            run.stackId = first.id;
          }
        }
      });
    }
  }, [stacks.data, draft.runs, update]);

  // On the review step the master checks the config as soon as it is complete and has stopped changing
  useEffect(() => {
    if (step !== "review" || localReasons.length > 0 || !client || validation.yaml === yaml) {
      return undefined;
    }
    const timer = setTimeout(() => void check(yaml), AUTO_CHECK_DELAY_MS);
    return () => clearTimeout(timer);
  }, [step, localReasons.length, client, validation.yaml, yaml, check]);

  const creation = useMutation({
    mutationFn: ({ start, target }: { start: boolean; target: OperatorClient }) => createCampaign(target, yaml, { start, kind: "campaign", origin: "wizard" }),
    onSuccess: (campaign) => {
      reset();
      resetValidation();
      setCreateMessage(null);
      onCreated(campaign.campaign_id);
    },
    onError: (error) => {
      adopt(validationFromError(yaml, error));
      setCreateMessage(describeCreateFailure(error));
    },
  });

  const serverReasons: Reason[] = validation.reasons;
  const allReasons = useMemo(() => [...localReasons, ...serverReasons], [localReasons, serverReasons]);
  const byStep = useMemo(() => reasonsByStep(allReasons), [allReasons]);
  // What the browser finds wrong shows on a step once the operator has been through it; the master's reasons always show
  const shownReasons = useCallback((id: WizardStepId) => byStep[id].filter((reason) => reason.source === "server" || visited.includes(id)), [byStep, visited]);
  const stepReasons = shownReasons(step);
  const index = pages.indexOf(step);

  // The problems each page shows, and the runs page's per run (its reasons without a run go with the first)
  const { problems, runProblems } = useMemo(() => {
    const counts = Object.fromEntries(WIZARD_STEPS.map((id) => [id, shownReasons(id).length])) as Record<WizardStepId, number>;
    counts.resources += visited.includes("resources") ? (plan?.missing.length ?? 0) : 0;
    counts.review = 0;
    const runs = draft.runs.map((_run, at) => shownReasons("runs").filter((reason) => reason.entry === at || (at === 0 && reason.entry === null)).length);
    return { problems: counts, runProblems: runs };
  }, [shownReasons, visited, plan, draft.runs]);

  const review = reviewStatusOf(localReasons.length, validation, yaml);
  const map = useMemo(
    () => buildCampaignMap(draft, { stacks: stacks.data, classes: classes.data?.items, plan, problems, runProblems, review }),
    [draft, stacks.data, classes.data, plan, problems, runProblems, review]
  );

  // A run card of the map opens the Simulation page at that run
  const pendingRun = useRef<string | null>(null);
  useEffect(() => {
    if (step === "runs" && pendingRun.current !== null) {
      scrollToRun(pendingRun.current);
      pendingRun.current = null;
    }
  });
  const openTarget = useCallback(
    (target: MapTarget) => {
      if (target.page === step && target.runId) {
        scrollToRun(target.runId);
        return;
      }
      pendingRun.current = target.runId ?? null;
      setStep(target.page);
    },
    [step, setStep]
  );

  const stepProps: StepProps = { draft, update, reasons: stepReasons };
  let body;
  switch (step) {
    case "steps":
      body = <StepsStep {...stepProps} />;
      break;
    case "input":
      body = <InputStep {...stepProps} catalog={catalogState} />;
      break;
    case "domain":
      body = <DomainStep {...stepProps} />;
      break;
    case "exploration":
      body = <ExplorationStep {...stepProps} />;
      break;
    case "scenes":
      body = <ScenesStep {...stepProps} />;
      break;
    case "trajectories":
      body = <TrajectoriesStep {...stepProps} catalog={catalogState} />;
      break;
    case "runs":
      body = <RunsStep {...stepProps} catalog={catalogState} />;
      break;
    case "resources":
      body = <ResourcesStep {...stepProps} cluster={cluster} />;
      break;
    case "policy":
      body = <PolicyStep {...stepProps} />;
      break;
    default:
      body = (
        <ReviewStep
          yaml={yaml}
          validation={validation}
          current={validation.yaml === yaml}
          baseSeed={draft.policy.seed}
          localReasons={localReasons}
          serverReasons={serverReasons}
          onGoTo={setStep}
          onCheck={() => void check(yaml)}
          onCreate={(start) => {
            if (client) {
              setCreateMessage(null);
              creation.mutate({ start, target: client });
            }
          }}
          creating={creation.isPending}
          createMessage={createMessage}
          startBlocker={cluster.startBlocker}
          explored={inputKindOf(draft.steps) === "explored" ? (draft.steps.length > 1 ? casesPerExploredFec(draft) : "the campaign ends with the list of FECs") : null}
        />
      );
  }

  return (
    <div className={`wiz${explanations ? "" : " wiz--terse"}`}>
      <header className="wiz-head panel">
        <div className="wiz-head-row">
          <div className="wiz-head-title">
            <h3>New campaign</h3>
            <p className="meta wiz-explain">Your entries are kept in this browser until the campaign is created or you discard them.</p>
          </div>
          <div className="wiz-head-actions">
            <button type="button" onClick={onClose}>
              Close, keep the draft
            </button>
            <button
              type="button"
              className="wiz-remove"
              onClick={() => {
                if (window.confirm("Discard everything entered in the wizard?")) {
                  reset();
                  resetValidation();
                  setCreateMessage(null);
                }
              }}
            >
              Discard the draft
            </button>
          </div>
        </div>
        <PresetBar
          draft={draft}
          catalog={stacks.data ? builderCatalog : null}
          classes={classes.data?.items}
          onLoad={(next) => {
            replaceDraft(next);
            resetValidation();
            setCreateMessage(null);
          }}
        />
      </header>
      <section className="wiz-map panel" aria-label={mapShown ? "Campaign map" : "Wizard pages"}>
        <div className="wiz-map-bar">
          <h4 className="wiz-map-title">{mapShown ? "Campaign map" : "Pages"}</h4>
          <p className="meta wiz-explain">{mapShown ? "What the campaign does, as set so far. A box opens its page." : "The pages of the wizard in order."}</p>
          <div className="wiz-map-tools">
            <label className="wiz-check" title="Show the explanation of every option and field. Without, a field explains itself while you edit it.">
              <input type="checkbox" checked={explanations} onChange={(event) => setExplanations(event.target.checked)} />
              Show explanations
            </label>
            <div className="wiz-switch" role="group" aria-label="Show the pages as">
              <button type="button" aria-pressed={mapShown} onClick={() => setMapShown(true)}>
                Map
              </button>
              <button type="button" aria-pressed={!mapShown} onClick={() => setMapShown(false)}>
                List
              </button>
            </div>
          </div>
        </div>
        {mapShown ? (
          <CampaignMap map={map} current={step} onOpen={openTarget} />
        ) : (
          <nav className="wiz-steps" aria-label="Wizard steps">
            <ol>
              {pages.map((id, at) => {
                const count = problems[id];
                return (
                  <li key={id}>
                    <button type="button" className={`wiz-step-tab${id === step ? " wiz-step-tab--on" : ""}${count > 0 ? " wiz-step-tab--bad" : ""}`} aria-current={id === step ? "step" : undefined} onClick={() => setStep(id)}>
                      <span className="wiz-step-number">{at + 1}</span>
                      <span className="wiz-step-label">{WIZARD_STEP_LABELS[id]}</span>
                      {count > 0 && (
                        <span className="wiz-step-count" title={`${count} ${count === 1 ? "problem" : "problems"}`}>
                          {count}
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ol>
          </nav>
        )}
      </section>
      <div className="wiz-body panel">
        <h3 className="wiz-page-title">{WIZARD_STEP_LABELS[step]}</h3>
        {body}
      </div>
      <footer className="wiz-foot">
        <button type="button" disabled={index === 0} onClick={() => setStep(pages[index - 1])}>
          Back
        </button>
        <span className="wiz-foot-page" aria-live="polite">
          Page {index + 1} of {pages.length}
        </span>
        {step !== "review" && (
          <>
            <button type="button" className="primary-btn accent" onClick={() => setStep(pages[index + 1])}>
              Next: {WIZARD_STEP_LABELS[pages[index + 1]]}
            </button>
            <button type="button" onClick={() => setStep("review")}>
              Review the config
            </button>
          </>
        )}
      </footer>
    </div>
  );
}
