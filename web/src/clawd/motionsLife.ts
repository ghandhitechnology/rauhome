/**
 * Clawd's second motion library: the things he does when he is *living* here
 * rather than reacting to you.
 *
 * The first library (`motions.ts`) is conversational — listen, nod, talk,
 * recoil. These are occupational. They exist so that "go and look it up on the
 * laptop" or "doze off by the window" are single, readable actions instead of
 * a walk clip with a caption, and so the model has verbs specific enough to be
 * worth choosing between.
 *
 * Authoring rules, same as the first library:
 *   - anticipate before every move, overshoot the extreme, settle after it
 *   - leave out any parameter the clip does not need, so blink and eye
 *     tracking keep running underneath
 *   - a loop must be seamless at t=0/t=1 on every track it owns
 */

import { gaitDuration, WALK_SPEED } from './gait'
import { defineMotion } from './motion'

// ── at the desk ───────────────────────────────────────────────────────

/** Scanning a screen: eyes sweep, body leans in, one claw taps through it. */
export const search = defineMotion({
  id: 'search',
  duration: 3.4,
  loop: true,
  priority: 1,
  fadeIn: 0.3,
  fadeOut: 0.3,
  tracks: [
    { param: 'angle', keys: [{ t: 0, v: 5 }, { t: 0.5, v: 6.5, ease: 'inOut' }, { t: 1, v: 5, ease: 'inOut' }] },
    { param: 'posX', keys: [{ t: 0, v: 0.8 }, { t: 1, v: 0.8 }] },
    // Reading a results list: down the page in steps, then back to the top.
    {
      param: 'eyeX',
      keys: [
        { t: 0, v: -0.55 },
        { t: 0.18, v: 0.5, ease: 'inOut' },
        { t: 0.22, v: -0.55, ease: 'out' },
        { t: 0.42, v: 0.5, ease: 'inOut' },
        { t: 0.46, v: -0.55, ease: 'out' },
        { t: 0.68, v: 0.45, ease: 'inOut' },
        { t: 0.74, v: -0.5, ease: 'out' },
        { t: 1, v: -0.55, ease: 'inOut' },
      ],
    },
    {
      param: 'eyeY',
      keys: [
        { t: 0, v: 0.1 },
        { t: 0.22, v: 0.28, ease: 'inOut' },
        { t: 0.46, v: 0.42, ease: 'inOut' },
        { t: 0.74, v: 0.2, ease: 'inOut' },
        { t: 1, v: 0.1, ease: 'inOut' },
      ],
    },
    // Scroll taps, not a wave: short, low, irregular.
    {
      param: 'clawR',
      keys: [
        { t: 0, v: -22 },
        { t: 0.2, v: -14, ease: 'out' },
        { t: 0.26, v: -24, ease: 'in' },
        { t: 0.5, v: -14, ease: 'out' },
        { t: 0.56, v: -24, ease: 'in' },
        { t: 0.78, v: -15, ease: 'out' },
        { t: 0.84, v: -23, ease: 'in' },
        { t: 1, v: -22, ease: 'inOut' },
      ],
    },
    { param: 'clawL', keys: [{ t: 0, v: -20 }, { t: 0.5, v: -17, ease: 'inOut' }, { t: 1, v: -20, ease: 'inOut' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Handwriting: hunched, one claw working in small fast arcs. */
export const scribble = defineMotion({
  id: 'scribble',
  duration: 1.5,
  loop: true,
  priority: 1,
  fadeIn: 0.25,
  fadeOut: 0.25,
  tracks: [
    { param: 'angle', keys: [{ t: 0, v: 8 }, { t: 1, v: 8 }] },
    { param: 'posY', keys: [{ t: 0, v: 0.6 }, { t: 1, v: 0.6 }] },
    { param: 'scaleY', keys: [{ t: 0, v: 0.97 }, { t: 1, v: 0.97 }] },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: -30 },
        { t: 0.12, v: -20, ease: 'inOut' },
        { t: 0.25, v: -32, ease: 'inOut' },
        { t: 0.37, v: -19, ease: 'inOut' },
        { t: 0.5, v: -31, ease: 'inOut' },
        { t: 0.62, v: -18, ease: 'inOut' },
        { t: 0.75, v: -33, ease: 'inOut' },
        { t: 0.87, v: -21, ease: 'inOut' },
        { t: 1, v: -30, ease: 'inOut' },
      ],
    },
    { param: 'clawL', keys: [{ t: 0, v: -26 }, { t: 1, v: -26 }] },
    { param: 'eyeY', keys: [{ t: 0, v: 0.5 }, { t: 1, v: 0.5 }] },
    { param: 'eyeX', keys: [{ t: 0, v: -0.2 }, { t: 0.5, v: 0.25, ease: 'inOut' }, { t: 1, v: -0.2, ease: 'inOut' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Head down, eyes tracking line by line, with a page turn near the end. */
export const read = defineMotion({
  id: 'read',
  duration: 5.2,
  loop: true,
  priority: 1,
  fadeIn: 0.35,
  fadeOut: 0.35,
  tracks: [
    { param: 'angle', keys: [{ t: 0, v: 6 }, { t: 1, v: 6 }] },
    { param: 'eyeY', keys: [{ t: 0, v: 0.45 }, { t: 0.85, v: 0.6, ease: 'inOut' }, { t: 0.9, v: 0.4, ease: 'out' }, { t: 1, v: 0.45, ease: 'inOut' }] },
    // Four lines: sweep right slowly, snap back left.
    {
      param: 'eyeX',
      keys: [
        { t: 0, v: -0.5 },
        { t: 0.16, v: 0.45, ease: 'linear' },
        { t: 0.2, v: -0.5, ease: 'out' },
        { t: 0.36, v: 0.45, ease: 'linear' },
        { t: 0.4, v: -0.5, ease: 'out' },
        { t: 0.56, v: 0.45, ease: 'linear' },
        { t: 0.6, v: -0.5, ease: 'out' },
        { t: 0.76, v: 0.45, ease: 'linear' },
        { t: 0.8, v: -0.5, ease: 'out' },
        { t: 1, v: -0.5 },
      ],
    },
    { param: 'clawL', keys: [{ t: 0, v: -34 }, { t: 1, v: -34 }] },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: -34 },
        { t: 0.84, v: -34 },
        { t: 0.89, v: 6, ease: 'out' }, // page turn
        { t: 0.96, v: -34, ease: 'in' },
        { t: 1, v: -34 },
      ],
    },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Both claws sweep open toward whatever he just put on the wall. */
export const present = defineMotion({
  id: 'present',
  duration: 1.15,
  priority: 7,
  fadeIn: 0.14,
  fadeOut: 0.26,
  tracks: [
    {
      param: 'clawL',
      keys: [
        { t: 0, v: 0 },
        { t: 0.16, v: -26, ease: 'in' }, // gather
        { t: 0.46, v: 62, ease: 'outBack' },
        { t: 0.78, v: 54, ease: 'inOut' },
        { t: 1, v: 8, ease: 'inCubic' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: 0 },
        { t: 0.16, v: -26, ease: 'in' },
        { t: 0.5, v: 58, ease: 'outBack' },
        { t: 0.8, v: 50, ease: 'inOut' },
        { t: 1, v: 6, ease: 'inCubic' },
      ],
    },
    { param: 'angle', keys: [{ t: 0, v: 0 }, { t: 0.16, v: 4, ease: 'in' }, { t: 0.46, v: -6, ease: 'outBack' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'posY', keys: [{ t: 0, v: 0 }, { t: 0.16, v: 0.5, ease: 'in' }, { t: 0.46, v: -1, ease: 'outCubic' }, { t: 1, v: 0, ease: 'outBounce' }] },
    { param: 'eyeSmile', keys: [{ t: 0, v: 0 }, { t: 0.46, v: 0.7, ease: 'out' }, { t: 1, v: 0.3, ease: 'inOut' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** One claw thrusts out and holds — "that one". */
export const point = defineMotion({
  id: 'point',
  duration: 0.9,
  priority: 7,
  fadeIn: 0.1,
  fadeOut: 0.24,
  tracks: [
    {
      param: 'clawR',
      keys: [
        { t: 0, v: 0 },
        { t: 0.14, v: -30, ease: 'in' },
        { t: 0.36, v: 74, ease: 'outBack' },
        { t: 0.72, v: 70, ease: 'inOut' },
        { t: 1, v: 10, ease: 'inCubic' },
      ],
    },
    { param: 'clawL', keys: [{ t: 0, v: 0 }, { t: 0.36, v: -20, ease: 'out' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'angle', keys: [{ t: 0, v: 0 }, { t: 0.14, v: -3, ease: 'in' }, { t: 0.36, v: 5, ease: 'outBack' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'eyeX', keys: [{ t: 0, v: 0 }, { t: 0.36, v: 0.6, ease: 'out' }, { t: 1, v: 0.3, ease: 'inOut' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

// ── handling things ───────────────────────────────────────────────────

/**
 * Crouch, take the weight, stand.
 *
 * The weight is the whole point: he goes *down* before he comes up, the rise
 * is slower than the dip, and the body squashes on the way. Without that it
 * reads as a hop next to an object rather than lifting it.
 */
export const lift = defineMotion({
  id: 'lift',
  duration: 1.05,
  priority: 8,
  fadeIn: 0.12,
  fadeOut: 0.2,
  tracks: [
    {
      param: 'posY',
      keys: [
        { t: 0, v: 0 },
        { t: 0.26, v: 2.6, ease: 'inOut' }, // crouch to it
        { t: 0.42, v: 2.6 },
        { t: 0.78, v: -0.6, ease: 'out' }, // stand, slowly
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: 1 },
        { t: 0.26, v: 0.86, ease: 'inOut' },
        { t: 0.5, v: 0.9 },
        { t: 0.8, v: 1.05, ease: 'out' },
        { t: 1, v: 1, ease: 'inOut' },
      ],
    },
    { param: 'scaleX', keys: [{ t: 0, v: 1 }, { t: 0.26, v: 1.1, ease: 'inOut' }, { t: 0.8, v: 0.97, ease: 'out' }, { t: 1, v: 1, ease: 'inOut' }] },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: 0 },
        { t: 0.3, v: -46, ease: 'inOut' }, // reach down
        { t: 0.46, v: -44 },
        { t: 0.82, v: 26, ease: 'out' }, // hold it up
        { t: 1, v: 22, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: 0 },
        { t: 0.3, v: -46, ease: 'inOut' },
        { t: 0.46, v: -44 },
        { t: 0.82, v: 24, ease: 'out' },
        { t: 1, v: 20, ease: 'inOut' },
      ],
    },
    { param: 'angle', keys: [{ t: 0, v: 0 }, { t: 0.3, v: 7, ease: 'inOut' }, { t: 0.82, v: -3, ease: 'out' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'eyeY', keys: [{ t: 0, v: 0 }, { t: 0.3, v: 0.6, ease: 'inOut' }, { t: 0.85, v: 0.1, ease: 'out' }, { t: 1, v: 0 }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Set it down carefully, then straighten and check it. */
export const place = defineMotion({
  id: 'place',
  duration: 1.1,
  priority: 8,
  fadeIn: 0.14,
  fadeOut: 0.22,
  tracks: [
    {
      param: 'posY',
      keys: [
        { t: 0, v: 0 },
        { t: 0.34, v: 2.4, ease: 'inOut' },
        { t: 0.56, v: 2.6 },
        { t: 0.86, v: 0, ease: 'out' },
        { t: 1, v: 0 },
      ],
    },
    { param: 'scaleY', keys: [{ t: 0, v: 1 }, { t: 0.34, v: 0.88, ease: 'inOut' }, { t: 0.86, v: 1.02, ease: 'out' }, { t: 1, v: 1, ease: 'inOut' }] },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: 22 },
        { t: 0.4, v: -44, ease: 'inOut' }, // lower it in
        { t: 0.6, v: -46 },
        { t: 0.72, v: -30, ease: 'out' }, // let go
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: 20 },
        { t: 0.4, v: -44, ease: 'inOut' },
        { t: 0.6, v: -46 },
        { t: 0.72, v: -28, ease: 'out' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    { param: 'angle', keys: [{ t: 0, v: 0 }, { t: 0.4, v: 8, ease: 'inOut' }, { t: 0.9, v: -2, ease: 'out' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'eyeY', keys: [{ t: 0, v: 0.1 }, { t: 0.5, v: 0.62, ease: 'inOut' }, { t: 1, v: 0.2, ease: 'inOut' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

const CARRY_SWING = 26
const CARRY_SPEED = WALK_SPEED * 0.78

/** Walking with both claws locked out in front, body leaning back a little. */
export const carry = defineMotion({
  id: 'carry',
  duration: gaitDuration(CARRY_SWING, CARRY_SPEED),
  loop: true,
  priority: 2,
  fadeIn: 0.2,
  fadeOut: 0.22,
  locomotion: CARRY_SPEED,
  phaseSource: 'distance',
  tracks: [
    { param: 'legSwing', keys: [{ t: 0, v: CARRY_SWING }] },
    // Heavier gait: the body drops harder onto each footfall (0.25 / 0.75) and
    // recovers less, because there is something in his claws resisting it.
    {
      param: 'posY',
      keys: [
        { t: 0, v: -0.35 },
        { t: 0.25, v: 0.2, ease: 'in' },
        { t: 0.5, v: -0.35, ease: 'out' },
        { t: 0.75, v: 0.2, ease: 'in' },
        { t: 1, v: -0.35, ease: 'out' },
      ],
    },
    { param: 'clawL', keys: [{ t: 0, v: 30 }, { t: 0.5, v: 26, ease: 'inOut' }, { t: 1, v: 30, ease: 'inOut' }] },
    { param: 'clawR', keys: [{ t: 0, v: 28 }, { t: 0.5, v: 32, ease: 'inOut' }, { t: 1, v: 28, ease: 'inOut' }] },
    { param: 'angle', keys: [{ t: 0, v: -4 }, { t: 0.5, v: -2.5, ease: 'inOut' }, { t: 1, v: -4, ease: 'inOut' }] },
    { param: 'eyeY', keys: [{ t: 0, v: 0.2 }, { t: 1, v: 0.2 }] },
  ],
})

/**
 * Shoulder into it: low claws, hard lean, legs driving, barely moving.
 *
 * The swing came down from 32 with the stride maths: at a third of walking
 * speed a 32-degree reach means one enormous slow-motion step every two
 * seconds. Short braced steps are both what the geometry allows and what
 * shoving something heavy actually looks like.
 */
const PUSH_SWING = 20
const PUSH_SPEED = WALK_SPEED * 0.34

export const push = defineMotion({
  id: 'push',
  duration: gaitDuration(PUSH_SWING, PUSH_SPEED),
  loop: true,
  priority: 2,
  fadeIn: 0.2,
  fadeOut: 0.24,
  locomotion: PUSH_SPEED,
  phaseSource: 'distance',
  tracks: [
    { param: 'legSwing', keys: [{ t: 0, v: PUSH_SWING }] },
    { param: 'angle', keys: [{ t: 0, v: 15 }, { t: 0.5, v: 18, ease: 'inOut' }, { t: 1, v: 15, ease: 'inOut' }] },
    { param: 'clawL', keys: [{ t: 0, v: 14 }, { t: 1, v: 14 }] },
    { param: 'clawR', keys: [{ t: 0, v: 12 }, { t: 1, v: 12 }] },
    // Braced low the whole way, dipping onto each footfall rather than bobbing.
    {
      param: 'posY',
      keys: [
        { t: 0, v: 0.2 },
        { t: 0.25, v: 0.6, ease: 'in' },
        { t: 0.5, v: 0.2, ease: 'out' },
        { t: 0.75, v: 0.6, ease: 'in' },
        { t: 1, v: 0.2, ease: 'out' },
      ],
    },
    { param: 'scaleX', keys: [{ t: 0, v: 1.0 }, { t: 0.25, v: 1.04, ease: 'in' }, { t: 0.5, v: 1.0, ease: 'out' }, { t: 0.75, v: 1.04, ease: 'in' }, { t: 1, v: 1.0, ease: 'out' }] },
    { param: 'eyeY', keys: [{ t: 0, v: 0.25 }, { t: 1, v: 0.25 }] },
  ],
})

// ── being somewhere ───────────────────────────────────────────────────

/**
 * Nodding off: the head sinks, the eyes lose the fight, and every so often he
 * catches himself. The catch is what makes it read as fighting sleep rather
 * than as being asleep.
 */
export const doze = defineMotion({
  id: 'doze',
  duration: 7.5,
  loop: true,
  priority: 1,
  fadeIn: 0.6,
  fadeOut: 0.5,
  tracks: [
    {
      param: 'angle',
      keys: [
        { t: 0, v: 2 },
        { t: 0.32, v: 13, ease: 'inCubic' }, // head sinks
        { t: 0.4, v: 1, ease: 'outBack' }, // ...catches himself
        { t: 0.72, v: 14, ease: 'inCubic' },
        { t: 0.78, v: 2, ease: 'outBack' },
        { t: 1, v: 2, ease: 'inOut' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: 0 },
        { t: 0.32, v: 1.5, ease: 'inCubic' },
        { t: 0.4, v: -0.3, ease: 'outBack' },
        { t: 0.72, v: 1.7, ease: 'inCubic' },
        { t: 0.78, v: 0, ease: 'outBack' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    {
      param: 'eyeOpenL',
      keys: [
        { t: 0, v: 0.55 },
        { t: 0.3, v: 0.05, ease: 'inOut' },
        { t: 0.4, v: 0.9, ease: 'out' },
        { t: 0.7, v: 0.05, ease: 'inOut' },
        { t: 0.78, v: 0.85, ease: 'out' },
        { t: 1, v: 0.55, ease: 'inOut' },
      ],
    },
    {
      param: 'eyeOpenR',
      keys: [
        { t: 0, v: 0.5 },
        { t: 0.28, v: 0.05, ease: 'inOut' },
        { t: 0.4, v: 0.88, ease: 'out' },
        { t: 0.68, v: 0.05, ease: 'inOut' },
        { t: 0.78, v: 0.82, ease: 'out' },
        { t: 1, v: 0.5, ease: 'inOut' },
      ],
    },
    { param: 'eyeY', keys: [{ t: 0, v: 0.3 }, { t: 0.35, v: 0.55, ease: 'inOut' }, { t: 1, v: 0.3, ease: 'inOut' }] },
    { param: 'clawL', keys: [{ t: 0, v: -30 }, { t: 0.5, v: -34, ease: 'inOut' }, { t: 1, v: -30, ease: 'inOut' }] },
    { param: 'clawR', keys: [{ t: 0, v: -32 }, { t: 0.5, v: -28, ease: 'inOut' }, { t: 1, v: -32, ease: 'inOut' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** A proper jaw-cracking yawn: rear up, squeeze shut, sag. */
export const yawn = defineMotion({
  id: 'yawn',
  duration: 1.9,
  priority: 6,
  fadeIn: 0.2,
  fadeOut: 0.35,
  tracks: [
    { param: 'scaleY', keys: [{ t: 0, v: 1 }, { t: 0.14, v: 0.94, ease: 'in' }, { t: 0.44, v: 1.16, ease: 'outCubic' }, { t: 0.72, v: 0.95, ease: 'inOut' }, { t: 1, v: 1, ease: 'outBounce' }] },
    { param: 'scaleX', keys: [{ t: 0, v: 1 }, { t: 0.44, v: 0.92, ease: 'outCubic' }, { t: 0.72, v: 1.05, ease: 'inOut' }, { t: 1, v: 1, ease: 'outBounce' }] },
    { param: 'posY', keys: [{ t: 0, v: 0 }, { t: 0.44, v: -1.8, ease: 'outCubic' }, { t: 0.78, v: 0.5, ease: 'inOut' }, { t: 1, v: 0, ease: 'outBounce' }] },
    { param: 'angle', keys: [{ t: 0, v: 0 }, { t: 0.44, v: -9, ease: 'outCubic' }, { t: 0.8, v: 5, ease: 'inOut' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'eyeOpenL', keys: [{ t: 0, v: 1 }, { t: 0.34, v: 0, ease: 'in' }, { t: 0.7, v: 0, ease: 'linear' }, { t: 0.9, v: 1, ease: 'out' }, { t: 1, v: 1 }] },
    { param: 'eyeOpenR', keys: [{ t: 0, v: 1 }, { t: 0.32, v: 0, ease: 'in' }, { t: 0.7, v: 0, ease: 'linear' }, { t: 0.92, v: 1, ease: 'out' }, { t: 1, v: 1 }] },
    { param: 'clawL', keys: [{ t: 0, v: 0 }, { t: 0.44, v: 68, ease: 'outCubic' }, { t: 0.8, v: -14, ease: 'inOut' }, { t: 1, v: 0, ease: 'outCubic' }] },
    { param: 'clawR', keys: [{ t: 0, v: 0 }, { t: 0.48, v: 62, ease: 'outCubic' }, { t: 0.82, v: -12, ease: 'inOut' }, { t: 1, v: 0, ease: 'outCubic' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Head back, eyes up, breathing long — watching something far away. */
export const stargaze = defineMotion({
  id: 'stargaze',
  duration: 8.5,
  loop: true,
  priority: 1,
  fadeIn: 0.7,
  fadeOut: 0.6,
  tracks: [
    { param: 'angle', keys: [{ t: 0, v: -8 }, { t: 0.5, v: -10.5, ease: 'inOut' }, { t: 1, v: -8, ease: 'inOut' }] },
    { param: 'eyeY', keys: [{ t: 0, v: -0.62 }, { t: 0.5, v: -0.72, ease: 'inOut' }, { t: 1, v: -0.62, ease: 'inOut' }] },
    { param: 'eyeX', keys: [{ t: 0, v: -0.25 }, { t: 0.35, v: 0.2, ease: 'inOut' }, { t: 0.7, v: -0.3, ease: 'inOut' }, { t: 1, v: -0.25, ease: 'inOut' }] },
    { param: 'posY', keys: [{ t: 0, v: -0.3 }, { t: 0.5, v: -0.8, ease: 'inOut' }, { t: 1, v: -0.3, ease: 'inOut' }] },
    { param: 'clawL', keys: [{ t: 0, v: -12 }, { t: 0.5, v: -16, ease: 'inOut' }, { t: 1, v: -12, ease: 'inOut' }] },
    { param: 'clawR', keys: [{ t: 0, v: -14 }, { t: 0.5, v: -10, ease: 'inOut' }, { t: 1, v: -14, ease: 'inOut' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Lower onto the floor and stay there. */
export const sit = defineMotion({
  id: 'sit',
  duration: 1.25,
  priority: 6,
  fadeIn: 0.18,
  fadeOut: 0.4,
  tracks: [
    { param: 'posY', keys: [{ t: 0, v: 0 }, { t: 0.2, v: -0.6, ease: 'out' }, { t: 0.68, v: 3.6, ease: 'inCubic' }, { t: 0.82, v: 3.2, ease: 'out' }, { t: 1, v: 3.4, ease: 'inOut' }] },
    { param: 'scaleY', keys: [{ t: 0, v: 1 }, { t: 0.68, v: 0.8, ease: 'inCubic' }, { t: 0.84, v: 0.86, ease: 'out' }, { t: 1, v: 0.83, ease: 'inOut' }] },
    { param: 'scaleX', keys: [{ t: 0, v: 1 }, { t: 0.68, v: 1.14, ease: 'inCubic' }, { t: 1, v: 1.11, ease: 'inOut' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
    { param: 'clawL', keys: [{ t: 0, v: 0 }, { t: 0.5, v: -34, ease: 'inOut' }, { t: 1, v: -30, ease: 'inOut' }] },
    { param: 'clawR', keys: [{ t: 0, v: 0 }, { t: 0.5, v: -32, ease: 'inOut' }, { t: 1, v: -28, ease: 'inOut' }] },
    { param: 'angle', keys: [{ t: 0, v: 0 }, { t: 0.68, v: 4, ease: 'inCubic' }, { t: 1, v: 2, ease: 'inOut' }] },
  ],
})

/** Claw to the face, tip back, swallow, down. */
export const sip = defineMotion({
  id: 'sip',
  duration: 1.85,
  priority: 6,
  fadeIn: 0.16,
  fadeOut: 0.26,
  tracks: [
    {
      param: 'clawR',
      keys: [
        { t: 0, v: -20 },
        { t: 0.2, v: -34, ease: 'in' }, // pick it up
        { t: 0.42, v: 52, ease: 'outCubic' }, // to the face
        { t: 0.7, v: 54 },
        { t: 0.86, v: -30, ease: 'inCubic' }, // back down
        { t: 1, v: -20, ease: 'inOut' },
      ],
    },
    { param: 'clawL', keys: [{ t: 0, v: -18 }, { t: 0.5, v: -24, ease: 'inOut' }, { t: 1, v: -18, ease: 'inOut' }] },
    { param: 'angle', keys: [{ t: 0, v: 0 }, { t: 0.5, v: -12, ease: 'inOut' }, { t: 0.72, v: -13, ease: 'inOut' }, { t: 0.92, v: 2, ease: 'inOut' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'posY', keys: [{ t: 0, v: 0 }, { t: 0.5, v: -0.5, ease: 'inOut' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'eyeOpenL', keys: [{ t: 0, v: 1 }, { t: 0.52, v: 0.15, ease: 'inOut' }, { t: 0.78, v: 0.15 }, { t: 0.94, v: 1, ease: 'out' }, { t: 1, v: 1 }] },
    { param: 'eyeOpenR', keys: [{ t: 0, v: 1 }, { t: 0.52, v: 0.12, ease: 'inOut' }, { t: 0.78, v: 0.12 }, { t: 0.94, v: 1, ease: 'out' }, { t: 1, v: 1 }] },
    { param: 'eyeSmile', keys: [{ t: 0, v: 0 }, { t: 0.8, v: 0.5, ease: 'out' }, { t: 1, v: 0.2, ease: 'inOut' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Reach out, tip, hold the pour, straighten. */
export const water = defineMotion({
  id: 'water',
  duration: 2.2,
  priority: 6,
  fadeIn: 0.18,
  fadeOut: 0.28,
  tracks: [
    {
      param: 'clawR',
      keys: [
        { t: 0, v: 0 },
        { t: 0.18, v: -22, ease: 'in' },
        { t: 0.4, v: 40, ease: 'outCubic' }, // out over the pot
        { t: 0.52, v: 24, ease: 'inOut' }, // tip
        { t: 0.72, v: 22, ease: 'inOut' },
        { t: 0.88, v: 44, ease: 'out' }, // right it
        { t: 1, v: 0, ease: 'inCubic' },
      ],
    },
    { param: 'clawL', keys: [{ t: 0, v: 0 }, { t: 0.4, v: -26, ease: 'inOut' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'angle', keys: [{ t: 0, v: 0 }, { t: 0.4, v: 7, ease: 'inOut' }, { t: 0.6, v: 9, ease: 'inOut' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'posX', keys: [{ t: 0, v: 0 }, { t: 0.4, v: 1.2, ease: 'inOut' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'eyeY', keys: [{ t: 0, v: 0 }, { t: 0.45, v: 0.55, ease: 'inOut' }, { t: 0.85, v: 0.5 }, { t: 1, v: 0.1, ease: 'inOut' }] },
    { param: 'eyeSmile', keys: [{ t: 0, v: 0 }, { t: 0.7, v: 0.45, ease: 'out' }, { t: 1, v: 0.15, ease: 'inOut' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

// ── moving about ──────────────────────────────────────────────────────

const TIPTOE_SWING = 16
const TIPTOE_SPEED = WALK_SPEED * 0.62

/** Quick light steps, body held high, claws tucked in. */
export const tiptoe = defineMotion({
  id: 'tiptoe',
  duration: gaitDuration(TIPTOE_SWING, TIPTOE_SPEED),
  loop: true,
  priority: 2,
  fadeIn: 0.16,
  fadeOut: 0.2,
  locomotion: TIPTOE_SPEED,
  phaseSource: 'distance',
  tracks: [
    { param: 'legSwing', keys: [{ t: 0, v: TIPTOE_SWING }] },
    // Held high throughout, with only the faintest touch down on each footfall
    // — the point of a tiptoe is that his weight never really lands.
    { param: 'posY', keys: [{ t: 0, v: -1.9 }, { t: 0.25, v: -1.5, ease: 'in' }, { t: 0.5, v: -1.9, ease: 'out' }, { t: 0.75, v: -1.5, ease: 'in' }, { t: 1, v: -1.9, ease: 'out' }] },
    { param: 'scaleY', keys: [{ t: 0, v: 1.04 }, { t: 1, v: 1.04 }] },
    { param: 'clawL', keys: [{ t: 0, v: -38 }, { t: 0.5, v: -34, ease: 'inOut' }, { t: 1, v: -38, ease: 'inOut' }] },
    { param: 'clawR', keys: [{ t: 0, v: -36 }, { t: 0.5, v: -40, ease: 'inOut' }, { t: 1, v: -36, ease: 'inOut' }] },
    { param: 'angle', keys: [{ t: 0, v: -2 }, { t: 0.5, v: -3.5, ease: 'inOut' }, { t: 1, v: -2, ease: 'inOut' }] },
  ],
})

const PACE_SWING = 30
const PACE_SPEED = WALK_SPEED * 1.18

/** Head-down back-and-forth. Faster than a walk, going nowhere in particular. */
export const pace = defineMotion({
  id: 'pace',
  duration: gaitDuration(PACE_SWING, PACE_SPEED),
  loop: true,
  priority: 2,
  fadeIn: 0.18,
  fadeOut: 0.2,
  locomotion: PACE_SPEED,
  phaseSource: 'distance',
  tracks: [
    { param: 'legSwing', keys: [{ t: 0, v: PACE_SWING }] },
    { param: 'posY', keys: [{ t: 0, v: -0.8 }, { t: 0.25, v: 0.1, ease: 'in' }, { t: 0.5, v: -0.8, ease: 'out' }, { t: 0.75, v: 0.1, ease: 'in' }, { t: 1, v: -0.8, ease: 'out' }] },
    { param: 'angle', keys: [{ t: 0, v: 9 }, { t: 0.5, v: 11, ease: 'inOut' }, { t: 1, v: 9, ease: 'inOut' }] },
    { param: 'eyeY', keys: [{ t: 0, v: 0.42 }, { t: 1, v: 0.42 }] },
    { param: 'clawL', keys: [{ t: 0, v: -26 }, { t: 0.5, v: -20, ease: 'inOut' }, { t: 1, v: -26, ease: 'inOut' }] },
    { param: 'clawR', keys: [{ t: 0, v: -22 }, { t: 0.5, v: -28, ease: 'inOut' }, { t: 1, v: -22, ease: 'inOut' }] },
  ],
})

/** Lean out to see round something, hold, come back. */
export const peek = defineMotion({
  id: 'peek',
  duration: 1.5,
  priority: 6,
  fadeIn: 0.14,
  fadeOut: 0.24,
  tracks: [
    { param: 'posX', keys: [{ t: 0, v: 0 }, { t: 0.12, v: -0.8, ease: 'in' }, { t: 0.38, v: 3.4, ease: 'outCubic' }, { t: 0.66, v: 3.4 }, { t: 1, v: 0, ease: 'inOutCubic' }] },
    { param: 'angle', keys: [{ t: 0, v: 0 }, { t: 0.12, v: -3, ease: 'in' }, { t: 0.38, v: 12, ease: 'outCubic' }, { t: 0.66, v: 12 }, { t: 1, v: 0, ease: 'inOutCubic' }] },
    { param: 'eyeX', keys: [{ t: 0, v: 0 }, { t: 0.38, v: 0.85, ease: 'out' }, { t: 0.7, v: 0.8 }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'eyeOpenL', keys: [{ t: 0, v: 1 }, { t: 0.38, v: 1 }, { t: 0.66, v: 1 }] },
    { param: 'clawL', keys: [{ t: 0, v: 0 }, { t: 0.38, v: -30, ease: 'out' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'clawR', keys: [{ t: 0, v: 0 }, { t: 0.38, v: -34, ease: 'out' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** A small private groove. Weight shifts side to side, claws counter-punch. */
export const groove = defineMotion({
  id: 'groove',
  duration: 1.1,
  loop: true,
  priority: 3,
  fadeIn: 0.2,
  fadeOut: 0.25,
  tracks: [
    { param: 'posX', keys: [{ t: 0, v: -1.1 }, { t: 0.5, v: 1.1, ease: 'inOut' }, { t: 1, v: -1.1, ease: 'inOut' }] },
    { param: 'angle', keys: [{ t: 0, v: -7 }, { t: 0.5, v: 7, ease: 'inOut' }, { t: 1, v: -7, ease: 'inOut' }] },
    { param: 'posY', keys: [{ t: 0, v: 0 }, { t: 0.25, v: -1.3, ease: 'out' }, { t: 0.5, v: 0, ease: 'in' }, { t: 0.75, v: -1.3, ease: 'out' }, { t: 1, v: 0, ease: 'in' }] },
    { param: 'scaleY', keys: [{ t: 0, v: 1 }, { t: 0.25, v: 1.06, ease: 'out' }, { t: 0.5, v: 0.96, ease: 'in' }, { t: 0.75, v: 1.06, ease: 'out' }, { t: 1, v: 1, ease: 'in' }] },
    { param: 'clawL', keys: [{ t: 0, v: 44 }, { t: 0.5, v: -14, ease: 'inOut' }, { t: 1, v: 44, ease: 'inOut' }] },
    { param: 'clawR', keys: [{ t: 0, v: -14 }, { t: 0.5, v: 44, ease: 'inOut' }, { t: 1, v: -14, ease: 'inOut' }] },
    { param: 'eyeSmile', keys: [{ t: 0, v: 0.8 }, { t: 1, v: 0.8 }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Claw over the eyes, head down, slow. */
export const facepalm = defineMotion({
  id: 'facepalm',
  duration: 1.7,
  priority: 7,
  fadeIn: 0.14,
  fadeOut: 0.3,
  tracks: [
    { param: 'clawR', keys: [{ t: 0, v: 0 }, { t: 0.1, v: -18, ease: 'in' }, { t: 0.3, v: 66, ease: 'outCubic' }, { t: 0.78, v: 62 }, { t: 1, v: 6, ease: 'inCubic' }] },
    { param: 'angle', keys: [{ t: 0, v: 0 }, { t: 0.3, v: 6, ease: 'inOut' }, { t: 0.6, v: 13, ease: 'inCubic' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'posY', keys: [{ t: 0, v: 0 }, { t: 0.6, v: 1.6, ease: 'inCubic' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'scaleY', keys: [{ t: 0, v: 1 }, { t: 0.6, v: 0.93, ease: 'inCubic' }, { t: 1, v: 1, ease: 'inOut' }] },
    { param: 'eyeOpenL', keys: [{ t: 0, v: 1 }, { t: 0.34, v: 0, ease: 'in' }, { t: 0.86, v: 0 }, { t: 1, v: 1, ease: 'out' }] },
    { param: 'eyeOpenR', keys: [{ t: 0, v: 1 }, { t: 0.34, v: 0, ease: 'in' }, { t: 0.86, v: 0 }, { t: 1, v: 1, ease: 'out' }] },
    { param: 'clawL', keys: [{ t: 0, v: 0 }, { t: 0.4, v: -28, ease: 'inOut' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Both claws up, quick repeated clap. */
export const applaud = defineMotion({
  id: 'applaud',
  duration: 1.35,
  priority: 7,
  fadeIn: 0.12,
  fadeOut: 0.24,
  tracks: [
    {
      param: 'clawL',
      keys: [
        { t: 0, v: 0 },
        { t: 0.16, v: 50, ease: 'outBack' },
        { t: 0.3, v: 16, ease: 'in' },
        { t: 0.42, v: 48, ease: 'out' },
        { t: 0.54, v: 16, ease: 'in' },
        { t: 0.66, v: 48, ease: 'out' },
        { t: 0.78, v: 18, ease: 'in' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: 0 },
        { t: 0.16, v: 48, ease: 'outBack' },
        { t: 0.3, v: 14, ease: 'in' },
        { t: 0.42, v: 46, ease: 'out' },
        { t: 0.54, v: 14, ease: 'in' },
        { t: 0.66, v: 46, ease: 'out' },
        { t: 0.78, v: 16, ease: 'in' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    { param: 'posY', keys: [{ t: 0, v: 0 }, { t: 0.3, v: -0.7, ease: 'out' }, { t: 0.54, v: 0, ease: 'in' }, { t: 0.78, v: -0.6, ease: 'out' }, { t: 1, v: 0, ease: 'in' }] },
    { param: 'eyeSmile', keys: [{ t: 0, v: 0.2 }, { t: 0.3, v: 1, ease: 'out' }, { t: 1, v: 0.5, ease: 'inOut' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Cold: a fast shudder that runs through the whole body and dies out. */
export const shiver = defineMotion({
  id: 'shiver',
  duration: 1.25,
  priority: 7,
  fadeIn: 0.08,
  fadeOut: 0.28,
  tracks: [
    {
      param: 'posX',
      keys: [
        { t: 0, v: 0 },
        { t: 0.08, v: 0.7 },
        { t: 0.16, v: -0.7 },
        { t: 0.24, v: 0.6 },
        { t: 0.32, v: -0.6 },
        { t: 0.42, v: 0.45 },
        { t: 0.52, v: -0.4 },
        { t: 0.64, v: 0.25 },
        { t: 0.76, v: -0.2 },
        { t: 1, v: 0, ease: 'out' },
      ],
    },
    { param: 'scaleX', keys: [{ t: 0, v: 1 }, { t: 0.2, v: 0.95, ease: 'inOut' }, { t: 0.6, v: 1.02, ease: 'inOut' }, { t: 1, v: 1, ease: 'inOut' }] },
    { param: 'scaleY', keys: [{ t: 0, v: 1 }, { t: 0.2, v: 1.05, ease: 'inOut' }, { t: 0.6, v: 0.98, ease: 'inOut' }, { t: 1, v: 1, ease: 'inOut' }] },
    { param: 'clawL', keys: [{ t: 0, v: 0 }, { t: 0.2, v: -42, ease: 'out' }, { t: 0.7, v: -38 }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'clawR', keys: [{ t: 0, v: 0 }, { t: 0.2, v: -44, ease: 'out' }, { t: 0.7, v: -40 }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'eyeOpenL', keys: [{ t: 0, v: 1 }, { t: 0.2, v: 0.35, ease: 'in' }, { t: 0.7, v: 0.5 }, { t: 1, v: 1, ease: 'out' }] },
    { param: 'eyeOpenR', keys: [{ t: 0, v: 1 }, { t: 0.2, v: 0.32, ease: 'in' }, { t: 0.7, v: 0.48 }, { t: 1, v: 1, ease: 'out' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Trip, catch himself, recover with a little dignity. */
export const stumble = defineMotion({
  id: 'stumble',
  duration: 1.4,
  priority: 8,
  fadeIn: 0.06,
  fadeOut: 0.26,
  tracks: [
    { param: 'posX', keys: [{ t: 0, v: 0 }, { t: 0.14, v: 3.2, ease: 'out' }, { t: 0.34, v: 2.2, ease: 'inOut' }, { t: 0.6, v: 2.6, ease: 'inOut' }, { t: 1, v: 0, ease: 'inOutCubic' }] },
    { param: 'angle', keys: [{ t: 0, v: 0 }, { t: 0.14, v: 26, ease: 'out' }, { t: 0.3, v: -12, ease: 'inOut' }, { t: 0.48, v: 9, ease: 'inOut' }, { t: 0.7, v: -4, ease: 'inOut' }, { t: 1, v: 0, ease: 'outSpring' }] },
    { param: 'posY', keys: [{ t: 0, v: 0 }, { t: 0.14, v: 2.4, ease: 'out' }, { t: 0.36, v: -0.8, ease: 'outCubic' }, { t: 0.56, v: 0.6, ease: 'in' }, { t: 1, v: 0, ease: 'outBounce' }] },
    { param: 'clawL', keys: [{ t: 0, v: 0 }, { t: 0.14, v: 82, ease: 'out' }, { t: 0.44, v: 30, ease: 'inOut' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'clawR', keys: [{ t: 0, v: 0 }, { t: 0.16, v: 76, ease: 'out' }, { t: 0.46, v: 26, ease: 'inOut' }, { t: 1, v: 0, ease: 'inOut' }] },
    { param: 'eyeOpenL', keys: [{ t: 0, v: 1 }, { t: 0.14, v: 1 }, { t: 0.5, v: 1 }] },
    { param: 'legSwing', keys: [{ t: 0, v: 30 }, { t: 0.5, v: 8, ease: 'out' }, { t: 1, v: 0 }] },
  ],
})

/** Tidying: short repeated sweeps low down, weight shifting with each. */
export const tidy = defineMotion({
  id: 'tidy',
  duration: 2.1,
  loop: true,
  priority: 1,
  fadeIn: 0.25,
  fadeOut: 0.25,
  tracks: [
    { param: 'angle', keys: [{ t: 0, v: 10 }, { t: 0.25, v: 13, ease: 'inOut' }, { t: 0.5, v: 10, ease: 'inOut' }, { t: 0.75, v: 13, ease: 'inOut' }, { t: 1, v: 10, ease: 'inOut' }] },
    { param: 'posY', keys: [{ t: 0, v: 1.2 }, { t: 1, v: 1.2 }] },
    { param: 'scaleY', keys: [{ t: 0, v: 0.94 }, { t: 1, v: 0.94 }] },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: -40 },
        { t: 0.18, v: -14, ease: 'out' },
        { t: 0.4, v: -44, ease: 'inOut' },
        { t: 0.58, v: -12, ease: 'out' },
        { t: 0.8, v: -46, ease: 'inOut' },
        { t: 1, v: -40, ease: 'inOut' },
      ],
    },
    { param: 'clawL', keys: [{ t: 0, v: -36 }, { t: 0.5, v: -30, ease: 'inOut' }, { t: 1, v: -36, ease: 'inOut' }] },
    { param: 'posX', keys: [{ t: 0, v: -0.5 }, { t: 0.5, v: 0.5, ease: 'inOut' }, { t: 1, v: -0.5, ease: 'inOut' }] },
    { param: 'eyeY', keys: [{ t: 0, v: 0.55 }, { t: 1, v: 0.55 }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Waiting on something: weight on one side, claws crossed, eyes wandering. */
export const loiter = defineMotion({
  id: 'loiter',
  duration: 6.4,
  loop: true,
  priority: 0,
  fadeIn: 0.5,
  fadeOut: 0.45,
  tracks: [
    { param: 'posX', keys: [{ t: 0, v: 0.9 }, { t: 0.45, v: -0.9, ease: 'inOut' }, { t: 1, v: 0.9, ease: 'inOut' }] },
    { param: 'angle', keys: [{ t: 0, v: 4 }, { t: 0.45, v: -3.5, ease: 'inOut' }, { t: 1, v: 4, ease: 'inOut' }] },
    { param: 'clawL', keys: [{ t: 0, v: -24 }, { t: 0.5, v: -21, ease: 'inOut' }, { t: 1, v: -24, ease: 'inOut' }] },
    { param: 'clawR', keys: [{ t: 0, v: -22 }, { t: 0.5, v: -25, ease: 'inOut' }, { t: 1, v: -22, ease: 'inOut' }] },
    { param: 'eyeX', keys: [{ t: 0, v: -0.4 }, { t: 0.3, v: 0.5, ease: 'inOut' }, { t: 0.62, v: -0.2, ease: 'inOut' }, { t: 1, v: -0.4, ease: 'inOut' }] },
    { param: 'eyeY', keys: [{ t: 0, v: 0.1 }, { t: 0.5, v: -0.2, ease: 'inOut' }, { t: 1, v: 0.1, ease: 'inOut' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** A slow deliberate nod of understanding — heavier than the backchannel nod. */
export const ponder = defineMotion({
  id: 'ponder',
  duration: 3.6,
  loop: true,
  priority: 1,
  fadeIn: 0.35,
  fadeOut: 0.35,
  tracks: [
    { param: 'angle', keys: [{ t: 0, v: 6 }, { t: 0.3, v: 10, ease: 'inOut' }, { t: 0.55, v: 4, ease: 'inOut' }, { t: 1, v: 6, ease: 'inOut' }] },
    { param: 'eyeY', keys: [{ t: 0, v: -0.3 }, { t: 0.35, v: -0.5, ease: 'inOut' }, { t: 0.7, v: 0.2, ease: 'inOut' }, { t: 1, v: -0.3, ease: 'inOut' }] },
    { param: 'eyeX', keys: [{ t: 0, v: 0.35 }, { t: 0.4, v: -0.45, ease: 'inOut' }, { t: 0.8, v: 0.25, ease: 'inOut' }, { t: 1, v: 0.35, ease: 'inOut' }] },
    { param: 'clawR', keys: [{ t: 0, v: 30 }, { t: 0.4, v: 36, ease: 'inOut' }, { t: 1, v: 30, ease: 'inOut' }] },
    { param: 'clawL', keys: [{ t: 0, v: -26 }, { t: 0.5, v: -22, ease: 'inOut' }, { t: 1, v: -26, ease: 'inOut' }] },
    { param: 'posY', keys: [{ t: 0, v: 0.3 }, { t: 0.5, v: 0, ease: 'inOut' }, { t: 1, v: 0.3, ease: 'inOut' }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Every clip in this library, by id. */
export const LIFE_MOTIONS = {
  search,
  scribble,
  read,
  present,
  point,
  lift,
  place,
  carry,
  push,
  doze,
  yawn,
  stargaze,
  sit,
  sip,
  water,
  tiptoe,
  pace,
  peek,
  groove,
  facepalm,
  applaud,
  shiver,
  stumble,
  tidy,
  loiter,
  ponder,
}

/** The ones that must be allowed to finish before anything else is chosen. */
export const LIFE_ONE_SHOTS = [
  'present',
  'point',
  'lift',
  'place',
  'yawn',
  'sit',
  'sip',
  'water',
  'peek',
  'facepalm',
  'applaud',
  'shiver',
  'stumble',
] as const

/** The ones that carry Clawd across the room rather than playing in place. */
export const LIFE_GAITS = ['carry', 'push', 'tiptoe', 'pace'] as const
