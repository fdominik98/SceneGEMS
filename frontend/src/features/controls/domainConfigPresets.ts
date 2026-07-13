export const COLREGS_CONSTRAINTS_PRESETS = [
  "/domain_config/colregs_constants/general_maritime_constants.yaml",
  "/domain_config/colregs_constants/wara_ps_constants.yaml",
] as const;

export const VESSEL_TYPES_PRESETS = ["/domain_config/vessel_types/vessel_types.yaml"] as const;

export const OBSTACLE_TYPES_PRESETS = [
  "/domain_config/static_obstacle_types/static_obstacle_types.yaml",
] as const;

export const DEFAULT_COLREGS_PRESET = COLREGS_CONSTRAINTS_PRESETS[0];
export const DEFAULT_VESSEL_TYPES_PRESET = VESSEL_TYPES_PRESETS[0];
export const DEFAULT_OBSTACLE_TYPES_PRESET = OBSTACLE_TYPES_PRESETS[0];
