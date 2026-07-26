/**
 * Locomotion constants, in their own module.
 *
 * Both motion libraries need the base walk speed, and `motions.ts` imports the
 * second library to build its registry. Left in `motions.ts` this would be a
 * cycle where the second library reads `WALK_SPEED` from a module still part
 * way through evaluating — a temporal dead zone, so a ReferenceError at import
 * rather than anything as forgiving as `undefined`.
 */

/** Walk cycle speed in stage units/sec. The leg phase is advanced by travel. */
export const WALK_SPEED = 7.5
