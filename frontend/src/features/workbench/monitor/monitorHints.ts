/**
 * Tooltip texts of the monitor panels: what each column, tile and flag means.
 * They follow the monitor's own definitions (`concrete_level/colregs_monitoring` in the backend).
 */

/** Columns of a situation context's per-vessel table. */
export const SITUATION_CONTEXT_HINTS = {
  timeInContext: "Time since the current situation of this pair began.",
  avoidance:
    "The side this encounter alone asks the vessel to alter course to: starboard, port, or ahead when it asks for no alteration.",
  judged:
    "The side the rules judge the vessel against in this encounter. It is fixed when the encounter begins. When the vessel's encounters ask for opposite sides, the side it committed to first is kept.",
  role: "The vessel's role in this encounter: a give-way vessel keeps out of the way, a stand-on vessel keeps her course and speed. A vessel with no give-way duty here shows as stand-on.",
  globalAvoidance:
    "The side over all encounters the vessel is in at this moment: starboard if any of them asks for it, else port, else ahead.",
  globalRole: "Give-way when the vessel has to give way in any of its current encounters, else stand-on.",
} as const;

/** Flags of a pair in the COLREGS monitor state. */
export const COLREGS_STATE_HINTS = {
  inSight: "Either vessel sees the other, now or earlier in the run. A pair that has been in sight stays in sight.",
  passedEachOther:
    "Finally past and clear: the closest point of approach is behind the pair, and the encounter has played out or the vessels have drawn well apart.",
  collisionCourse:
    "With both vessels keeping course and speed, the distance at the closest point of approach (DCPA) is below the safety distance.",
  safetyDomainViolated: "One vessel is inside the safety domain of the other for this encounter.",
  lowTcpa: "The closest point of approach is still ahead and the time to it (TCPA) is below the safe temporal distance.",
} as const;

/** Per-vessel columns of the COLREGS monitor state, by the field they show. */
export const COLREGS_STATE_COLUMN_HINTS = {
  rightOfStartStateByActorId:
    "The vessel is now to starboard of the track it was on when the encounter began.",
  leftOfStartStateByActorId: "The vessel is now to port of the track it was on when the encounter began.",
  haveBeenInRightManeuverByActorId: "The vessel has made a course change to starboard during this encounter.",
  haveBeenInLeftManeuverByActorId: "The vessel has made a course change to port during this encounter.",
  passedPotentialCollisionDomainByActorId:
    "The vessel is clear of the collision domain predicted on its course when the encounter began: beside it or beyond it. Also set when no collision domain was predicted.",
  inFrontOfPotentialCollisionDomainByActorId:
    "The vessel is beyond the far edge of that collision domain, seen along the course it had when the encounter began. Also set when no collision domain was predicted.",
} as const;

/** Tiles and flags of a vessel's maneuver state. */
export const MANEUVER_HINTS = {
  maneuverCount: "Number of the vessel's current maneuver: it goes up each time a new maneuver is detected.",
  turn: "Direction of the heading change in the last time step, when the change is large enough to be detected.",
  headingPrev: "Heading change over the last time step. Positive is to port, negative to starboard.",
  headingStart: "Heading change added up since the current maneuver began. Positive is to port, negative to starboard.",
  headingReadilyApparent:
    "Heading change over the readily apparent time window: the most recent stretch in which a course change has to become readily apparent to the other vessel.",
  speedPrev: "Speed change over the last time step. Positive is faster.",
  speedStart: "Speed change added up since the current maneuver began.",
  speedReadilyApparent:
    "Speed change over the readily apparent time window: the most recent stretch in which a speed change has to become readily apparent to the other vessel.",
  distanceMade: "Distance sailed in the current maneuver, out of the distance sailed since the monitoring began.",
  justStarted: "The current maneuver began in this time step.",
  readilyApparentTimePassed:
    "The current maneuver has lasted at least the readily apparent time, so its course or speed change can be judged for being readily apparent.",
  timespan: "How long the current maneuver has lasted.",
  suggested: "The maneuver types the active rules allow this vessel in the next time step.",
} as const;

/** Tiles of the metrics section. */
export const METRIC_HINTS = {
  distance: "Current distance between the two vessels.",
  dcpa: "Distance at the closest point of approach (DCPA), if both vessels keep course and speed.",
  tcpa: "Time to the closest point of approach (TCPA), if both vessels keep course and speed. Negative once it is behind.",
} as const;

/** Headings of the COLREGS rules panel. */
export const RULE_SCOPE_HINTS = {
  vessels:
    "Rules on a vessel's own maneuvering. They are judged once per vessel, whatever encounters it is in, so they are listed once here and not under each of its encounters.",
  encounters: "Rules of one encounter between two vessels.",
} as const;
