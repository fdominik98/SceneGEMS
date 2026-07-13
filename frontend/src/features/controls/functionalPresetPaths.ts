const GENERATED_FUNCTIONAL_MODELS_PREFIX = "/generated_functional_models/";
const ALL_FOLDER_SEGMENT = "/all/";

/** UI label: path relative to `.../all/` (e.g. `3vessel_0obstacle_scenarios/functional_model0.problem`). */
export function formatFunctionalPresetLabel(path: string): string {
  const allIndex = path.indexOf(ALL_FOLDER_SEGMENT);
  if (allIndex === -1) {
    return path.startsWith(GENERATED_FUNCTIONAL_MODELS_PREFIX)
      ? path.slice(GENERATED_FUNCTIONAL_MODELS_PREFIX.length)
      : path;
  }
  return path.slice(allIndex + ALL_FOLDER_SEGMENT.length);
}
