import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { NumberSetting, StepPanel, StepRow } from "./StepPanel";

describe("StepPanel", () => {
  it("shows the step, its status, where it runs and its run button", () => {
    render(
      <StepPanel step={2} title="Trajectory Generation" status={{ label: "Trajectory ready", tone: "ok" }} where="Plans as a job on the cluster." actions={<button type="button">Generate trajectories</button>}>
        <StepRow label="Input">scene</StepRow>
      </StepPanel>
    );
    const panel = screen.getByRole("region", { name: "Trajectory Generation" });
    expect(within(panel).getByText("Step 2 of 3")).toBeInTheDocument();
    expect(within(panel).getByRole("heading", { name: "Trajectory Generation" })).toBeInTheDocument();
    expect(within(panel).getByRole("status")).toHaveTextContent("Trajectory ready");
    expect(within(panel).getByRole("status")).toHaveClass("step-chip--ok");
    expect(within(panel).getByText("Plans as a job on the cluster.")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Generate trajectories" })).toBeInTheDocument();
    expect(within(panel).getByRole("group", { name: "Input" })).toHaveTextContent("scene");
  });

  it("lists what is missing before it can run, with a way to fix it", async () => {
    const user = userEvent.setup();
    const connect = vi.fn();
    render(
      <StepPanel
        step={3}
        title="Simulation"
        status={{ label: "Not initialized", tone: "idle" }}
        actions={null}
        notices={[{ text: "Take the input trajectories." }, { text: "A live session needs the MQTT broker.", action: { label: "Connect it", onClick: connect } }]}
      >
        {null}
      </StepPanel>
    );
    const notices = screen.getByRole("list", { name: "Before it can run" });
    expect(within(notices).getAllByRole("listitem")).toHaveLength(2);
    await user.click(within(notices).getByRole("button", { name: "Connect it" }));
    expect(connect).toHaveBeenCalledTimes(1);
  });

  it("has no notice list when nothing is missing", () => {
    render(
      <StepPanel step={1} title="Scene Generation" status={{ label: "Idle", tone: "idle" }} actions={null}>
        {null}
      </StepPanel>
    );
    expect(screen.queryByRole("list", { name: "Before it can run" })).not.toBeInTheDocument();
  });
});

describe("StepRow", () => {
  it("puts its buttons at the row's end", () => {
    render(
      <StepRow label="Result" aside={<button type="button">Next: Simulation</button>}>
        planned
      </StepRow>
    );
    const row = screen.getByRole("group", { name: "Result" });
    expect(within(row).getByRole("button", { name: "Next: Simulation" }).parentElement).toHaveClass("step-row-aside");
  });
});

describe("NumberSetting", () => {
  it("names its field with the unit and keeps the value within its bounds", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<NumberSetting label="Timeout" unit="s" integer min={1} max={600} value={240} onChange={onChange} />);
    const field = screen.getByRole("spinbutton", { name: "Timeout (s)" });
    expect(field).toHaveValue(240);
    await user.clear(field);
    expect(onChange).not.toHaveBeenCalled();
    await user.type(field, "9000");
    expect(onChange).toHaveBeenLastCalledWith(600);
  });
});
