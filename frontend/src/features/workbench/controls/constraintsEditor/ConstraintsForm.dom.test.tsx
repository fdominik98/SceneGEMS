import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConstraintsForm } from "./ConstraintsForm";

// Picking a steering type from the choice list writes that one value to the YAML and nothing else.

// Two rows in the shape of vessel_types.yaml: the first one carries the comments.
const VESSEL_TYPES = [
  "UnspecifiedVesselType:",
  "    max_speed: 25.722235 # Maximum vessel speed: 50.0 knots in m/s",
  "    steering_type: rudder # How the vessel turns: rudder, skid (two propellers, thrust difference) or vectored_thrust (one turnable engine)",
  "    block_coefficient: 0.65 # Hull fullness: displaced volume over length * beam * draft",
  "",
  "MiniUSV:",
  "    max_speed: 1.028889",
  "    steering_type: skid",
  "    block_coefficient: 0.45",
  "",
].join("\n");

describe("the steering type choice list", () => {
  it("offers the three steering types and writes the picked one to the YAML", () => {
    const onTextChange = vi.fn();
    render(<ConstraintsForm text={VESSEL_TYPES} onTextChange={onTextChange} protectedRows={["UnspecifiedVesselType"]} tableMinRows={1} />);

    const select = screen.getByLabelText("MiniUSV steering_type") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    expect(select.value).toBe("skid");
    expect(Array.from(select.options).map((option) => option.value)).toEqual(["rudder", "skid", "vectored_thrust"]);

    fireEvent.change(select, { target: { value: "vectored_thrust" } });

    expect(onTextChange).toHaveBeenCalledTimes(1);
    expect(onTextChange).toHaveBeenCalledWith(VESSEL_TYPES.replace("steering_type: skid", "steering_type: vectored_thrust"));
  });

  it("writes the first row's steering type and keeps the comment after it", () => {
    const onTextChange = vi.fn();
    render(<ConstraintsForm text={VESSEL_TYPES} onTextChange={onTextChange} tableMinRows={1} />);

    fireEvent.change(screen.getByLabelText("UnspecifiedVesselType steering_type"), { target: { value: "skid" } });

    expect(onTextChange).toHaveBeenCalledWith(VESSEL_TYPES.replace("steering_type: rudder # How", "steering_type: skid # How"));
  });

  it("writes a block coefficient typed into its cell", () => {
    const onTextChange = vi.fn();
    render(<ConstraintsForm text={VESSEL_TYPES} onTextChange={onTextChange} tableMinRows={1} />);

    fireEvent.change(screen.getByLabelText("MiniUSV block_coefficient"), { target: { value: "0.5" } });

    expect(onTextChange).toHaveBeenCalledTimes(1);
    expect(onTextChange).toHaveBeenCalledWith(VESSEL_TYPES.replace("block_coefficient: 0.45", "block_coefficient: 0.5"));
  });
});
