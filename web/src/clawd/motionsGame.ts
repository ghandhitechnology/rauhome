/**
 * Clawd's third motion library: what he does across a card table.
 *
 * One authoring rule dominates everything here and is worth stating loudly.
 * The seated base pose is the *end* of the existing `sit` clip —
 *
 *     posY 3.4 · scaleY 0.83 · scaleX 1.11 · angle ~2
 *
 * — and every clip below is written around those values rather than around
 * standing neutral. A one-shot authored at posY 0 does not read as "he
 * flinched while sitting", it reads as him standing up out of the chair for
 * three hundred milliseconds and dropping back into it, because the crossfade
 * takes the parameter honestly wherever the clip says to.
 *
 * Otherwise the usual rules: anticipate, overshoot, settle; leave out any
 * parameter the clip does not need so blink and eye tracking keep running;
 * loops seamless at t=0/t=1 on every track they own.
 */

import { defineMotion } from './motion'

/** The seated base, repeated rather than shared so each clip stays readable. */
const SEAT_Y = 3.4
const SEAT_SY = 0.83
const SEAT_SX = 1.11
/** Claws held up and in, which is how you hold a fan you do not want seen. */
const FAN_L = 36
const FAN_R = 42

// ── holding a hand ────────────────────────────────────────────────────

/**
 * Sitting at the table with cards up.
 *
 * Deliberately does not own `breath`: the fan of card backs is anchored to
 * his claws, so leaving breathing to the automatic layer is what makes the
 * cards rise and fall with him for free.
 */
export const sitTable = defineMotion({
  id: 'sitTable',
  duration: 4.6,
  loop: true,
  priority: 5,
  fadeIn: 0.35,
  fadeOut: 0.35,
  tracks: [
    { param: 'posY', keys: [{ t: 0, v: SEAT_Y }] },
    { param: 'scaleY', keys: [{ t: 0, v: SEAT_SY }] },
    { param: 'scaleX', keys: [{ t: 0, v: SEAT_SX }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 1.6 },
        { t: 0.5, v: 2.9, ease: 'inOut' },
        { t: 1, v: 1.6, ease: 'inOut' },
      ],
    },
    // The two claws drift out of phase, so the fan is never quite still.
    {
      param: 'clawL',
      keys: [
        { t: 0, v: FAN_L },
        { t: 0.5, v: FAN_L + 4, ease: 'inOut' },
        { t: 1, v: FAN_L, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: FAN_R },
        { t: 0.42, v: FAN_R - 4, ease: 'inOut' },
        { t: 1, v: FAN_R, ease: 'inOut' },
      ],
    },
  ],
})

// ── taking a turn ─────────────────────────────────────────────────────

/** Reach left to the deck, take one, bring it back into the fan. */
export const reachDraw = defineMotion({
  id: 'reachDraw',
  duration: 0.9,
  priority: 7,
  fadeIn: 0.14,
  fadeOut: 0.24,
  tracks: [
    {
      param: 'clawL',
      keys: [
        { t: 0, v: FAN_L },
        { t: 0.16, v: 48, ease: 'in' }, // anticipation, up and back
        { t: 0.42, v: -20, ease: 'outCubic' }, // down onto the pile
        { t: 0.54, v: -22 }, // takes it
        { t: 0.78, v: 68, ease: 'inCubic' }, // lifts it to the fan
        { t: 1, v: FAN_L, ease: 'inOut' },
      ],
    },
    {
      param: 'posX',
      keys: [
        { t: 0, v: 0 },
        { t: 0.44, v: -2.2, ease: 'inOut' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 1.6 },
        { t: 0.44, v: -3.4, ease: 'inOut' },
        { t: 0.82, v: 3, ease: 'inOut' },
        { t: 1, v: 1.6, ease: 'inOut' },
      ],
    },
    { param: 'posY', keys: [{ t: 0, v: SEAT_Y }] },
    { param: 'scaleY', keys: [{ t: 0, v: SEAT_SY }] },
    { param: 'scaleX', keys: [{ t: 0, v: SEAT_SX }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Flick a card right, onto the discard. Fast, and slightly showy. */
export const flickPlay = defineMotion({
  id: 'flickPlay',
  duration: 0.7,
  priority: 7,
  fadeIn: 0.12,
  fadeOut: 0.22,
  tracks: [
    {
      param: 'clawR',
      keys: [
        { t: 0, v: FAN_R },
        { t: 0.2, v: 16, ease: 'in' }, // wind up
        { t: 0.46, v: 88, ease: 'outBack' }, // snap
        { t: 0.7, v: 50, ease: 'inOut' },
        { t: 1, v: FAN_R, ease: 'inOut' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 1.6 },
        { t: 0.2, v: -1, ease: 'inOut' },
        { t: 0.5, v: 6.4, ease: 'outCubic' },
        { t: 1, v: 1.6, ease: 'inOut' },
      ],
    },
    {
      param: 'posX',
      keys: [
        { t: 0, v: 0 },
        { t: 0.5, v: 1.8, ease: 'outCubic' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    { param: 'posY', keys: [{ t: 0, v: SEAT_Y }] },
    { param: 'scaleY', keys: [{ t: 0, v: SEAT_SY }] },
    { param: 'scaleX', keys: [{ t: 0, v: SEAT_SX }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** NOPE. Both claws up and straight back down on the table. */
export const slamNope = defineMotion({
  id: 'slamNope',
  duration: 0.6,
  priority: 8,
  fadeIn: 0.08,
  fadeOut: 0.2,
  tracks: [
    {
      param: 'clawL',
      keys: [
        { t: 0, v: FAN_L },
        { t: 0.24, v: 94, ease: 'outCubic' },
        { t: 0.46, v: -36, ease: 'inCubic' }, // the slam
        { t: 0.66, v: -18, ease: 'out' },
        { t: 1, v: FAN_L, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: FAN_R },
        { t: 0.24, v: 96, ease: 'outCubic' },
        { t: 0.46, v: -34, ease: 'inCubic' },
        { t: 0.66, v: -16, ease: 'out' },
        { t: 1, v: FAN_R, ease: 'inOut' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: SEAT_Y },
        { t: 0.26, v: SEAT_Y - 0.9, ease: 'outCubic' },
        { t: 0.46, v: SEAT_Y + 0.8, ease: 'inCubic' },
        { t: 1, v: SEAT_Y, ease: 'inOut' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: SEAT_SY },
        { t: 0.26, v: 0.87, ease: 'outCubic' },
        { t: 0.48, v: 0.75, ease: 'inCubic' },
        { t: 1, v: SEAT_SY, ease: 'inOut' },
      ],
    },
    {
      param: 'scaleX',
      keys: [
        { t: 0, v: SEAT_SX },
        { t: 0.26, v: 1.07, ease: 'outCubic' },
        { t: 0.48, v: 1.19, ease: 'inCubic' },
        { t: 1, v: SEAT_SX, ease: 'inOut' },
      ],
    },
    // Held wide open through the whole thing — a blink here would soften it.
    { param: 'eyeOpenL', keys: [{ t: 0, v: 1 }] },
    { param: 'eyeOpenR', keys: [{ t: 0, v: 1 }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

// ── the kitten ────────────────────────────────────────────────────────

/** He drew it. Straight up out of the seat and back down. */
export const kittenRecoil = defineMotion({
  id: 'kittenRecoil',
  duration: 0.9,
  priority: 9,
  fadeIn: 0.05,
  fadeOut: 0.26,
  tracks: [
    {
      param: 'posY',
      keys: [
        { t: 0, v: SEAT_Y },
        { t: 0.1, v: SEAT_Y + 0.3, ease: 'in' }, // the smallest crouch
        { t: 0.3, v: 1.1, ease: 'outCubic' }, // out of the seat
        { t: 0.56, v: SEAT_Y + 0.6, ease: 'inCubic' },
        { t: 1, v: SEAT_Y, ease: 'inOut' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: SEAT_SY },
        { t: 0.1, v: 0.78, ease: 'in' },
        { t: 0.3, v: 0.93, ease: 'outCubic' },
        { t: 0.58, v: 0.79, ease: 'inCubic' },
        { t: 1, v: SEAT_SY, ease: 'inOut' },
      ],
    },
    {
      param: 'scaleX',
      keys: [
        { t: 0, v: SEAT_SX },
        { t: 0.1, v: 1.17, ease: 'in' },
        { t: 0.3, v: 1.02, ease: 'outCubic' },
        { t: 0.58, v: 1.16, ease: 'inCubic' },
        { t: 1, v: SEAT_SX, ease: 'inOut' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 1.6 },
        { t: 0.32, v: -8, ease: 'outCubic' },
        { t: 0.62, v: -3.5, ease: 'inOut' },
        { t: 1, v: 1.6, ease: 'inOut' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: FAN_L },
        { t: 0.28, v: 96, ease: 'outCubic' },
        { t: 0.66, v: 58, ease: 'inOut' },
        { t: 1, v: FAN_L, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: FAN_R },
        { t: 0.28, v: 98, ease: 'outCubic' },
        { t: 0.66, v: 60, ease: 'inOut' },
        { t: 1, v: FAN_R, ease: 'inOut' },
      ],
    },
    { param: 'eyeOpenL', keys: [{ t: 0, v: 1 }] },
    { param: 'eyeOpenR', keys: [{ t: 0, v: 1 }] },
    { param: 'eyeSmile', keys: [{ t: 0, v: 0 }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/**
 * Defused. One long breath out.
 *
 * The only clip here that owns `breath` — relief is a breath, and there is no
 * other channel on this character that says it.
 */
export const defuseRelief = defineMotion({
  id: 'defuseRelief',
  duration: 1,
  priority: 7,
  fadeIn: 0.18,
  fadeOut: 0.3,
  tracks: [
    {
      param: 'breath',
      keys: [
        { t: 0, v: 0.35 },
        { t: 0.24, v: 1, ease: 'outCubic' },
        { t: 0.78, v: 0.12, ease: 'inOutCubic' },
        { t: 1, v: 0.4, ease: 'inOut' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 1.6 },
        { t: 0.5, v: -3, ease: 'inOut' },
        { t: 1, v: 1.6, ease: 'inOut' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: SEAT_Y },
        { t: 0.6, v: SEAT_Y + 0.5, ease: 'inOut' },
        { t: 1, v: SEAT_Y, ease: 'inOut' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: FAN_L },
        { t: 0.5, v: -14, ease: 'inOut' },
        { t: 1, v: FAN_L, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: FAN_R },
        { t: 0.5, v: -10, ease: 'inOut' },
        { t: 1, v: FAN_R, ease: 'inOut' },
      ],
    },
    {
      param: 'eyeOpenL',
      keys: [
        { t: 0, v: 1 },
        { t: 0.4, v: 0.1, ease: 'inOut' },
        { t: 0.72, v: 0.1 },
        { t: 0.92, v: 1, ease: 'out' },
        { t: 1, v: 1 },
      ],
    },
    {
      param: 'eyeOpenR',
      keys: [
        { t: 0, v: 1 },
        { t: 0.4, v: 0.12, ease: 'inOut' },
        { t: 0.72, v: 0.12 },
        { t: 0.92, v: 1, ease: 'out' },
        { t: 1, v: 1 },
      ],
    },
    {
      param: 'eyeSmile',
      keys: [
        { t: 0, v: 0 },
        { t: 0.86, v: 0.45, ease: 'out' },
        { t: 1, v: 0.25, ease: 'inOut' },
      ],
    },
    { param: 'scaleY', keys: [{ t: 0, v: SEAT_SY }] },
    { param: 'scaleX', keys: [{ t: 0, v: SEAT_SX }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

// ── attitude ──────────────────────────────────────────────────────────

/** He just played Attack. Leans in, half-lidded, taps a claw. */
export const smugLean = defineMotion({
  id: 'smugLean',
  duration: 1,
  priority: 7,
  fadeIn: 0.2,
  fadeOut: 0.3,
  tracks: [
    {
      param: 'angle',
      keys: [
        { t: 0, v: 1.6 },
        { t: 0.14, v: -1, ease: 'inOut' }, // pulls back before leaning in
        { t: 0.42, v: 7.4, ease: 'outCubic' },
        { t: 0.72, v: 5.6, ease: 'inOut' },
        { t: 1, v: 1.6, ease: 'inOut' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: SEAT_Y },
        { t: 0.42, v: SEAT_Y - 0.6, ease: 'outCubic' },
        { t: 1, v: SEAT_Y, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: FAN_R },
        { t: 0.46, v: 62, ease: 'outCubic' },
        { t: 0.62, v: 46, ease: 'inCubic' }, // the tap
        { t: 0.76, v: 58, ease: 'out' },
        { t: 1, v: FAN_R, ease: 'inOut' },
      ],
    },
    {
      param: 'eyeOpenL',
      keys: [
        { t: 0, v: 1 },
        { t: 0.4, v: 0.5, ease: 'inOut' },
        { t: 0.82, v: 0.5 },
        { t: 1, v: 1, ease: 'out' },
      ],
    },
    {
      param: 'eyeOpenR',
      keys: [
        { t: 0, v: 1 },
        { t: 0.4, v: 0.48, ease: 'inOut' },
        { t: 0.82, v: 0.48 },
        { t: 1, v: 1, ease: 'out' },
      ],
    },
    {
      param: 'eyeSmile',
      keys: [
        { t: 0, v: 0 },
        { t: 0.5, v: 0.4, ease: 'out' },
        { t: 1, v: 0.15, ease: 'inOut' },
      ],
    },
    { param: 'scaleY', keys: [{ t: 0, v: SEAT_SY }] },
    { param: 'scaleX', keys: [{ t: 0, v: SEAT_SX }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** He lost. Folds forward and stays there — the clip holds its last frame. */
export const slumpLoss = defineMotion({
  id: 'slumpLoss',
  duration: 1.4,
  priority: 8,
  fadeIn: 0.2,
  fadeOut: 0.5,
  tracks: [
    {
      param: 'posY',
      keys: [
        { t: 0, v: SEAT_Y },
        { t: 0.18, v: SEAT_Y - 0.5, ease: 'out' }, // one last hopeful lift
        { t: 0.72, v: SEAT_Y + 2, ease: 'inCubic' },
        { t: 1, v: SEAT_Y + 1.8, ease: 'inOut' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 1.6 },
        { t: 0.2, v: -2, ease: 'out' },
        { t: 0.78, v: 9.5, ease: 'inCubic' },
        { t: 1, v: 8.6, ease: 'inOut' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: FAN_L },
        { t: 0.2, v: 46, ease: 'out' },
        { t: 0.8, v: -52, ease: 'inCubic' },
        { t: 1, v: -48, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: FAN_R },
        { t: 0.2, v: 50, ease: 'out' },
        { t: 0.8, v: -50, ease: 'inCubic' },
        { t: 1, v: -46, ease: 'inOut' },
      ],
    },
    {
      param: 'eyeY',
      keys: [
        { t: 0, v: 0 },
        { t: 0.8, v: 0.85, ease: 'inOut' },
        { t: 1, v: 0.8 },
      ],
    },
    {
      param: 'eyeOpenL',
      keys: [
        { t: 0, v: 1 },
        { t: 0.8, v: 0.42, ease: 'inOut' },
        { t: 1, v: 0.42 },
      ],
    },
    {
      param: 'eyeOpenR',
      keys: [
        { t: 0, v: 1 },
        { t: 0.8, v: 0.4, ease: 'inOut' },
        { t: 1, v: 0.4 },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: SEAT_SY },
        { t: 0.8, v: 0.78, ease: 'inOut' },
        { t: 1, v: 0.78 },
      ],
    },
    { param: 'scaleX', keys: [{ t: 0, v: SEAT_SX }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** He won, and he is still sitting down. Two bounces in the seat. */
export const sitCheer = defineMotion({
  id: 'sitCheer',
  duration: 1.2,
  priority: 8,
  fadeIn: 0.12,
  fadeOut: 0.32,
  tracks: [
    {
      param: 'posY',
      keys: [
        { t: 0, v: SEAT_Y },
        { t: 0.08, v: SEAT_Y + 0.4, ease: 'in' },
        { t: 0.26, v: 1.3, ease: 'outCubic' },
        { t: 0.46, v: SEAT_Y + 0.2, ease: 'inCubic' },
        { t: 0.64, v: 1.8, ease: 'outCubic' },
        { t: 0.84, v: SEAT_Y + 0.1, ease: 'inCubic' },
        { t: 1, v: SEAT_Y, ease: 'inOut' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: SEAT_SY },
        { t: 0.08, v: 0.79, ease: 'in' },
        { t: 0.26, v: 0.91, ease: 'outCubic' },
        { t: 0.46, v: 0.8, ease: 'inCubic' },
        { t: 0.64, v: 0.89, ease: 'outCubic' },
        { t: 1, v: SEAT_SY, ease: 'inOut' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: FAN_L },
        { t: 0.26, v: 96, ease: 'outCubic' },
        { t: 0.5, v: 66, ease: 'inOut' },
        { t: 0.66, v: 98, ease: 'outCubic' },
        { t: 1, v: 44, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: FAN_R },
        { t: 0.26, v: 98, ease: 'outCubic' },
        { t: 0.5, v: 68, ease: 'inOut' },
        { t: 0.66, v: 96, ease: 'outCubic' },
        { t: 1, v: 46, ease: 'inOut' },
      ],
    },
    {
      param: 'eyeSmile',
      keys: [
        { t: 0, v: 0 },
        { t: 0.2, v: 1, ease: 'out' },
        { t: 0.86, v: 1 },
        { t: 1, v: 0.6, ease: 'inOut' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 1.6 },
        { t: 0.3, v: -2.4, ease: 'inOut' },
        { t: 0.68, v: 3.6, ease: 'inOut' },
        { t: 1, v: 1.6, ease: 'inOut' },
      ],
    },
    { param: 'scaleX', keys: [{ t: 0, v: SEAT_SX }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

// ── the ritual ────────────────────────────────────────────────────────

/**
 * The dealing flourish: four flicks of the right claw.
 *
 * `DEAL_FLICKS` is the contract — the cards leave the deck on exactly these
 * beats, so the hand you are dealt looks dealt by him rather than by a timer
 * that happens to be running nearby.
 */
export const DEAL_FLICKS = [0.12, 0.35, 0.58, 0.81]
export const DEAL_DURATION = 1.3

export const dealFlick = defineMotion({
  id: 'dealFlick',
  duration: DEAL_DURATION,
  priority: 7,
  fadeIn: 0.12,
  fadeOut: 0.26,
  tracks: [
    {
      param: 'clawR',
      keys: [
        { t: 0, v: FAN_R },
        { t: 0.06, v: 18, ease: 'in' },
        { t: 0.12, v: 86, ease: 'outBack' },
        { t: 0.22, v: 34, ease: 'inOut' },
        { t: 0.29, v: 16, ease: 'in' },
        { t: 0.35, v: 86, ease: 'outBack' },
        { t: 0.45, v: 34, ease: 'inOut' },
        { t: 0.52, v: 16, ease: 'in' },
        { t: 0.58, v: 86, ease: 'outBack' },
        { t: 0.68, v: 34, ease: 'inOut' },
        { t: 0.75, v: 16, ease: 'in' },
        { t: 0.81, v: 86, ease: 'outBack' },
        { t: 0.92, v: 40, ease: 'inOut' },
        { t: 1, v: FAN_R, ease: 'inOut' },
      ],
    },
    // The left claw holds the rest of the deck steady through all of it.
    {
      param: 'clawL',
      keys: [
        { t: 0, v: FAN_L },
        { t: 0.5, v: 22, ease: 'inOut' },
        { t: 1, v: FAN_L, ease: 'inOut' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 1.6 },
        { t: 0.12, v: 4.2, ease: 'outCubic' },
        { t: 0.35, v: 4, ease: 'inOut' },
        { t: 0.58, v: 4.2, ease: 'inOut' },
        { t: 0.81, v: 4, ease: 'inOut' },
        { t: 1, v: 1.6, ease: 'inOut' },
      ],
    },
    { param: 'posY', keys: [{ t: 0, v: SEAT_Y }] },
    { param: 'scaleY', keys: [{ t: 0, v: SEAT_SY }] },
    { param: 'scaleX', keys: [{ t: 0, v: SEAT_SX }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/** Out of the seat. The reverse of `sit`, and the way every game ends. */
export const standUp = defineMotion({
  id: 'standUp',
  duration: 0.8,
  priority: 6,
  fadeIn: 0.16,
  fadeOut: 0.3,
  tracks: [
    {
      param: 'posY',
      keys: [
        { t: 0, v: SEAT_Y },
        { t: 0.22, v: SEAT_Y + 0.5, ease: 'in' }, // pushes down to push up
        { t: 0.76, v: -0.4, ease: 'outCubic' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: SEAT_SY },
        { t: 0.22, v: 0.79, ease: 'in' },
        { t: 0.78, v: 1.03, ease: 'outCubic' },
        { t: 1, v: 1, ease: 'inOut' },
      ],
    },
    {
      param: 'scaleX',
      keys: [
        { t: 0, v: SEAT_SX },
        { t: 0.22, v: 1.15, ease: 'in' },
        { t: 0.78, v: 0.98, ease: 'outCubic' },
        { t: 1, v: 1, ease: 'inOut' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 1.6 },
        { t: 0.26, v: 3.6, ease: 'inOut' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: FAN_L },
        { t: 0.4, v: 8, ease: 'inOut' },
        { t: 1, v: 4, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: FAN_R },
        { t: 0.4, v: 10, ease: 'inOut' },
        { t: 1, v: -5, ease: 'inOut' },
      ],
    },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

export const GAME_MOTIONS = {
  sitTable,
  reachDraw,
  flickPlay,
  slamNope,
  kittenRecoil,
  defuseRelief,
  smugLean,
  slumpLoss,
  sitCheer,
  dealFlick,
  standUp,
}

/** Everything here except the seated loop must be allowed to finish. */
export const GAME_ONE_SHOTS = [
  'reachDraw',
  'flickPlay',
  'slamNope',
  'kittenRecoil',
  'defuseRelief',
  'smugLean',
  'slumpLoss',
  'sitCheer',
  'dealFlick',
  'standUp',
] as const
