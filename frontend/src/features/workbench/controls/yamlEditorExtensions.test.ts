import { describe, expect, it } from "vitest";
import { editorSurface } from "./editorTheme";
import { yamlEditorExtensions } from "./yamlEditorExtensions";

describe("yamlEditorExtensions", () => {
  it("has a list per theme, stable between reads so an editor does not reconfigure", () => {
    expect(yamlEditorExtensions.dark).not.toBe(yamlEditorExtensions.light);
    expect(yamlEditorExtensions.dark).toHaveLength(3);
    expect(yamlEditorExtensions.light).toHaveLength(3);
  });
});

describe("editorSurface", () => {
  it("builds an extension for each theme", () => {
    expect(editorSurface("dark")).toBeTruthy();
    expect(editorSurface("light")).toBeTruthy();
  });
});
