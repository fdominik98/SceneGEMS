import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ConstraintsForm } from "./ConstraintsForm";
import { GENERAL_COLREGS, OBSTACLE_TYPES, VESSEL_DYNAMICS, VESSEL_TYPES } from "./domainFiles.fixture";

function render(text: string, extra: Partial<Parameters<typeof ConstraintsForm>[0]> = {}): string {
  return renderToStaticMarkup(<ConstraintsForm text={text} onTextChange={() => undefined} {...extra} />);
}

describe("ConstraintsForm", () => {
  it("renders the COLREGS constants with labels, descriptions, units and converted values", () => {
    const html = render(GENERAL_COLREGS);
    expect(html).toContain("Readily apparent course change time");
    expect(html).toContain("READILY_APPARENT_COURSE_CHANGE_TIME");
    expect(html).toContain("Time for a course change to be readily apparent");
    expect(html).toContain("COLREGS maneuver detection parameters");
    expect(html).toContain("Speed change detection parameters");
    // radians and the same value in degrees
    expect(html).toContain('value="0.5235987755982988"');
    expect(html).toContain('value="30"');
    expect(html).toContain("deg");
    // m/s and knots
    expect(html).toContain("kn");
    // seconds and minutes
    expect(html).toContain('value="20"');
  });

  it("renders the vessel types as a table with row actions and the add form", () => {
    const html = render(VESSEL_TYPES, { protectedRows: ["UnspecifiedVesselType"], tableMinRows: 1 });
    expect(html).toContain("<table");
    expect(html).toContain("CargoShip");
    expect(html).toContain("Duplicate");
    expect(html).toContain("Rename");
    expect(html).toContain("Remove");
    expect(html).toContain("Add a type like");
    expect(html).toContain("required");
    expect(html).toContain("Min length");
    expect(html).toContain("rad/s");
  });

  it("renders the steering type of a vessel type as a choice list and the hull ratios as numbers", () => {
    const html = render(VESSEL_TYPES, { protectedRows: ["UnspecifiedVesselType"], tableMinRows: 1 });
    expect(html).toContain("Steering type");
    expect(html).toContain("Block coefficient");
    expect(html).toContain("Length to beam");
    expect(html).toContain("Beam to draft");
    const select = /<select[^>]*aria-label="MiniUSV steering_type"[^>]*>(.*?)<\/select>/.exec(html);
    expect(select).not.toBeNull();
    expect(select?.[1]).toBe('<option value="rudder">rudder</option><option value="skid" selected="">skid</option><option value="vectored_thrust">vectored_thrust</option>');
    expect(html).toMatch(/<input[^>]*aria-label="MiniUSV block_coefficient"[^>]*value="0.45"/);
  });

  it("keeps a steering type the backend does not know selectable, and flags it", () => {
    const html = render("A:\n  steering_type: paddle\nB:\n  steering_type: skid\n");
    const select = /<select[^>]*aria-label="A steering_type"[^>]*>(.*?)<\/select>/.exec(html);
    expect(select?.[1]).toContain('<option value="paddle" selected="">paddle</option>');
    expect(select?.[1]).toContain('<option value="vectored_thrust">vectored_thrust</option>');
    expect(html).toContain("The backend accepts only rudder, skid or vectored_thrust as steering_type.");
  });

  it("renders the obstacle types", () => {
    const html = render(OBSTACLE_TYPES, { protectedRows: ["UnspecifiedObstacleType"] });
    expect(html).toContain("TinyObstacleType");
    expect(html).toContain("Min radius");
  });

  it("renders vessel dynamics generically", () => {
    const html = render(VESSEL_DYNAMICS);
    expect(html).toContain("About this file");
    expect(html).toContain("holds nothing yet");
  });

  it("renders a key it has never seen", () => {
    const html = render(`${GENERAL_COLREGS}\r\nNEVER_SEEN_BEFORE: 7  # Distance (meters) nobody coded\r\n`);
    expect(html).toContain("Never seen before");
    expect(html).toContain("Distance nobody coded");
  });

  it("flags values that need a look", () => {
    const html = render("min_length: 50\nmax_length: 10\n");
    expect(html).toContain("min_length is greater than max_length.");
    expect(html).toContain("2 values need a look");
  });

  it("says so instead of rendering when the YAML does not parse", () => {
    const html = render("a: [1\nb: 2\n", { onShowYaml: () => undefined });
    expect(html).toContain("The YAML does not parse");
    expect(html).toContain("Fix it in the YAML tab");
    expect(html).not.toContain("ce-field");
  });

  it("explains an empty text", () => {
    expect(render("")).toContain("The text is empty");
  });

  it("shows raw nodes it cannot edit", () => {
    const html = render("base: &anchor 5\nalias: *anchor\n");
    expect(html).toContain("cannot be edited in the form");
    expect(html).toContain("*anchor");
  });
});
