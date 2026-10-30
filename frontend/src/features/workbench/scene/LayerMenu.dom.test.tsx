import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { OverlayVisibility } from "../../../app/uiStore";
import { DEFAULT_CANVAS_SETTINGS } from "./canvasSettings";
import { LayerMenu, type LayerColumn } from "./LayerMenu";

const LAYERS: OverlayVisibility = {
  dot: true,
  velocity: true,
  safetyRadius: false,
  trajectory: true,
  safetyDomain: true,
  staticAvoidanceDomain: false,
  maneuveringDomain: true,
};

function column(key: string, overrides: Partial<LayerColumn> = {}): LayerColumn {
  return { key, label: key === "preview" ? "Preview" : "Simulation", layers: LAYERS, onChange: vi.fn(), ...overrides };
}

describe("LayerMenu", () => {
  it("is one icon button that opens every layer", async () => {
    const user = userEvent.setup();
    render(<LayerMenu columns={[column("preview")]} settings={DEFAULT_CANVAS_SETTINGS} onSettingsChange={vi.fn()} />);

    const button = screen.getByRole("button", { name: "Layers" });
    expect(button).toHaveAttribute("title", "Layers");
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("checkbox", { name: "Tracks" })).not.toBeInTheDocument();

    await user.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    const vessels = screen.getByRole("group", { name: "Vessel layers" });
    expect(within(vessels).getAllByRole("checkbox")).toHaveLength(7);
    expect(screen.getByRole("checkbox", { name: "Tracks" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Safety radius rings" })).not.toBeChecked();
  });

  it("switches a layer of a single stream from its row", async () => {
    const user = userEvent.setup();
    const preview = column("preview");
    render(<LayerMenu columns={[preview]} settings={DEFAULT_CANVAS_SETTINGS} onSettingsChange={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Layers" }));
    await user.click(screen.getByText("Safety domains"));
    expect(preview.onChange).toHaveBeenCalledWith("safetyDomain", false);
    await user.click(screen.getByRole("checkbox", { name: "Static avoidance domains" }));
    expect(preview.onChange).toHaveBeenCalledWith("staticAvoidanceDomain", true);
  });

  it("sets the preview and the simulation side by side, each with its own switch", async () => {
    const user = userEvent.setup();
    const preview = column("preview", { shown: true, onShownChange: vi.fn() });
    const simulation = column("simulation", { shown: false, onShownChange: vi.fn() });
    render(<LayerMenu columns={[preview, simulation]} settings={DEFAULT_CANVAS_SETTINGS} onSettingsChange={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Layers" }));
    expect(screen.getByRole("checkbox", { name: "Preview visible" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Simulation visible" })).not.toBeChecked();

    await user.click(screen.getByRole("checkbox", { name: "Course vectors, Simulation" }));
    expect(simulation.onChange).toHaveBeenCalledWith("velocity", false);
    expect(preview.onChange).not.toHaveBeenCalled();

    await user.click(screen.getByRole("checkbox", { name: "Simulation visible" }));
    expect(simulation.onShownChange).toHaveBeenCalledWith(true);
  });

  it("leaves out the visible row when no stream can be hidden", async () => {
    const user = userEvent.setup();
    render(<LayerMenu columns={[column("preview")]} settings={DEFAULT_CANVAS_SETTINGS} onSettingsChange={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Layers" }));
    expect(screen.queryByText("Visible")).not.toBeInTheDocument();
  });

  it("holds the chart's marks and the vector length", async () => {
    const user = userEvent.setup();
    const onSettingsChange = vi.fn();
    render(<LayerMenu columns={[]} settings={{ ...DEFAULT_CANVAS_SETTINGS, cpa: false }} onSettingsChange={onSettingsChange} />);

    await user.click(screen.getByRole("button", { name: "Layers" }));
    expect(screen.queryByRole("group", { name: "Vessel layers" })).not.toBeInTheDocument();
    const chart = screen.getByRole("group", { name: "Chart" });
    expect(within(chart).getByRole("button", { name: "Range rings" })).toHaveAttribute("aria-pressed", "true");
    expect(within(chart).getByRole("button", { name: "CPA" })).toHaveAttribute("aria-pressed", "false");

    await user.click(within(chart).getByRole("button", { name: "CPA" }));
    expect(onSettingsChange).toHaveBeenCalledWith({ cpa: true });
    await user.selectOptions(within(chart).getByRole("combobox", { name: "Vector length" }), "12");
    expect(onSettingsChange).toHaveBeenCalledWith({ vectorMinutes: 12 });
  });
});
