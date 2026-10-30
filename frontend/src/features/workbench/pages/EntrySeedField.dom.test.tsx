import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { EntrySeedField } from "./EntrySeedField";
import { useEntrySeedStore } from "./entrySeedStore";

describe("EntrySeedField", () => {
  beforeEach(() => useEntrySeedStore.setState({ fixed: null, last: null }));

  it("fixes the seed of the next entries, and empty goes back to a random one", async () => {
    const { container } = render(<EntrySeedField />);
    const setting = container.querySelector(".entry-seed");
    expect(setting).toHaveAttribute("title", "A new random seed per run.");
    expect(screen.getByRole("spinbutton", { name: "Base seed" })).toHaveAttribute("placeholder", "random");
    await userEvent.type(screen.getByRole("spinbutton", { name: "Base seed" }), "123");
    expect(useEntrySeedStore.getState().fixed).toBe(123);
    expect(setting).toHaveAttribute("title", "Every run uses this seed in each step.");
    await userEvent.clear(screen.getByRole("spinbutton", { name: "Base seed" }));
    expect(useEntrySeedStore.getState().fixed).toBeNull();
  });

  it("keeps the seed the last run used", async () => {
    useEntrySeedStore.setState({ last: 987 });
    const { container } = render(<EntrySeedField />);
    expect(container.querySelector(".entry-seed")).toHaveAttribute("title", "A new random seed per run; the last run used 987.");
    await userEvent.click(screen.getByRole("button", { name: "Keep 987" }));
    expect(useEntrySeedStore.getState().fixed).toBe(987);
    expect(screen.getByRole("spinbutton", { name: "Base seed" })).toHaveValue(987);
  });
});
