import { beforeEach, describe, expect, it } from "vitest";
import { defaultTexts, sameTexts, useDomainDraftStore } from "./domainDraftStore";

const SAVED = { colregs_constants: "A: 1\n", vessel_types: "Ferry: {}\n", obstacle_types: "Buoy: {}\n" };
const URL_A = "http://127.0.0.1:5174";
const URL_B = "http://10.0.0.2:5174";

beforeEach(() => {
  useDomainDraftStore.setState({ drafts: {} });
});

describe("the domain draft store", () => {
  it("starts a draft from the saved texts and keeps one per cluster", () => {
    useDomainDraftStore.getState().setText(URL_A, SAVED, "colregs_constants", "A: 2\n");
    useDomainDraftStore.getState().setText(URL_A, SAVED, "vessel_types", "Tug: {}\n");
    expect(useDomainDraftStore.getState().drafts[URL_A]).toEqual({ colregs_constants: "A: 2\n", vessel_types: "Tug: {}\n", obstacle_types: "Buoy: {}\n" });
    expect(useDomainDraftStore.getState().drafts[URL_B]).toBeUndefined();
    useDomainDraftStore.getState().discard(URL_A);
    expect(useDomainDraftStore.getState().drafts).toEqual({});
  });

  it("compares texts with line endings aside", () => {
    expect(sameTexts(SAVED, { ...SAVED, colregs_constants: "A: 1\r\n" })).toBe(true);
    expect(sameTexts(SAVED, { ...SAVED, obstacle_types: "Rock: {}\n" })).toBe(false);
  });

  it("takes the default preset of every text, or none while one is missing", () => {
    const presets = {
      colregs_constants: [
        { name: "strict", default: false, content: "A: 5\n" },
        { name: "general", default: true, content: "A: 1\n" },
      ],
      vessel_types: [{ name: "vessel_types", default: true, content: "Ferry: {}\n" }],
      obstacle_types: [{ name: "static_obstacle_types", default: true, content: "Buoy: {}\n" }],
    };
    expect(defaultTexts(presets)).toEqual(SAVED);
    expect(defaultTexts({ ...presets, vessel_types: [] })).toBeNull();
    expect(defaultTexts(undefined)).toBeNull();
  });
});
