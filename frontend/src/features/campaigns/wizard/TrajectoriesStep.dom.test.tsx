import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { catalogStacksSchema } from "../../../domain/cluster/campaignApi";
import { sampleCatalogStacks } from "../../../test/fixtures/campaignCatalog";
import { parseReasons } from "./reasons";
import type { CatalogState } from "./stepTypes";
import { TrajectoriesStep } from "./TrajectoriesStep";
import { StepHarness } from "./wizardTestHarness";
import { draftOf } from "./wizardTestData";
import type { WizardDraft } from "./wizardState";

const CATALOG: CatalogState = {
  classes: [],
  classesError: null,
  classesLoading: false,
  stacks: catalogStacksSchema.parse(sampleCatalogStacks),
  stacksError: null,
  stacksLoading: false,
  retry: () => undefined,
};

function setup(reasons = parseReasons([])) {
  const seen: WizardDraft[] = [];
  render(<StepHarness Page={TrajectoriesStep} extra={{ catalog: CATALOG }} initial={draftOf()} reasons={reasons} onDraft={(draft) => seen.push(draft)} />);
  return { latest: () => seen[seen.length - 1], user: userEvent.setup() };
}

describe("the Trajectory generation page", () => {
  it("sets the monitor after trajectory generation beside the generator", async () => {
    const { latest, user } = setup();
    expect(screen.getByRole("group", { name: "Trajectory generator" })).toBeVisible();
    const monitor = screen.getByRole("group", { name: "Monitor after trajectory generation" });
    await user.click(within(monitor).getByRole("radio", { name: /Post hoc monitor/ }));
    expect(latest().trajectoryMonitor).toBe("post_hoc");
    expect(latest().sceneMonitor).toBe("empty");
  });

  it("shows the control node's reason about the monitor under it", () => {
    setup(parseReasons(["trajectories.monitor: Value error, a generation step cannot be monitored live"]));
    expect(screen.getByText("a generation step cannot be monitored live")).toBeVisible();
  });
});
