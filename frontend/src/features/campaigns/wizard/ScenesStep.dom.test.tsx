import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { parseReasons } from "./reasons";
import { ScenesStep } from "./ScenesStep";
import { StepHarness } from "./wizardTestHarness";
import { draftOf } from "./wizardTestData";
import type { WizardDraft } from "./wizardState";

function setup(reasons = parseReasons([])) {
  const seen: WizardDraft[] = [];
  render(<StepHarness Page={ScenesStep} extra={{}} initial={draftOf()} reasons={reasons} onDraft={(draft) => seen.push(draft)} />);
  return { latest: () => seen[seen.length - 1], user: userEvent.setup() };
}

describe("the Scene generation page", () => {
  it("sets the monitor after scene generation", async () => {
    const { latest, user } = setup();
    const monitor = screen.getByRole("group", { name: "Monitor after scene generation" });
    expect(within(monitor).getByRole("radio", { name: /No monitor/ })).toBeChecked();
    await user.click(within(monitor).getByRole("radio", { name: /Post hoc monitor/ }));
    expect(latest().sceneMonitor).toBe("post_hoc");
  });

  it("sets the generation's timeout and the low TCPA option", async () => {
    const { latest, user } = setup();
    const timeout = screen.getByRole("spinbutton", { name: "Scene generation timeout" });
    await user.clear(timeout);
    await user.type(timeout, "90");
    expect(latest().domain.sceneGenerationTimeoutS).toBe(90);
    await user.click(screen.getByRole("checkbox", { name: /Enforce low TCPA/ }));
    expect(latest().domain.enforceLowTcpa).toBe(true);
  });

  it("shows the control node's reasons at the fields they name", () => {
    setup(parseReasons(["scene_generation.monitor: Value error, a generation step cannot be monitored live", "domain.scene_generation_timeout_s: Input should be greater than 0"]));
    expect(screen.getByText("a generation step cannot be monitored live")).toBeVisible();
    expect(screen.getByText("Input should be greater than 0")).toBeVisible();
  });
});
