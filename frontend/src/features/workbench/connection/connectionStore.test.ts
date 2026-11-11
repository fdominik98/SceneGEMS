import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { ConnectionPersisted } from "./connectionStore";
import { waraps_tls_broker } from "./connectionLibrary";
import { defaultReferenceGeofence } from "./referenceGeofence";
import { MemoryStorage } from "../../../test/memoryStorage";

type ConnectionModule = typeof import("./connectionStore");

const storage = new MemoryStorage();
let connection: ConnectionModule;

beforeAll(async () => {
  vi.stubGlobal("localStorage", storage);
  vi.stubGlobal("window", { localStorage: storage });
  connection = await import("./connectionStore");
});

afterAll(() => {
  vi.unstubAllGlobals();
});

function migrate(persisted: unknown, version: number) {
  const run = connection.useConnectionStore.persist.getOptions().migrate;
  if (!run) {
    throw new Error("connection store has no migrate");
  }
  return run(persisted, version) as ConnectionPersisted;
}

const FORM = {
  user: "u",
  password: "p",
  agentBroker: "10.0.0.8",
  clientBroker: "10.0.0.8",
  port: 1883,
  tlsConnection: false,
  allowCertificates: false,
  geofence: defaultReferenceGeofence,
};

describe("connection form migration", () => {
  it("moves the single-machine stack's profiles to the control node broker", () => {
    for (const legacy of ["local_mqtt_connection", "host_mqtt_connection"]) {
      const migrated = migrate({ ...FORM, selectedPreset: legacy }, 2);
      expect(migrated.selectedPreset).toBe("control_node_broker");
      expect(migrated.user).toBe("u");
      expect(migrated).not.toHaveProperty("state");
    }
  });

  it("keeps the public TLS broker under its new name", () => {
    expect(migrate({ ...FORM, selectedPreset: "live_mqtt_connection" }, 1).selectedPreset).toBe("waraps_tls_broker");
  });

  it("leaves a hand-typed address in place", () => {
    const migrated = migrate({ ...FORM, selectedPreset: "" }, 2);
    expect(migrated.selectedPreset).toBe("");
    expect(migrated.clientBroker).toBe("10.0.0.8");
  });

  it("moves the control node broker's profile from its v3 key, so the address left in the form is not dialled", () => {
    const migrated = migrate({ ...FORM, agentBroker: "broker", clientBroker: "broker", selectedPreset: "master_broker" }, 3);
    expect(migrated.selectedPreset).toBe("control_node_broker");
    expect(connection.buildConnectMessage(migrated)).toMatchObject({ use_control_node_broker: true });
  });

  it("keeps the other v3 profiles", () => {
    expect(migrate({ ...FORM, selectedPreset: "waraps_tls_broker" }, 3).selectedPreset).toBe("waraps_tls_broker");
    const typed = migrate({ ...FORM, selectedPreset: "" }, 3);
    expect(typed.selectedPreset).toBe("");
    expect(typed.clientBroker).toBe("10.0.0.8");
  });

  it("does not touch a state that is already on the current version", () => {
    const current = { ...FORM, selectedPreset: "" as const };
    expect(migrate(current, 4)).toBe(current);
  });
});

describe("connect message", () => {
  it("names the control node broker instead of an address", () => {
    const message = connection.buildConnectMessage({ ...FORM, agentBroker: "", clientBroker: "", selectedPreset: "control_node_broker" });
    expect(message).toMatchObject({ type: "connect_to_mqtt_broker", use_control_node_broker: true });
    expect(connection.connectionFormIsValid({ ...FORM, agentBroker: "", clientBroker: "", selectedPreset: "control_node_broker" })).toBe(true);
  });

  it("sends an external broker's address, trimmed", () => {
    const message = connection.buildConnectMessage({
      ...FORM,
      user: " mqtt ",
      agentBroker: ` ${waraps_tls_broker.agent_broker} `,
      clientBroker: waraps_tls_broker.client_broker,
      port: waraps_tls_broker.port,
      tlsConnection: true,
      selectedPreset: "waraps_tls_broker",
    });
    expect(message).toMatchObject({
      type: "connect_to_mqtt_broker",
      user: "mqtt",
      agent_broker: "broker.waraps.org",
      client_broker: "broker.waraps.org",
      port: 8883,
      tls_connection: true,
      use_control_node_broker: false,
    });
  });

  it("needs an address and a port for another broker", () => {
    expect(connection.connectionFormIsValid({ ...FORM, selectedPreset: "" })).toBe(true);
    expect(connection.connectionFormIsValid({ ...FORM, clientBroker: " ", selectedPreset: "" })).toBe(false);
    expect(connection.connectionFormIsValid({ ...FORM, port: 70000, selectedPreset: "" })).toBe(false);
  });
});

describe("the broker of an attended run with a real vessel", () => {
  it("is not named for the control node's own broker", () => {
    expect(connection.attendedBroker({ ...FORM, selectedPreset: "control_node_broker" })).toBeNull();
  });

  it("is any other broker by the address the vessels' agents dial, trimmed", () => {
    const broker = connection.attendedBroker({
      ...FORM,
      user: " lab ",
      password: "secret",
      agentBroker: " broker.waraps.org ",
      clientBroker: "localhost",
      port: 8883,
      tlsConnection: true,
      allowCertificates: false,
      selectedPreset: "waraps_tls_broker",
    });
    expect(broker).toEqual({ host: "broker.waraps.org", port: 8883, tls: true, allow_certificates: false, user: "lab", password: "secret" });
  });
});
