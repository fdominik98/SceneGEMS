/** Multiples of real time an observed simulation can be paced to. */
export const SPEED_CHOICES = [1, 2, 5, 10, 25, 50, 100] as const;

/** The control node's default pace (design doc 5.3, "Wave 2 contracts"). */
export const DEFAULT_OBSERVED_SPEED = 10;
