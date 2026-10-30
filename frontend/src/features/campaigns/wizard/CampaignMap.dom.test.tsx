import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CampaignMap } from "./CampaignMap";
import { buildCampaignMap, type MapContext } from "./campaignMapModel";
import { emptyDraft, emptyRun, WIZARD_STEPS, type WizardDraft, type WizardStepId } from "./wizardState";

const NO_PROBLEMS = Object.fromEntries(WIZARD_STEPS.map((step) => [step, 0])) as Record<WizardStepId, number>;

function mapOf(change: (draft: WizardDraft) => void = () => undefined, overrides: Partial<MapContext> = {}) {
  const draft = emptyDraft();
  draft.name = "sweep";
  draft.runs = [
    { ...emptyRun("kinematic.replay"), id: "r1", name: "replay" },
    { ...emptyRun("kinematic.usv_navigation"), id: "r2" },
  ];
  change(draft);
  return buildCampaignMap(draft, { stacks: undefined, classes: undefined, plan: null, problems: NO_PROBLEMS, runProblems: [], review: "unchecked", ...overrides });
}

function setup(current: WizardStepId, map = mapOf()) {
  const onOpen = vi.fn();
  render(<CampaignMap map={map} current={current} onOpen={onOpen} />);
  return { onOpen, user: userEvent.setup() };
}

describe("the campaign map", () => {
  it("shows a box per part of the chain, each run on its own, with what its page holds", () => {
    setup("steps");
    for (const name of [/^Input/, /^Scene generation/, /^Trajectory generation/, /^Run 1: replay/, /^Run 2/, /^Review/]) {
      expect(screen.getByRole("button", { name })).toBeVisible();
    }
    expect(screen.getByText("Simulation, 2 runs")).toBeVisible();
    expect(screen.getByRole("button", { name: /^Input/ })).toHaveTextContent("Nothing chosen yet");
    const settings = screen.getByRole("list", { name: "Settings of the whole campaign" });
    expect(within(settings).getAllByRole("button").map((button) => button.querySelector(".cmap-card-title")?.textContent)).toEqual(["Steps", "Domain", "Resources", "Policy"]);
  });

  it("marks the boxes of the page shown below it", () => {
    setup("runs");
    expect(screen.getByRole("button", { name: /^Run 1/ })).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("button", { name: /^Run 2/ })).toHaveAttribute("aria-current", "step");
    expect(screen.getByRole("button", { name: /^Input/ })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("button", { name: /^Steps/ })).not.toHaveAttribute("aria-current");
  });

  it("does not mark a step the campaign skips as the Steps page", () => {
    setup("steps", mapOf((draft) => void (draft.steps = ["simulation"])));
    expect(screen.getByRole("button", { name: /^Scene generation\s*Not run/ })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("button", { name: /^Steps/ })).toHaveAttribute("aria-current", "step");
  });

  it("opens the page of the box clicked, and a run at its card", async () => {
    const { onOpen, user } = setup("steps");
    await user.click(screen.getByRole("button", { name: /^Trajectory generation/ }));
    expect(onOpen).toHaveBeenLastCalledWith({ page: "trajectories", runId: undefined });
    await user.click(screen.getByRole("button", { name: /^Run 2/ }));
    expect(onOpen).toHaveBeenLastCalledWith({ page: "runs", runId: "r2" });
    await user.click(screen.getByRole("button", { name: /^Policy/ }));
    expect(onOpen).toHaveBeenLastCalledWith({ page: "policy" });
  });

  it("names the problems of a box for assistive technology", () => {
    setup("steps", mapOf(undefined, { problems: { ...NO_PROBLEMS, input: 2, resources: 1 }, runProblems: [0, 1] }));
    expect(screen.getByRole("button", { name: /^Input, 2 problems/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /^Run 2, 1 problem/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /^Resources, 1 problem/ })).toBeVisible();
  });
});
