/**
 * Locomotion constants and the geometry that keeps feet on the ground.
 *
 * Both motion libraries need the base walk speed, and `motions.ts` imports the
 * second library to build its registry. Left in `motions.ts` this would be a
 * cycle where the second library reads `WALK_SPEED` from a module still part
 * way through evaluating — a temporal dead zone, so a ReferenceError at import
 * rather than anything as forgiving as `undefined`.
 *
 * The stride maths below is the reason a gait no longer slides. A gait clip is
 * played off distance travelled rather than wall time, so the only way the feet
 * can skate is if the clip's cycle covers a different distance than the legs
 * physically reach. `gaitDuration` removes that possibility by deriving the
 * duration from the geometry instead of leaving it to be hand-tuned.
 */

/** Walk cycle speed in stage units/sec. */
export const WALK_SPEED = 7.5

/**
 * Leg length in sprite units — must match `LEG.h` in `sprite.ts`.
 *
 * Legs hang from the body and rotate about their top, so a leg swung to angle
 * A puts its foot `sin(A) * LEG_LENGTH` ahead of the hip.
 */
export const LEG_LENGTH = 2.5

/** Legs alternate in two pairs, so one cycle plants two steps. */
export const STEPS_PER_CYCLE = 2

const DEG = Math.PI / 180

/**
 * Ground covered by one full cycle of a gait with this leg amplitude.
 *
 * A foot travels from `-sin(A)·L` to `+sin(A)·L` relative to the hip, so one
 * planted step is `2·sin(A)·L` of ground and a cycle is twice that.
 */
export function cycleDistance(legSwing: number): number {
  return STEPS_PER_CYCLE * 2 * Math.sin(legSwing * DEG) * LEG_LENGTH
}

/**
 * How long one cycle of a gait lasts at its own cruising speed.
 *
 * Authoring a duration by hand is what let the legs and the body drift apart:
 * the number had no relationship to how far the legs actually reach. Deriving
 * it means a clip cannot be authored into sliding.
 */
export function gaitDuration(legSwing: number, locomotion: number): number {
  return cycleDistance(legSwing) / locomotion
}

/**
 * Leg amplitude that produces `scale`× the stride of `legSwing`.
 *
 * Stride goes with the *sine* of the leg angle, so scaling the angle directly
 * would leave the phase clock and the feet disagreeing by a few percent at the
 * extremes — which is exactly the sliding this module exists to prevent.
 */
export function strideAngle(legSwing: number, scale: number): number {
  const s = Math.sin(legSwing * DEG) * scale
  return (Math.asin(s < -1 ? -1 : s > 1 ? 1 : s) / DEG)
}
