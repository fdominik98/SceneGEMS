import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ExplorationStep } from "./ExplorationStep";
import { InputStep } from "./InputStep";
import { parseReasons } from "./reasons";
import { StepHarness } from "./wizardTestHarness";
import { draftOf } from "./wizardTestData";
import type { WizardDraft } from "./wizardState";

const mocks = vi.hoisted(() => ({ designSpace: { data: undefined as unknown, isSuccess: false, isError: false, error: null as unknown } }));

vi.mock("../useCampaignData", () => ({ useDesignSpaceDefault: () => mocks.designSpace, useOperatorClient: () => null }));
vi.mock("@uiw/react-codemirror", () => ({
  default: ({ value, onChange }: { value: string; onChange?: (value: string) => void }) => (
    <textarea aria-label="Specification text" value={value} onChange={(event) => onChange?.(event.target.value)} />
  ),
}));

function exploring(change: (draft: WizardDraft) => void = () => undefined): WizardDraft {
  return draftOf((draft) => {
    draft.steps = ["design_space_exploration", "scene_generation"];
    change(draft);
  });
}

function setup(initial: WizardDraft, reasons = parseReasons([])) {
  const seen: WizardDraft[] = [];
  render(<StepHarness Page={ExplorationStep} extra={{}} initial={initial} reasons={reasons} onDraft={(draft) => seen.push(draft)} />);
  return { latest: () => seen[seen.length - 1], user: userEvent.setup() };
}

describe("the Design space exploration page of the wizard", () => {
  beforeEach(() => {
    mocks.designSpace = { data: { specification: "abstract class Vessel.\n", scope: "TS = 2, StaticObstacle = 0" }, isSuccess: true, isError: false, error: null };
  });

  it("starts from the control node's default and sets the scope, the limits and what each FEC needs", async () => {
    const { latest, user } = setup(exploring());
    await waitFor(() => expect(latest()?.exploration).toMatchObject({ specification: "abstract class Vessel.\n", scope: "TS = 2, StaticObstacle = 0" }));
    const scope = screen.getByRole("textbox", { name: "Scope" });
    await user.clear(scope);
    await user.type(scope, "TS = 3..1");
    expect(screen.getByRole("alert")).toHaveTextContent("The lower bound comes first");
    await user.clear(screen.getByRole("spinbutton", { name: "Max FECs" }));
    expect(latest().exploration.maxFecs).toBeNull();
    const quota = screen.getByRole("spinbutton", { name: "Cases per explored FEC" });
    await user.clear(quota);
    await user.type(quota, "3");
    expect(latest().exploration.quota).toBe(3);
  });

  it("asks for no cases per FEC when the exploration runs alone", () => {
    setup(exploring((draft) => void (draft.steps = ["design_space_exploration"])));
    expect(screen.queryByRole("spinbutton", { name: "Cases per explored FEC" })).not.toBeInTheDocument();
    expect(screen.getByText("The campaign runs the exploration alone, so its FECs need no cases.")).toBeInTheDocument();
  });

  it("shows the control node's reasons at the fields they name", () => {
    setup(exploring(), parseReasons(["design_space_exploration.timeout_s: Input should be greater than 0"]));
    expect(screen.getByText("Input should be greater than 0")).toBeVisible();
  });
});

describe("the Input page of a campaign that explores", () => {
  it("says that the FECs come from the exploration", () => {
    const catalog = { classes: [], classesError: null, classesLoading: false, stacks: undefined, stacksError: null, stacksLoading: false, retry: () => undefined };
    render(<StepHarness Page={InputStep} extra={{ catalog }} initial={exploring()} reasons={parseReasons([])} onDraft={() => undefined} />);
    expect(screen.getByRole("note")).toHaveTextContent("its FECs come from the exploration");
  });
});
