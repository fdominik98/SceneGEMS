import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { StepsStep } from "./StepsStep";
import { StepHarness } from "./wizardTestHarness";
import { draftOf } from "./wizardTestData";
import type { WizardDraft } from "./wizardState";

function setup(change: (draft: WizardDraft) => void = () => undefined) {
  const seen: WizardDraft[] = [];
  render(<StepHarness Page={StepsStep} extra={{}} initial={draftOf(change)} onDraft={(draft) => seen.push(draft)} />);
  return { latest: () => seen[seen.length - 1], user: userEvent.setup() };
}

describe("the Steps page", () => {
  it("starts with the whole chain and leaves the monitors to the pages of the steps", () => {
    setup();
    expect(screen.getByRole("radio", { name: /Scene generation\s*Generates scenes/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /Simulation\s*Produces simulated runs/ })).toBeChecked();
    expect(screen.getByText("scene generation, then trajectory generation, then simulation")).toBeVisible();
    expect(screen.queryByRole("group", { name: /Monitor after/ })).not.toBeInTheDocument();
  });

  it("takes the name and the description", async () => {
    const { latest, user } = setup();
    await user.type(screen.getByRole("textbox", { name: "Name" }), "planned");
    expect(latest().name).toBe("planned");
    await user.type(screen.getByRole("textbox", { name: "Description" }), "two steps");
    expect(latest().description).toBe("two steps");
  });

  it("chooses a consecutive part: starting later keeps the last step, stopping early keeps the first", async () => {
    const { latest, user } = setup();
    await user.click(screen.getByRole("radio", { name: /Trajectory generation\s*Plans the trajectories/ }));
    expect(latest().steps).toEqual(["trajectory_generation", "simulation"]);
    await user.click(screen.getByRole("radio", { name: /Trajectory generation\s*Produces trajectories/ }));
    expect(latest().steps).toEqual(["trajectory_generation"]);
    await user.click(screen.getByRole("radio", { name: /Simulation\s*Simulates trajectories/ }));
    expect(latest().steps).toEqual(["simulation"]);
  });

  it("does not offer a last step before the first", async () => {
    setup((draft) => void (draft.steps = ["trajectory_generation", "simulation"]));
    expect(screen.getByRole("radio", { name: /Scene generation\s*Comes before the first step/ })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /Simulation\s*Produces simulated runs/ })).toBeChecked();
  });

  it("says the input comes from earlier results or files when the campaign starts later", () => {
    setup((draft) => void (draft.steps = ["simulation"]));
    expect(screen.getByText(/Its input comes from earlier results or files/)).toBeVisible();
  });

  it("leaves items out that do not fit the new first step", async () => {
    const { latest, user } = setup((draft) => {
      draft.steps = ["trajectory_generation", "simulation"];
      draft.input.items = [
        { id: "a", name: "scene", ref: { sha256: "a".repeat(64), size_bytes: 1, kind: "scene" }, source: { file: "s.json" }, uploadedAt: null },
      ];
    });
    await user.click(screen.getByRole("radio", { name: /Simulation\s*Simulates trajectories/ }));
    expect(latest().steps).toEqual(["simulation"]);
    expect(latest().input.items).toEqual([]);
  });
});
