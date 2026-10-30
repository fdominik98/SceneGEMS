import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { FailureBudgetField } from "./fields";
import type { FailureBudgetDraft } from "./wizardState";

// The failure budget field: a number of cases, or unlimited.

function Budget({ initial, seen }: { initial: FailureBudgetDraft; seen: FailureBudgetDraft[] }) {
  const [value, setValue] = useState<FailureBudgetDraft>(initial);
  return (
    <>
      <label htmlFor="budget">Failure budget</label>
      <FailureBudgetField
        id="budget"
        value={value}
        onChange={(next) => {
          seen.push(next);
          setValue(next);
        }}
      />
    </>
  );
}

describe("FailureBudgetField", () => {
  it("turns unlimited on and off, and brings back the number it replaced", async () => {
    const seen: FailureBudgetDraft[] = [];
    render(<Budget initial={3} seen={seen} />);
    const box = screen.getByLabelText("Failure budget");
    const unlimited = screen.getByRole("checkbox", { name: "Unlimited" });
    expect(box).toHaveValue(3);

    await userEvent.click(unlimited);
    expect(seen.at(-1)).toBe("unlimited");
    expect(box).toBeDisabled();
    expect(box).toHaveValue(null);
    expect(screen.getByText(/Never abandoned/)).toBeInTheDocument();

    await userEvent.click(unlimited);
    expect(seen.at(-1)).toBe(3);
    expect(box).toBeEnabled();
    expect(box).toHaveValue(3);
    expect(screen.queryByText(/Never abandoned/)).not.toBeInTheDocument();
  });

  it("starts from 0 when an unlimited budget loaded from a preset is turned off", async () => {
    const seen: FailureBudgetDraft[] = [];
    render(<Budget initial="unlimited" seen={seen} />);
    expect(screen.getByRole("checkbox", { name: "Unlimited" })).toBeChecked();
    await userEvent.click(screen.getByRole("checkbox", { name: "Unlimited" }));
    expect(seen).toEqual([0]);
    await userEvent.type(screen.getByLabelText("Failure budget"), "5");
    expect(seen.at(-1)).toBe(5);
  });
});
