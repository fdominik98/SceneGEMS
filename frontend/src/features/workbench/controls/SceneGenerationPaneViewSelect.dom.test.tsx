import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { useUiStore } from "../../../app/uiStore";
import { SceneGenerationPaneViewSelect } from "./SceneGenerationPaneViewSelect";

describe("SceneGenerationPaneViewSelect", () => {
  beforeEach(() => useUiStore.setState({ sceneGenerationPaneView: "specification" }));

  it("calls the specification a FEC and switches to the monitor preview", async () => {
    const user = userEvent.setup();
    render(<SceneGenerationPaneViewSelect />);
    expect(screen.getByRole("tab", { name: "FEC specification" })).toHaveAttribute("aria-selected", "true");
    await user.click(screen.getByRole("tab", { name: "Monitor preview" }));
    expect(useUiStore.getState().sceneGenerationPaneView).toBe("monitor");
  });
});
