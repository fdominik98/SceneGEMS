/** Labels of the encounter types (the backend's COLREGSType names), as the monitor's situation labels read. */
export const ENCOUNTER_TYPE_LABELS: Readonly<Record<string, string>> = {
  OVERTAKING_TO_PORT: "Overtaking to Port",
  OVERTAKING_TO_STARBOARD: "Overtaking to Starboard",
  CROSSING_FROM_PORT: "Crossing from Port",
  HEAD_ON: "Head-On",
  TWO_WAY_CROSSING_FROM_PORT: "Two Way Crossing from Port",
  TWO_WAY_CROSSING_FROM_STARBOARD: "Two Way Crossing from Starboard",
  OTHER: "Other",
};

/** The label of an encounter type; an unknown type (a newer master) reads as its name in words. */
export function encounterTypeLabel(type: string): string {
  const known = ENCOUNTER_TYPE_LABELS[type.toUpperCase()];
  if (known) {
    return known;
  }
  const words = type.toLowerCase().replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
