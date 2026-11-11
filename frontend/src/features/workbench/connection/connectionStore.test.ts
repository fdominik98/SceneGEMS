import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { ConnectionPersisted } from "./connectionStore";
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
  port: 1883,
  tlsConnection: false,
  allowCertificates: false,
  geofence: defaultReferenceGeofence,
};

/** The form as versions before v5 stored it: also with the host the control node dialled. */
const STORED_BEFORE_V5 = { ...FORM, clientBroker: "localhost" };

describe("connection form migration", () => {
  it("moves the single-machine stack's profiles to the control node broker", () => {
    for (const legacy of ["local_mqtt_connection", "host_mqtt_connection"]) {
      const migrated = migrate({ ...STORED_BEFORE_V5, selectedPreset: legacy }, 2);
      expect(migrated.selectedPreset).toBe("control_node_broker");
      expect(migrated.user).toBe("u");
      expect(migrated).not.toHaveProperty("state");
    }
  });

  it("keeps the public TLS broker under its new name", () => {
    expect(migrate({ ...STORED_BEFORE_V5, selectedPreset: "live_mqtt_connection" }, 1).selectedPreset).toBe("waraps_tls_broker");
  });

  it("leaves a hand-typed address in place", () => {
    const migrated = migrate({ ...STORED_BEFORE_V5, selectedPreset: "" }, 2);
    expect(migrated.selectedPreset).toBe("");
    expect(migrated.agentBroker).toBe("10.0.0.8");
  });

  it("moves the control node broker's profile from its v3 key, so the address left in the form is not dialled", () => {
    const migrated = migrate({ ...STORED_BEFORE_V5, agentBroker: "broker", clientBroker: "broker", selectedPreset: "master_broker" }, 3);
    expect(migrated.selectedPreset).toBe("control_node_broker");
    expect(connection.attendedBroker(migrated)).toBeNull();
  });

  it("keeps the other v3 profiles", () => {
    expect(migrate({ ...STORED_BEFORE_V5, selectedPreset: "waraps_tls_broker" }, 3).selectedPreset).toBe("waraps_tls_broker");
    const typed = migrate({ ...STORED_BEFORE_V5, selectedPreset: "" }, 3);
    expect(typed.selectedPreset).toBe("");
    expect(typed.agentBroker).toBe("10.0.0.8");
  });

  it("does not touch a state that is already on the current version", () => {
    const current = { ...FORM, selectedPreset: "" as const };
    expect(migrate(current, 5)).toBe(current);
  });

  it("drops the host the control node dialled, which nothing dials any more", () => {
    const migrated = migrate({ ...STORED_BEFORE_V5, selectedPreset: "waraps_tls_broker" }, 4);
    expect(migrated).not.toHaveProperty("clientBroker");
    expect(migrated.agentBroker).toBe("10.0.0.8");
    expect(migrated.selectedPreset).toBe("waraps_tls_broker");
  });

  it("takes that host for the containers where no host was stored for them", () => {
    const migrated = migrate({ ...STORED_BEFORE_V5, agentBroker: " ", clientBroker: "broker.example.org", selectedPreset: "" }, 4);
    expect(migrated.agentBroker).toBe("broker.example.org");
    expect(connection.attendedBroker(migrated)).toMatchObject({ host: "broker.example.org", port: 1883 });
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
      port: 8883,
      tlsConnection: true,
      allowCertificates: false,
      selectedPreset: "waraps_tls_broker",
    });
    expect(broker).toEqual({ host: "broker.waraps.org", port: 8883, tls: true, allow_certificates: false, user: "lab", password: "secret" });
  });
});
