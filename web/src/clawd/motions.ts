/**
 * Clawd's motion library.
 *
 * Each clip is authored the way a 2D animator would: anticipation before a
 * move, overshoot at the extreme, follow-through as it settles. Parameters a
 * clip leaves out stay under automatic control, so blinking and eye tracking
 * keep running through a walk cycle but a sleep clip can pin the eyes shut.
 */

import { gaitDuration, WALK_SPEED } from './gait'
import { defineMotion, type Motion } from './motion'
import { LIFE_MOTIONS, LIFE_ONE_SHOTS } from './motionsLife'
import { GAME_MOTIONS, GAME_ONE_SHOTS } from './motionsGame'
import { CHESS_MOTIONS, CHESS_ONE_SHOTS } from './motionsChess'

export { WALK_SPEED }

export const idle = defineMotion({
  id: 'idle',
  duration: 4.2,
  loop: true,
  priority: 0,
  fadeIn: 0.45,
  fadeOut: 0.45,
  tracks: [
    {
      param: 'clawL',
      keys: [
        { t: 0, v: 4 },
        { t: 0.5, v: -5, ease: 'inOut' },
        { t: 1, v: 4, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: -5 },
        { t: 0.5, v: 4, ease: 'inOut' },
        { t: 1, v: -5, ease: 'inOut' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: -1.4 },
        { t: 0.5, v: 1.4, ease: 'inOut' },
        { t: 1, v: -1.4, ease: 'inOut' },
      ],
    },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/**
 * Past ~26 the two legs in each pair swing far enough to cross over each other
 * and the gait turns into a single scissoring blob.
 */
const WALK_SWING = 24

export const walk = defineMotion({
  id: 'walk',
  // Derived, not authored: the cycle has to cover exactly the ground the legs
  // reach, or the feet skate however carefully the keys are placed.
  duration: gaitDuration(WALK_SWING, WALK_SPEED),
  loop: true,
  priority: 2,
  fadeIn: 0.18,
  fadeOut: 0.2,
  locomotion: WALK_SPEED,
  phaseSource: 'distance',
  tracks: [
    // Legs are furthest forward at phase 0.25 and 0.75 — those are the two
    // footfalls, and everything below is keyed against them.
    //
    // The body is *lowest* at contact, taking the weight, and highest at mid
    // stance as it passes over the planted legs. Keyed the other way round —
    // which is how this read before — a walk looks like a hover.
    {
      param: 'posY',
      keys: [
        { t: 0, v: -0.5 },
        { t: 0.25, v: 0.12, ease: 'in' }, // contact: drops onto it
        { t: 0.5, v: -0.5, ease: 'out' }, // mid stance: rises over the leg
        { t: 0.75, v: 0.12, ease: 'in' },
        { t: 1, v: -0.5, ease: 'out' },
      ],
    },
    // Squash on each footfall keeps the weight readable.
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: 1.03 },
        { t: 0.25, v: 0.95, ease: 'in' },
        { t: 0.5, v: 1.03, ease: 'out' },
        { t: 0.75, v: 0.95, ease: 'in' },
        { t: 1, v: 1.03, ease: 'out' },
      ],
    },
    {
      param: 'scaleX',
      keys: [
        { t: 0, v: 0.98 },
        { t: 0.25, v: 1.05, ease: 'in' },
        { t: 0.5, v: 0.98, ease: 'out' },
        { t: 0.75, v: 1.05, ease: 'in' },
        { t: 1, v: 0.98, ease: 'out' },
      ],
    },
    { param: 'legSwing', keys: [{ t: 0, v: WALK_SWING }] },
    // Claws counter-swing against the legs.
    {
      param: 'clawL',
      keys: [
        { t: 0, v: 22 },
        { t: 0.5, v: -14, ease: 'inOut' },
        { t: 1, v: 22, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: -14 },
        { t: 0.5, v: 22, ease: 'inOut' },
        { t: 1, v: -14, ease: 'inOut' },
      ],
    },
    // A small forward lean. Anything past ~4 degrees reads as toppling over
    // on a body this squat.
    {
      param: 'angle',
      keys: [
        { t: 0, v: 2 },
        { t: 0.5, v: 3.4, ease: 'inOut' },
        { t: 1, v: 2, ease: 'inOut' },
      ],
    },
  ],
})

export const wave = defineMotion({
  id: 'wave',
  duration: 1.9,
  priority: 6,
  fadeIn: 0.16,
  fadeOut: 0.28,
  tracks: [
    {
      param: 'clawR',
      keys: [
        { t: 0, v: 0 },
        { t: 0.1, v: -18, ease: 'in' }, // wind up
        { t: 0.24, v: 82, ease: 'outBack' }, // snap up
        { t: 0.38, v: 58, ease: 'inOut' },
        { t: 0.5, v: 88, ease: 'inOut' },
        { t: 0.62, v: 58, ease: 'inOut' },
        { t: 0.74, v: 88, ease: 'inOut' },
        { t: 0.88, v: 62, ease: 'inOut' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: 0 },
        { t: 0.24, v: -14, ease: 'out' },
        { t: 0.8, v: -10, ease: 'inOut' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 0 },
        { t: 0.24, v: -6, ease: 'outBack' },
        { t: 0.74, v: -5, ease: 'inOut' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: 0 },
        { t: 0.24, v: -0.4, ease: 'out' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    {
      param: 'eyeSmile',
      keys: [
        { t: 0, v: 0 },
        { t: 0.2, v: 1, ease: 'out' },
        { t: 0.85, v: 1 },
        { t: 1, v: 0, ease: 'in' },
      ],
    },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

export const type = defineMotion({
  id: 'type',
  duration: 0.44,
  loop: true,
  priority: 4,
  fadeIn: 0.3,
  fadeOut: 0.3,
  tracks: [
    // Claws alternate like hands on a keyboard.
    {
      param: 'clawL',
      keys: [
        { t: 0, v: -34 },
        { t: 0.25, v: -52, ease: 'in' },
        { t: 0.5, v: -34, ease: 'out' },
        { t: 1, v: -34 },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: -34 },
        { t: 0.5, v: -34 },
        { t: 0.75, v: -52, ease: 'in' },
        { t: 1, v: -34, ease: 'out' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 0.8 },
        { t: 0.5, v: -0.8, ease: 'inOut' },
        { t: 1, v: 0.8, ease: 'inOut' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: -0.08 },
        { t: 0.25, v: 0.04, ease: 'inOut' },
        { t: 0.75, v: 0.04, ease: 'inOut' },
        { t: 1, v: -0.08, ease: 'inOut' },
      ],
    },
    { param: 'eyeY', keys: [{ t: 0, v: 0.55 }] }, // looking down at the desk
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

export const bounce = defineMotion({
  id: 'bounce',
  duration: 1.15,
  priority: 7,
  fadeIn: 0.08,
  fadeOut: 0.22,
  tracks: [
    {
      param: 'posY',
      keys: [
        { t: 0, v: 0 },
        { t: 0.12, v: 0.5, ease: 'in' }, // crouch
        { t: 0.34, v: -6.2, ease: 'outCubic' }, // launch
        { t: 0.56, v: 0, ease: 'inCubic' }, // fall
        { t: 0.66, v: 0.45, ease: 'out' }, // impact squash
        { t: 0.8, v: -1.4, ease: 'outCubic' }, // small second hop
        { t: 0.92, v: 0, ease: 'inCubic' },
        { t: 1, v: 0, ease: 'outBounce' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: 1 },
        { t: 0.12, v: 0.76, ease: 'in' },
        { t: 0.34, v: 1.22, ease: 'outBack' },
        { t: 0.56, v: 1.1, ease: 'in' },
        { t: 0.66, v: 0.8, ease: 'out' },
        { t: 0.8, v: 1.08, ease: 'outBack' },
        { t: 1, v: 1, ease: 'outBounce' },
      ],
    },
    {
      param: 'scaleX',
      keys: [
        { t: 0, v: 1 },
        { t: 0.12, v: 1.22, ease: 'in' },
        { t: 0.34, v: 0.86, ease: 'outBack' },
        { t: 0.56, v: 0.94, ease: 'in' },
        { t: 0.66, v: 1.2, ease: 'out' },
        { t: 0.8, v: 0.95, ease: 'outBack' },
        { t: 1, v: 1, ease: 'outBounce' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: 0 },
        { t: 0.12, v: -26, ease: 'in' },
        { t: 0.34, v: 74, ease: 'outBack' },
        { t: 0.66, v: 20, ease: 'in' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: 0 },
        { t: 0.12, v: -26, ease: 'in' },
        { t: 0.34, v: 74, ease: 'outBack' },
        { t: 0.66, v: 20, ease: 'in' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'eyeSmile',
      keys: [
        { t: 0, v: 0 },
        { t: 0.3, v: 1, ease: 'out' },
        { t: 0.9, v: 1 },
        { t: 1, v: 0, ease: 'in' },
      ],
    },
    { param: 'legSwing', keys: [{ t: 0, v: 12 }] },
  ],
})

export const think = defineMotion({
  id: 'think',
  duration: 3.4,
  loop: true,
  priority: 3,
  fadeIn: 0.4,
  fadeOut: 0.4,
  tracks: [
    // One claw held up near the "chin", tapping slowly.
    {
      param: 'clawR',
      keys: [
        { t: 0, v: 52 },
        { t: 0.18, v: 62, ease: 'inOut' },
        { t: 0.34, v: 52, ease: 'inOut' },
        { t: 0.52, v: 62, ease: 'inOut' },
        { t: 0.68, v: 52, ease: 'inOut' },
        { t: 1, v: 52 },
      ],
    },
    { param: 'clawL', keys: [{ t: 0, v: -20 }] },
    {
      param: 'angle',
      keys: [
        { t: 0, v: -3 },
        { t: 0.5, v: -6, ease: 'inOut' },
        { t: 1, v: -3, ease: 'inOut' },
      ],
    },
    {
      param: 'eyeX',
      keys: [
        { t: 0, v: 0.4 },
        { t: 0.3, v: 0.75, ease: 'inOut' },
        { t: 0.62, v: 0.2, ease: 'inOut' },
        { t: 1, v: 0.4, ease: 'inOut' },
      ],
    },
    { param: 'eyeY', keys: [{ t: 0, v: -0.5 }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

export const sleep = defineMotion({
  id: 'sleep',
  duration: 5.2,
  loop: true,
  priority: 3,
  fadeIn: 0.9,
  fadeOut: 0.6,
  tracks: [
    { param: 'eyeOpenL', keys: [{ t: 0, v: 0 }] },
    { param: 'eyeOpenR', keys: [{ t: 0, v: 0 }] },
    { param: 'eyeSmile', keys: [{ t: 0, v: 0 }] },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: 0.9 },
        { t: 0.5, v: 0.97, ease: 'inOut' },
        { t: 1, v: 0.9, ease: 'inOut' },
      ],
    },
    {
      param: 'scaleX',
      keys: [
        { t: 0, v: 1.08 },
        { t: 0.5, v: 1.02, ease: 'inOut' },
        { t: 1, v: 1.08, ease: 'inOut' },
      ],
    },
    { param: 'posY', keys: [{ t: 0, v: 0.4 }] },
    { param: 'clawL', keys: [{ t: 0, v: -46 }] },
    { param: 'clawR', keys: [{ t: 0, v: -46 }] },
    { param: 'angle', keys: [{ t: 0, v: 2 }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

export const talk = defineMotion({
  id: 'talk',
  duration: 0.9,
  loop: true,
  priority: 5,
  fadeIn: 0.2,
  fadeOut: 0.35,
  tracks: [
    // Small conversational gestures — Clawd "talks with his claws".
    {
      param: 'clawL',
      keys: [
        { t: 0, v: 14 },
        { t: 0.3, v: 34, ease: 'inOut' },
        { t: 0.6, v: 10, ease: 'inOut' },
        { t: 1, v: 14, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: 26 },
        { t: 0.35, v: 8, ease: 'inOut' },
        { t: 0.7, v: 32, ease: 'inOut' },
        { t: 1, v: 26, ease: 'inOut' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: 0 },
        { t: 0.25, v: -0.28, ease: 'inOut' },
        { t: 0.5, v: 0, ease: 'inOut' },
        { t: 0.75, v: -0.2, ease: 'inOut' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: -2 },
        { t: 0.5, v: 2.5, ease: 'inOut' },
        { t: 1, v: -2, ease: 'inOut' },
      ],
    },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

export const celebrate = defineMotion({
  id: 'celebrate',
  duration: 2.1,
  priority: 8,
  fadeIn: 0.1,
  fadeOut: 0.3,
  tracks: [
    {
      param: 'posY',
      keys: [
        { t: 0, v: 0 },
        { t: 0.08, v: 0.5, ease: 'in' },
        { t: 0.24, v: -7.5, ease: 'outCubic' },
        { t: 0.42, v: 0, ease: 'inCubic' },
        { t: 0.5, v: 0.4, ease: 'out' },
        { t: 0.64, v: -4.5, ease: 'outCubic' },
        { t: 0.8, v: 0, ease: 'inCubic' },
        { t: 0.88, v: 0.3, ease: 'out' },
        { t: 1, v: 0, ease: 'outBounce' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: 1 },
        { t: 0.08, v: 0.72, ease: 'in' },
        { t: 0.24, v: 1.26, ease: 'outBack' },
        { t: 0.5, v: 0.82, ease: 'out' },
        { t: 0.64, v: 1.18, ease: 'outBack' },
        { t: 1, v: 1, ease: 'outBounce' },
      ],
    },
    {
      param: 'scaleX',
      keys: [
        { t: 0, v: 1 },
        { t: 0.08, v: 1.26, ease: 'in' },
        { t: 0.24, v: 0.82, ease: 'outBack' },
        { t: 0.5, v: 1.18, ease: 'out' },
        { t: 0.64, v: 0.88, ease: 'outBack' },
        { t: 1, v: 1, ease: 'outBounce' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: 0 },
        { t: 0.24, v: 96, ease: 'outBack' },
        { t: 0.48, v: 70, ease: 'inOut' },
        { t: 0.64, v: 96, ease: 'outBack' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: 0 },
        { t: 0.24, v: 96, ease: 'outBack' },
        { t: 0.48, v: 70, ease: 'inOut' },
        { t: 0.64, v: 96, ease: 'outBack' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 0 },
        { t: 0.24, v: 8, ease: 'inOut' },
        { t: 0.5, v: -8, ease: 'inOut' },
        { t: 0.75, v: 6, ease: 'inOut' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'eyeSmile',
      keys: [
        { t: 0, v: 0 },
        { t: 0.15, v: 1, ease: 'out' },
        { t: 0.92, v: 1 },
        { t: 1, v: 0, ease: 'in' },
      ],
    },
    { param: 'legSwing', keys: [{ t: 0, v: 16 }] },
  ],
})

/** Startled hop — used when Clawd is clicked or something interrupts him. */
export const startle = defineMotion({
  id: 'startle',
  duration: 0.85,
  priority: 9,
  fadeIn: 0.04,
  fadeOut: 0.24,
  tracks: [
    {
      param: 'posY',
      keys: [
        { t: 0, v: 0 },
        { t: 0.14, v: -3.6, ease: 'outCubic' },
        { t: 0.36, v: 0, ease: 'inCubic' },
        { t: 0.46, v: 0.35, ease: 'out' },
        { t: 1, v: 0, ease: 'outBounce' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: 1 },
        { t: 0.14, v: 1.3, ease: 'out' },
        { t: 0.46, v: 0.8, ease: 'out' },
        { t: 1, v: 1, ease: 'outBounce' },
      ],
    },
    {
      param: 'scaleX',
      keys: [
        { t: 0, v: 1 },
        { t: 0.14, v: 0.8, ease: 'out' },
        { t: 0.46, v: 1.2, ease: 'out' },
        { t: 1, v: 1, ease: 'outBounce' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: 0 },
        { t: 0.14, v: 92, ease: 'outBack' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: 0 },
        { t: 0.14, v: 92, ease: 'outBack' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    // Held open on both sides — blinking through a jump-scare reads as him
    // having missed it, and pinning one eye leaves him winking.
    { param: 'eyeOpenL', keys: [{ t: 0, v: 1 }] },
    { param: 'eyeOpenR', keys: [{ t: 0, v: 1 }] },
    { param: 'legSwing', keys: [{ t: 0, v: 22 }] },
  ],
})

/** Looking out of the window: leans back, eyes up and away. */
export const gaze = defineMotion({
  id: 'gaze',
  duration: 6,
  loop: true,
  priority: 3,
  fadeIn: 0.5,
  fadeOut: 0.5,
  tracks: [
    { param: 'angle', keys: [{ t: 0, v: -5 }] },
    {
      param: 'eyeY',
      keys: [
        { t: 0, v: -0.7 },
        { t: 0.5, v: -0.5, ease: 'inOut' },
        { t: 1, v: -0.7, ease: 'inOut' },
      ],
    },
    {
      param: 'eyeX',
      keys: [
        { t: 0, v: -0.2 },
        { t: 0.35, v: 0.3, ease: 'inOut' },
        { t: 0.7, v: -0.3, ease: 'inOut' },
        { t: 1, v: -0.2, ease: 'inOut' },
      ],
    },
    { param: 'clawL', keys: [{ t: 0, v: -12 }] },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: -12 },
        { t: 0.5, v: -4, ease: 'inOut' },
        { t: 1, v: -12, ease: 'inOut' },
      ],
    },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/**
 * Attending to whoever is talking: weight forward, claws lowered and out of
 * the way. Deliberately owns nothing on the face, so blinking keeps running
 * and the director is free to aim the eyes at the camera.
 */
export const listen = defineMotion({
  id: 'listen',
  duration: 3.6,
  loop: true,
  priority: 5,
  fadeIn: 0.3,
  fadeOut: 0.3,
  tracks: [
    {
      param: 'angle',
      keys: [
        { t: 0, v: 3.6 },
        { t: 0.5, v: 4.6, ease: 'inOut' },
        { t: 1, v: 3.6, ease: 'inOut' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: 0.14 },
        { t: 0.5, v: -0.04, ease: 'inOut' },
        { t: 1, v: 0.14, ease: 'inOut' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: 0.985 },
        { t: 0.5, v: 1.005, ease: 'inOut' },
        { t: 1, v: 0.985, ease: 'inOut' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: -30 },
        { t: 0.5, v: -27, ease: 'inOut' },
        { t: 1, v: -30, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: -28 },
        { t: 0.5, v: -31, ease: 'inOut' },
        { t: 1, v: -28, ease: 'inOut' },
      ],
    },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Backchannel nod: dips the whole body, since there is no neck to nod with. */
export const nod = defineMotion({
  id: 'nod',
  duration: 0.42,
  priority: 6,
  fadeIn: 0.07,
  fadeOut: 0.16,
  tracks: [
    {
      param: 'angle',
      keys: [
        { t: 0, v: 0 },
        { t: 0.16, v: -2.4, ease: 'out' }, // tip back to load the nod
        { t: 0.44, v: 7, ease: 'in' },
        { t: 0.68, v: 1.4, ease: 'outCubic' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: 0 },
        { t: 0.16, v: -0.22, ease: 'out' },
        { t: 0.44, v: 0.52, ease: 'in' },
        { t: 0.68, v: -0.08, ease: 'outCubic' },
        { t: 1, v: 0, ease: 'outBounce' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: 1 },
        { t: 0.16, v: 1.03, ease: 'out' },
        { t: 0.44, v: 0.94, ease: 'in' },
        { t: 0.68, v: 1.02, ease: 'outBack' },
        { t: 1, v: 1, ease: 'outBounce' },
      ],
    },
    {
      param: 'scaleX',
      keys: [
        { t: 0, v: 1 },
        { t: 0.16, v: 0.98, ease: 'out' },
        { t: 0.44, v: 1.05, ease: 'in' },
        { t: 0.68, v: 0.99, ease: 'outBack' },
        { t: 1, v: 1, ease: 'outBounce' },
      ],
    },
    // Claws stay planted where the listen pose left them: a nod that also
    // waves the arms about reads as a whole-body agreement, not a backchannel.
    {
      param: 'clawL',
      keys: [
        { t: 0, v: -26 },
        { t: 0.44, v: -31, ease: 'in' },
        { t: 1, v: -26, ease: 'outCubic' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: -26 },
        { t: 0.44, v: -31, ease: 'in' },
        { t: 1, v: -26, ease: 'outCubic' },
      ],
    },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** The small hop of someone who has just been spoken to. */
export const perk = defineMotion({
  id: 'perk',
  duration: 0.62,
  priority: 7,
  fadeIn: 0.12,
  fadeOut: 0.2,
  tracks: [
    {
      param: 'posY',
      keys: [
        { t: 0, v: 0 },
        { t: 0.12, v: 0.4, ease: 'in' }, // crouch
        { t: 0.34, v: -2.8, ease: 'outCubic' },
        { t: 0.56, v: 0, ease: 'inCubic' },
        { t: 0.66, v: 0.3, ease: 'out' },
        { t: 1, v: 0, ease: 'outBounce' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: 1 },
        { t: 0.12, v: 0.86, ease: 'in' },
        { t: 0.34, v: 1.16, ease: 'outBack' },
        { t: 0.66, v: 0.9, ease: 'out' },
        { t: 1, v: 1, ease: 'outBounce' },
      ],
    },
    {
      param: 'scaleX',
      keys: [
        { t: 0, v: 1 },
        { t: 0.12, v: 1.12, ease: 'in' },
        { t: 0.34, v: 0.9, ease: 'outBack' },
        { t: 0.66, v: 1.08, ease: 'out' },
        { t: 1, v: 1, ease: 'outBounce' },
      ],
    },
    // Starts from the lowered listening pose so the hop does not snap the
    // claws to neutral on the first frame.
    {
      param: 'clawL',
      keys: [
        { t: 0, v: -18 },
        { t: 0.12, v: -30, ease: 'in' },
        { t: 0.34, v: 40, ease: 'outBack' },
        { t: 0.6, v: 12, ease: 'in' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: -18 },
        { t: 0.14, v: -30, ease: 'in' },
        { t: 0.36, v: 34, ease: 'outBack' },
        { t: 0.62, v: 10, ease: 'in' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 2 },
        { t: 0.34, v: -4.5, ease: 'outBack' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'eyeSmile',
      keys: [
        { t: 0, v: 0 },
        { t: 0.34, v: 0.7, ease: 'out' },
        { t: 0.8, v: 0.5 },
        { t: 1, v: 0, ease: 'in' },
      ],
    },
    { param: 'legSwing', keys: [{ t: 0, v: 10 }] },
  ],
})

/** Cut off mid-sentence: pulls back, drops the claws, holds the eyes wide. */
export const recoil = defineMotion({
  id: 'recoil',
  duration: 0.72,
  priority: 9,
  fadeIn: 0.05,
  fadeOut: 0.26,
  tracks: [
    {
      param: 'angle',
      keys: [
        { t: 0, v: 0 },
        { t: 0.07, v: 2.5, ease: 'in' }, // the gesture still going forward
        { t: 0.22, v: -9.5, ease: 'outBack' },
        { t: 0.5, v: -4, ease: 'inOut' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: 0 },
        { t: 0.2, v: -0.65, ease: 'outCubic' },
        { t: 0.44, v: 0.3, ease: 'inCubic' },
        { t: 1, v: 0, ease: 'outBounce' },
      ],
    },
    {
      param: 'scaleX',
      keys: [
        { t: 0, v: 1 },
        { t: 0.2, v: 1.14, ease: 'out' },
        { t: 0.44, v: 0.97, ease: 'out' },
        { t: 1, v: 1, ease: 'outBounce' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: 1 },
        { t: 0.2, v: 0.88, ease: 'out' },
        { t: 0.44, v: 1.04, ease: 'out' },
        { t: 1, v: 1, ease: 'outBounce' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: 22 },
        { t: 0.18, v: -54, ease: 'outCubic' },
        { t: 0.55, v: -42, ease: 'inOut' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: 22 },
        { t: 0.2, v: -50, ease: 'outCubic' },
        { t: 0.58, v: -40, ease: 'inOut' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    // Pinned open — a blink in the middle of being interrupted would read as
    // him not having noticed.
    { param: 'eyeOpenL', keys: [{ t: 0, v: 1 }] },
    { param: 'eyeOpenR', keys: [{ t: 0, v: 1 }] },
    { param: 'eyeSmile', keys: [{ t: 0, v: 0 }] },
    { param: 'legSwing', keys: [{ t: 0, v: 14 }] },
  ],
})

/** Uncertainty: claws out and up, weight back, eyes off to one side. */
export const shrug = defineMotion({
  id: 'shrug',
  duration: 1.15,
  priority: 6,
  fadeIn: 0.14,
  fadeOut: 0.26,
  tracks: [
    {
      param: 'clawL',
      keys: [
        { t: 0, v: -14 },
        { t: 0.18, v: -30, ease: 'in' },
        { t: 0.42, v: 46, ease: 'outBack' },
        { t: 0.72, v: 42, ease: 'inOut' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: -14 },
        { t: 0.2, v: -30, ease: 'in' },
        { t: 0.46, v: 40, ease: 'outBack' },
        { t: 0.74, v: 36, ease: 'inOut' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: 0 },
        { t: 0.18, v: 0.3, ease: 'in' },
        { t: 0.42, v: -0.9, ease: 'outCubic' },
        { t: 0.75, v: -0.7, ease: 'inOut' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: 1 },
        { t: 0.18, v: 0.94, ease: 'in' },
        { t: 0.42, v: 1.06, ease: 'outBack' },
        { t: 1, v: 1, ease: 'outCubic' },
      ],
    },
    {
      param: 'scaleX',
      keys: [
        { t: 0, v: 1 },
        { t: 0.18, v: 1.05, ease: 'in' },
        { t: 0.42, v: 0.96, ease: 'outBack' },
        { t: 1, v: 1, ease: 'outCubic' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 0 },
        { t: 0.42, v: -5, ease: 'outBack' },
        { t: 0.72, v: -3.5, ease: 'inOut' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'eyeY',
      keys: [
        { t: 0, v: 0 },
        { t: 0.3, v: -0.5, ease: 'out' },
        { t: 0.78, v: -0.45, ease: 'inOut' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    {
      param: 'eyeX',
      keys: [
        { t: 0, v: 0 },
        { t: 0.35, v: -0.45, ease: 'out' },
        { t: 0.8, v: -0.35, ease: 'inOut' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** A long stretch, eyes screwed shut at the top of it. Idle variety. */
export const stretch = defineMotion({
  id: 'stretch',
  duration: 2.4,
  priority: 3,
  fadeIn: 0.3,
  fadeOut: 0.4,
  tracks: [
    {
      param: 'posY',
      keys: [
        { t: 0, v: 0 },
        { t: 0.16, v: 0.45, ease: 'in' }, // compress before the reach
        { t: 0.42, v: -1.3, ease: 'outCubic' },
        { t: 0.7, v: -1.1, ease: 'inOut' },
        { t: 0.86, v: 0.25, ease: 'in' },
        { t: 1, v: 0, ease: 'outBounce' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: 1 },
        { t: 0.16, v: 0.9, ease: 'in' },
        { t: 0.42, v: 1.14, ease: 'outBack' },
        { t: 0.7, v: 1.12, ease: 'inOut' },
        { t: 0.86, v: 0.94, ease: 'in' },
        { t: 1, v: 1, ease: 'outBounce' },
      ],
    },
    {
      param: 'scaleX',
      keys: [
        { t: 0, v: 1 },
        { t: 0.16, v: 1.1, ease: 'in' },
        { t: 0.42, v: 0.9, ease: 'outBack' },
        { t: 0.7, v: 0.92, ease: 'inOut' },
        { t: 0.86, v: 1.08, ease: 'in' },
        { t: 1, v: 1, ease: 'outBounce' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: 0 },
        { t: 0.16, v: -34, ease: 'in' },
        { t: 0.44, v: 96, ease: 'outBack' },
        { t: 0.72, v: 88, ease: 'inOut' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: 0 },
        { t: 0.18, v: -34, ease: 'in' },
        { t: 0.46, v: 92, ease: 'outBack' },
        { t: 0.74, v: 84, ease: 'inOut' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 0 },
        { t: 0.44, v: -6, ease: 'outBack' },
        { t: 0.72, v: -4, ease: 'inOut' },
        { t: 1, v: 0, ease: 'outCubic' },
      ],
    },
    {
      param: 'eyeOpenL',
      keys: [
        { t: 0, v: 1 },
        { t: 0.38, v: 0.05, ease: 'in' },
        { t: 0.68, v: 0.05 },
        { t: 0.88, v: 1, ease: 'out' },
        { t: 1, v: 1 },
      ],
    },
    {
      param: 'eyeOpenR',
      keys: [
        { t: 0, v: 1 },
        { t: 0.38, v: 0.05, ease: 'in' },
        { t: 0.68, v: 0.05 },
        { t: 0.88, v: 1, ease: 'out' },
        { t: 1, v: 1 },
      ],
    },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Impatient weight shift — small steps on the spot while a job runs. */
export const shuffle = defineMotion({
  id: 'shuffle',
  duration: 2.4,
  loop: true,
  priority: 3,
  fadeIn: 0.3,
  fadeOut: 0.3,
  tracks: [
    // Owning the phase is what makes the feet actually move: the automatic
    // layer only advances it while he is travelling somewhere.
    {
      param: 'legPhase',
      keys: [
        { t: 0, v: 0 },
        { t: 1, v: 1, ease: 'linear' },
      ],
    },
    { param: 'legSwing', keys: [{ t: 0, v: 7 }] },
    {
      param: 'posY',
      keys: [
        { t: 0, v: 0 },
        { t: 0.25, v: -0.18, ease: 'inOut' },
        { t: 0.5, v: 0, ease: 'inOut' },
        { t: 0.75, v: -0.18, ease: 'inOut' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: -2.4 },
        { t: 0.5, v: 2.4, ease: 'inOut' },
        { t: 1, v: -2.4, ease: 'inOut' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: 0.99 },
        { t: 0.5, v: 1.01, ease: 'inOut' },
        { t: 1, v: 0.99, ease: 'inOut' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: -24 },
        { t: 0.3, v: -33, ease: 'inOut' },
        { t: 0.62, v: -19, ease: 'inOut' },
        { t: 1, v: -24, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: -20 },
        { t: 0.34, v: -30, ease: 'inOut' },
        { t: 0.7, v: -26, ease: 'inOut' },
        { t: 1, v: -20, ease: 'inOut' },
      ],
    },
  ],
})

export const MOTIONS = {
  idle,
  walk,
  wave,
  type,
  bounce,
  think,
  sleep,
  talk,
  celebrate,
  startle,
  gaze,
  listen,
  nod,
  perk,
  recoil,
  shrug,
  stretch,
  shuffle,
  // The occupational library: search, doze, lift, carry, sip, present…
  ...LIFE_MOTIONS,
  // The card table: the seated pose and the beats of a hand.
  ...GAME_MOTIONS,
  // The same seat, across a chess board: hesitation, and committing to it.
  ...CHESS_MOTIONS,
} satisfies Record<string, Motion>

export type MotionName = keyof typeof MOTIONS

/** Clips the director should let finish before choosing something new. */
export const ONE_SHOTS: MotionName[] = [
  'wave',
  'bounce',
  'celebrate',
  'startle',
  'nod',
  'perk',
  'recoil',
  'shrug',
  'stretch',
  ...LIFE_ONE_SHOTS,
  ...GAME_ONE_SHOTS,
  ...CHESS_ONE_SHOTS,
]
