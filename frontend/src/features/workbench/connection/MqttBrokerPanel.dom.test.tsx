import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { useConnectionStore } from "./connectionStore";
import { MqttBrokerPanel } from "./MqttBrokerPanel";

const initialForm = useConnectionStore.getState();

beforeEach(() => {
  useConnectionStore.setState(initialForm, true);
});

describe("Connections page", () => {
  it("holds settings only: nothing connects from it", () => {
    render(<MqttBrokerPanel />);
    expect(screen.getByText(/nothing connects from this page/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Disconnect" })).toBeNull();
  });

  it("asks for no address while the control node's own broker is chosen", () => {
    render(<MqttBrokerPanel />);
    expect(screen.getByRole("combobox")).toHaveValue("control_node_broker");
    expect(screen.getByText(/The control node's own broker/)).toBeInTheDocument();
    expect(screen.queryByText("Broker address")).toBeNull();
  });

  it("names another broker by the host the worker node's containers dial", async () => {
    const user = userEvent.setup();
    render(<MqttBrokerPanel />);
    await user.selectOptions(screen.getByRole("combobox"), "waraps_tls_broker");
    expect(useConnectionStore.getState()).toMatchObject({ selectedPreset: "waraps_tls_broker", agentBroker: "broker.waraps.org", port: 8883, tlsConnection: true });
    expect(screen.getByText(/broker\.waraps\.org:8883, TLS/)).toBeInTheDocument();
    expect(screen.getByText("Broker address")).toBeInTheDocument();
  });
});
