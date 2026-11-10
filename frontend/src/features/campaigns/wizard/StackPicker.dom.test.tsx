import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { catalogStacksSchema } from "../../../domain/cluster/campaignApi";
import { sampleCatalogStacks } from "../../../test/fixtures/campaignCatalog";
import { RunsStep } from "./RunsStep";
import type { CatalogState } from "./stepTypes";
import { emptyRun, type WizardDraft } from "./wizardState";
import { StepHarness } from "./wizardTestHarness";
import { draftOf } from "./wizardTestData";

// The stack catalog on the Simulation page: finding a stack, and what picking one does to the run.

const parsed = catalogStacksSchema.parse(sampleCatalogStacks);

function catalogOf(stacks = parsed): CatalogState {
  return { classes: [], classesError: null, classesLoading: false, stacks, stacksError: null, stacksLoading: false, retry: () => undefined };
}

function setup(edit: (run: ReturnType<typeof emptyRun>) => void = () => undefined, catalog = catalogOf()) {
  const initial = draftOf((draft) => {
    const run = emptyRun("kinematic.replay", "post_hoc");
    edit(run);
    draft.runs = [run];
  });
  const drafts: WizardDraft[] = [];
  render(<StepHarness Page={RunsStep} initial={initial} extra={{ catalog }} onDraft={(draft) => drafts.push(draft)} />);
  return { drafts, user: userEvent.setup() };
}

describe("the stack picker", () => {
  it("shows the run's stack and opens the catalog, the stack marked", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Stack: Replay on the kinematic layer" }));
    const dialog = screen.getByRole("dialog", { name: "Simulation stacks" });
    const chosen = within(dialog).getByRole("button", { name: /^Replay on the kinematic layer/ });
    expect(chosen).toHaveAttribute("aria-current", "true");
    expect(chosen).toHaveTextContent("In this run");
    expect(within(dialog).getByRole("region", { name: "Gazebo" })).toBeVisible();
  });

  it("finds a stack by its filters and picks it, which resets what belonged to the old stack", async () => {
    const { drafts, user } = setup((run) => {
      run.stackParameters = { dt: 2 };
      run.earlyStop = true;
    });
    await user.click(screen.getByRole("button", { name: /^Stack:/ }));
    const dialog = screen.getByRole("dialog", { name: "Simulation stacks" });
    await user.click(within(dialog).getByRole("checkbox", { name: /Custom controller/ }));
    await user.click(within(dialog).getByRole("checkbox", { name: /USV Navigation/ }));
    expect(within(dialog).getByRole("status")).toHaveTextContent("1 of 6 stacks");
    await user.click(within(dialog).getByRole("button", { name: /^USV Navigation on the custom controller with Gazebo/ }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stack: USV Navigation on the custom controller with Gazebo" })).toBeVisible();
    const run = drafts[drafts.length - 1].runs[0];
    expect(run.stackId).toBe("gazebo_custom.usv_navigation");
    expect(run.stackParameters).toEqual({});
    expect(run.earlyStop).toBe(false);
  });

  it("keeps the run as it is when the same stack is picked again", async () => {
    const { drafts, user } = setup((run) => void (run.stackParameters = { dt: 2 }));
    await user.click(screen.getByRole("button", { name: /^Stack:/ }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: /^Replay on the kinematic layer/ }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(drafts).toEqual([]);
  });

  it("says why a stack the control node cannot run cannot be picked", async () => {
    const stacks = { ...parsed, stacks: parsed.stacks.map((stack) => (stack.id === "gazebo_custom.replay" ? { ...stack, available: false, reasons: ["no Gazebo adapter here"] } : stack)) };
    const { user } = setup(undefined, catalogOf(stacks));
    await user.click(screen.getByRole("button", { name: /^Stack:/ }));
    const dialog = screen.getByRole("dialog");
    const card = within(dialog).getByRole("button", { name: /^Replay on the custom controller/ });
    expect(card).toBeDisabled();
    expect(card).toHaveTextContent("no Gazebo adapter here");
    await user.click(within(dialog).getByRole("checkbox", { name: /Cannot run on this control node/ }));
    expect(within(dialog).getByRole("status")).toHaveTextContent("1 of 6 stacks");
  });

  it("names a stack the control node does not offer", () => {
    setup((run) => void (run.stackId = "somewhere.replay"));
    expect(screen.getByRole("button", { name: "Stack: somewhere.replay (not available)" })).toBeVisible();
  });

  it("names a stack the control node offers but cannot run", () => {
    const stacks = { ...parsed, stacks: parsed.stacks.map((stack) => (stack.id === "kinematic.replay" ? { ...stack, available: false } : stack)) };
    setup(undefined, catalogOf(stacks));
    expect(screen.getByRole("button", { name: "Stack: Replay on the kinematic layer (not available)" })).toBeVisible();
  });

  it("asks for a stack when the run has none", () => {
    setup((run) => void (run.stackId = ""));
    expect(screen.getByRole("button", { name: "Stack: Choose a stack" })).toBeVisible();
  });

  it("does not leave the catalog of one run open for the others", async () => {
    const { user } = setup();
    await user.click(screen.getByRole("button", { name: "Add a run" }));
    const pickers = screen.getAllByRole("button", { name: /^Stack:/ });
    expect(pickers).toHaveLength(2);
    await user.click(pickers[1]);
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });
});
