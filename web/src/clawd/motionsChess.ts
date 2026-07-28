/**
 * Clawd's fourth motion library: what he does across a chess board.
 *
 * Everything `motionsGame` says about authoring around the seated base pose
 * applies here without exception and is worth repeating, because it is the
 * one mistake that makes all of this unusable. The seat is
 *
 *     posY 3.4 · scaleY 0.83 · scaleX 1.11 · angle ~2
 *
 * and a clip written around standing neutral does not read as a flinch in a
 * chair, it reads as him standing up for three hundred milliseconds. The
 * claws start and end at the same held-in values the shared `sitTable` loop
 * leaves them at, so a beat can begin and end anywhere in that loop's cycle
 * without a snap on either side.
 *
 * The difference from the card table is what these clips are *for*. He is not
 * playing chess. Stockfish is: every move that lands on the board was chosen
 * by an engine, and his half of it is entirely performance — the pause, the
 * claw that goes out and comes back without touching anything, the moment he
 * sees what he has done. So the clips here are weighted toward hesitation
 * rather than action. `reachHover` and `chinRest` both hold their last frame
 * indefinitely and are meant to: the choreographer keeps them up until the
 * next beat replaces them, and the time he spends apparently deciding is the
 * only thing standing between "an opponent" and "a progress bar with a face".
 */

import { defineMotion } from './motion'

/** The seated base, repeated rather than shared so each clip stays readable. */
const SEAT_Y = 3.4
const SEAT_SY = 0.83
const SEAT_SX = 1.11
/** Where `sitTable` parks the claws. Every clip leaves them back here. */
const REST_L = 36
const REST_R = 42

// ── deciding ──────────────────────────────────────────────────────────

/**
 * The claw goes out over the board, and stays there.
 *
 * The clip ends holding: he is over a square, considering it, and the
 * choreographer leaves him there until the server says he has moved on. The
 * held pose is deliberately *above* the board rather than down on it — the
 * gap is what makes the following `pullBack` a change of mind instead of a
 * fumble.
 */
export const reachHover = defineMotion({
  id: 'reachHover',
  duration: 0.85,
  priority: 7,
  fadeIn: 0.18,
  fadeOut: 0.3,
  tracks: [
    {
      param: 'clawR',
      keys: [
        { t: 0, v: REST_R },
        { t: 0.18, v: 54, ease: 'in' }, // lifts before it goes out
        { t: 0.58, v: -8, ease: 'outCubic' },
        { t: 0.8, v: -14, ease: 'inOut' },
        { t: 1, v: -12 }, // and stops there
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: REST_L },
        { t: 0.6, v: 22, ease: 'inOut' },
        { t: 1, v: 20 },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 1.6 },
        { t: 0.2, v: 0.2, ease: 'inOut' },
        { t: 0.62, v: 4.8, ease: 'outCubic' },
        { t: 1, v: 4.4, ease: 'inOut' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: SEAT_Y },
        { t: 0.62, v: SEAT_Y - 0.4, ease: 'outCubic' },
        { t: 1, v: SEAT_Y - 0.35 },
      ],
    },
    {
      param: 'posX',
      keys: [
        { t: 0, v: 0 },
        { t: 0.62, v: 0.7, ease: 'outCubic' },
        { t: 1, v: 0.65 },
      ],
    },
    // Narrowed rather than shut: he is looking at one square, and the eye
    // tracking underneath still needs somewhere to go.
    {
      param: 'eyeOpenL',
      keys: [
        { t: 0, v: 1 },
        { t: 0.5, v: 0.72, ease: 'inOut' },
        { t: 1, v: 0.72 },
      ],
    },
    {
      param: 'eyeOpenR',
      keys: [
        { t: 0, v: 1 },
        { t: 0.5, v: 0.7, ease: 'inOut' },
        { t: 1, v: 0.7 },
      ],
    },
    { param: 'scaleY', keys: [{ t: 0, v: SEAT_SY }] },
    { param: 'scaleX', keys: [{ t: 0, v: SEAT_SX }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/**
 * Thought better of it.
 *
 * Authored to start from where `reachHover` left him, which is what it always
 * follows. Played cold it still reads — a small reach and an immediate
 * retreat — because the crossfade takes the first value honestly.
 */
export const pullBack = defineMotion({
  id: 'pullBack',
  duration: 0.72,
  priority: 7,
  fadeIn: 0.16,
  fadeOut: 0.26,
  tracks: [
    {
      param: 'clawR',
      keys: [
        { t: 0, v: -6 },
        { t: 0.14, v: -16, ease: 'in' }, // one last dip toward the square
        { t: 0.52, v: 50, ease: 'outCubic' },
        { t: 1, v: REST_R, ease: 'inOut' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: 22 },
        { t: 0.6, v: 34, ease: 'inOut' },
        { t: 1, v: REST_L, ease: 'inOut' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 4.4 },
        { t: 0.12, v: 5.4, ease: 'inOut' },
        { t: 0.58, v: -1.8, ease: 'inOutCubic' }, // sits back off the board
        { t: 1, v: 1.6, ease: 'inOut' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: SEAT_Y - 0.35 },
        { t: 0.62, v: SEAT_Y + 0.45, ease: 'inOutCubic' },
        { t: 1, v: SEAT_Y, ease: 'inOut' },
      ],
    },
    {
      param: 'posX',
      keys: [
        { t: 0, v: 0.65 },
        { t: 0.62, v: -0.4, ease: 'inOutCubic' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    {
      param: 'eyeOpenL',
      keys: [
        { t: 0, v: 0.72 },
        { t: 0.56, v: 1, ease: 'out' },
        { t: 1, v: 1 },
      ],
    },
    {
      param: 'eyeOpenR',
      keys: [
        { t: 0, v: 0.7 },
        { t: 0.56, v: 1, ease: 'out' },
        { t: 1, v: 1 },
      ],
    },
    { param: 'scaleY', keys: [{ t: 0, v: SEAT_SY }] },
    { param: 'scaleX', keys: [{ t: 0, v: SEAT_SX }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/**
 * A claw up under the chin, and a long think.
 *
 * The only loop in this library, and the reason the delay before an engine
 * move is bearable at all: eighteen seconds of nothing is a hang, eighteen
 * seconds of a crab with a claw under its chin is a hard position. It leaves
 * `breath` alone so the automatic layer keeps him alive underneath, and every
 * track closes on the value it opened with so it can run for as long as the
 * server takes without a seam.
 */
export const chinRest = defineMotion({
  id: 'chinRest',
  duration: 5.4,
  loop: true,
  priority: 6,
  fadeIn: 0.4,
  fadeOut: 0.4,
  tracks: [
    {
      param: 'clawR',
      keys: [
        { t: 0, v: 72 },
        { t: 0.46, v: 78, ease: 'inOut' },
        { t: 1, v: 72, ease: 'inOut' },
      ],
    },
    // The other claw is out of it entirely, resting on the table edge.
    {
      param: 'clawL',
      keys: [
        { t: 0, v: 10 },
        { t: 0.52, v: 4, ease: 'inOut' },
        { t: 1, v: 10, ease: 'inOut' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 3.2 },
        { t: 0.38, v: 4.4, ease: 'inOut' },
        { t: 0.74, v: 2.8, ease: 'inOut' },
        { t: 1, v: 3.2, ease: 'inOut' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: SEAT_Y - 0.2 },
        { t: 0.5, v: SEAT_Y - 0.05, ease: 'inOut' },
        { t: 1, v: SEAT_Y - 0.2, ease: 'inOut' },
      ],
    },
    {
      param: 'eyeOpenL',
      keys: [
        { t: 0, v: 0.62 },
        { t: 0.44, v: 0.54, ease: 'inOut' },
        { t: 1, v: 0.62, ease: 'inOut' },
      ],
    },
    {
      param: 'eyeOpenR',
      keys: [
        { t: 0, v: 0.6 },
        { t: 0.44, v: 0.52, ease: 'inOut' },
        { t: 1, v: 0.6, ease: 'inOut' },
      ],
    },
    { param: 'scaleY', keys: [{ t: 0, v: SEAT_SY }] },
    { param: 'scaleX', keys: [{ t: 0, v: SEAT_SX }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

// ── committing ────────────────────────────────────────────────────────

/**
 * The move goes down.
 *
 * Anticipate, place, settle — and a beat of stillness with the claw still on
 * the piece before it comes away, because letting go is the part of a move
 * that a human hesitates over.
 */
export const placePiece = defineMotion({
  id: 'placePiece',
  duration: 0.98,
  priority: 7,
  fadeIn: 0.14,
  fadeOut: 0.26,
  tracks: [
    {
      param: 'clawR',
      keys: [
        { t: 0, v: REST_R },
        { t: 0.14, v: 58, ease: 'in' }, // anticipation, up and back
        { t: 0.44, v: -30, ease: 'outCubic' }, // down onto the square
        { t: 0.58, v: -32 }, // and holds it there
        { t: 0.82, v: 32, ease: 'inCubic' }, // lets go, lifts away
        { t: 1, v: REST_R, ease: 'inOut' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: REST_L },
        { t: 0.5, v: 24, ease: 'inOut' },
        { t: 1, v: REST_L, ease: 'inOut' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 1.6 },
        { t: 0.14, v: -0.6, ease: 'inOut' },
        { t: 0.46, v: 5.4, ease: 'outCubic' },
        { t: 0.74, v: 2.6, ease: 'inOut' },
        { t: 1, v: 1.6, ease: 'inOut' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: SEAT_Y },
        { t: 0.46, v: SEAT_Y - 0.5, ease: 'outCubic' },
        { t: 0.74, v: SEAT_Y + 0.15, ease: 'inCubic' },
        { t: 1, v: SEAT_Y, ease: 'inOut' },
      ],
    },
    {
      param: 'posX',
      keys: [
        { t: 0, v: 0 },
        { t: 0.46, v: 0.9, ease: 'outCubic' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    // The smallest amount of pleased, once the piece is down and not before.
    {
      param: 'eyeSmile',
      keys: [
        { t: 0, v: 0 },
        { t: 0.84, v: 0.28, ease: 'out' },
        { t: 1, v: 0.16, ease: 'inOut' },
      ],
    },
    { param: 'scaleY', keys: [{ t: 0, v: SEAT_SY }] },
    { param: 'scaleX', keys: [{ t: 0, v: SEAT_SX }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/**
 * A capture. The same move, done greedily.
 *
 * A third quicker than `placePiece`, with the whole body going after it and
 * the taken piece yanked clear of the board rather than set aside — the point
 * of a separate clip is that you should be able to tell a capture happened
 * without looking at the squares.
 */
export const snatchCapture = defineMotion({
  id: 'snatchCapture',
  duration: 0.64,
  priority: 8,
  fadeIn: 0.09,
  fadeOut: 0.22,
  tracks: [
    {
      param: 'clawR',
      keys: [
        { t: 0, v: REST_R },
        { t: 0.1, v: 64, ease: 'in' },
        { t: 0.32, v: -34, ease: 'outCubic' }, // straight down onto it
        { t: 0.42, v: -36 },
        { t: 0.64, v: 88, ease: 'inCubic' }, // and off the board with it
        { t: 0.84, v: 52, ease: 'inOut' },
        { t: 1, v: REST_R, ease: 'inOut' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: REST_L },
        { t: 0.34, v: 18, ease: 'outCubic' },
        { t: 1, v: REST_L, ease: 'inOut' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 1.6 },
        { t: 0.1, v: -1.6, ease: 'in' },
        { t: 0.34, v: 7.2, ease: 'outCubic' },
        { t: 0.68, v: -1, ease: 'inCubic' }, // back with the prize
        { t: 1, v: 1.6, ease: 'inOut' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: SEAT_Y },
        { t: 0.34, v: SEAT_Y - 0.7, ease: 'outCubic' },
        { t: 0.68, v: SEAT_Y + 0.3, ease: 'inCubic' },
        { t: 1, v: SEAT_Y, ease: 'inOut' },
      ],
    },
    {
      param: 'posX',
      keys: [
        { t: 0, v: 0 },
        { t: 0.34, v: 1.4, ease: 'outCubic' },
        { t: 0.7, v: -0.5, ease: 'inCubic' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: SEAT_SY },
        { t: 0.34, v: 0.8, ease: 'outCubic' },
        { t: 0.68, v: 0.87, ease: 'inCubic' },
        { t: 1, v: SEAT_SY, ease: 'inOut' },
      ],
    },
    {
      param: 'scaleX',
      keys: [
        { t: 0, v: SEAT_SX },
        { t: 0.34, v: 1.16, ease: 'outCubic' },
        { t: 0.68, v: 1.06, ease: 'inCubic' },
        { t: 1, v: SEAT_SX, ease: 'inOut' },
      ],
    },
    // Held wide through the grab; a blink in the middle of this would read as
    // squeamishness, which is the opposite of the beat.
    { param: 'eyeOpenL', keys: [{ t: 0, v: 1 }] },
    { param: 'eyeOpenR', keys: [{ t: 0, v: 1 }] },
    {
      param: 'eyeSmile',
      keys: [
        { t: 0, v: 0 },
        { t: 0.72, v: 0.55, ease: 'out' },
        { t: 1, v: 0.3, ease: 'inOut' },
      ],
    },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

// ── attitude ──────────────────────────────────────────────────────────

/** Check. He leans in to watch you notice, half-lidded and delighted. */
export const leanCheck = defineMotion({
  id: 'leanCheck',
  duration: 1.15,
  priority: 7,
  fadeIn: 0.18,
  fadeOut: 0.3,
  tracks: [
    {
      param: 'angle',
      keys: [
        { t: 0, v: 1.6 },
        { t: 0.12, v: -0.8, ease: 'inOut' }, // pulls back before leaning in
        { t: 0.44, v: 8.2, ease: 'outCubic' },
        { t: 0.76, v: 7, ease: 'inOut' },
        { t: 1, v: 1.6, ease: 'inOut' },
      ],
    },
    {
      param: 'posY',
      keys: [
        { t: 0, v: SEAT_Y },
        { t: 0.44, v: SEAT_Y - 0.9, ease: 'outCubic' },
        { t: 0.76, v: SEAT_Y - 0.7, ease: 'inOut' },
        { t: 1, v: SEAT_Y, ease: 'inOut' },
      ],
    },
    {
      param: 'posX',
      keys: [
        { t: 0, v: 0 },
        { t: 0.46, v: 0.8, ease: 'outCubic' },
        { t: 1, v: 0, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: REST_R },
        { t: 0.42, v: 68, ease: 'outCubic' }, // a claw raised at your king
        { t: 0.62, v: 58, ease: 'inOut' },
        { t: 1, v: REST_R, ease: 'inOut' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: REST_L },
        { t: 0.5, v: 28, ease: 'inOut' },
        { t: 1, v: REST_L, ease: 'inOut' },
      ],
    },
    {
      param: 'eyeOpenL',
      keys: [
        { t: 0, v: 1 },
        { t: 0.44, v: 0.55, ease: 'inOut' },
        { t: 0.8, v: 0.55 },
        { t: 1, v: 1, ease: 'out' },
      ],
    },
    {
      param: 'eyeOpenR',
      keys: [
        { t: 0, v: 1 },
        { t: 0.44, v: 0.52, ease: 'inOut' },
        { t: 0.8, v: 0.52 },
        { t: 1, v: 1, ease: 'out' },
      ],
    },
    {
      param: 'eyeSmile',
      keys: [
        { t: 0, v: 0 },
        { t: 0.46, v: 0.75, ease: 'out' },
        { t: 0.8, v: 0.85, ease: 'inOut' },
        { t: 1, v: 0.35, ease: 'inOut' },
      ],
    },
    { param: 'scaleY', keys: [{ t: 0, v: SEAT_SY }] },
    { param: 'scaleX', keys: [{ t: 0, v: SEAT_SX }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

/**
 * The moment he realises.
 *
 * Different from `slumpLoss` in the only way that matters: it opens with a
 * quarter-second of nothing at all. He has already moved, the position is
 * already lost, and the stillness before the fold is the beat where he is
 * still looking at what he did. Ends held — the choreographer keeps him there
 * until the next thing happens, and there usually is no next thing.
 *
 * The fold is deliberately shallower than `slumpLoss`'s. The board is painted
 * over him and its far rim sits at stage y 67.3; a full slump takes his eyes
 * to about 67.6 and puts the reaction behind the furniture. Holding the pose
 * a unit higher keeps his face on screen, which for a beat that exists only
 * to be watched is not a compromise but the requirement.
 */
export const slumpBlunder = defineMotion({
  id: 'slumpBlunder',
  duration: 1.5,
  priority: 8,
  fadeIn: 0.12,
  fadeOut: 0.45,
  tracks: [
    {
      param: 'posY',
      keys: [
        { t: 0, v: SEAT_Y },
        { t: 0.22, v: SEAT_Y }, // the stare
        { t: 0.36, v: SEAT_Y - 0.35, ease: 'outCubic' }, // a sharp small recoil
        { t: 0.88, v: SEAT_Y + 1.15, ease: 'inCubic' },
        { t: 1, v: SEAT_Y + 1, ease: 'inOut' },
      ],
    },
    {
      param: 'angle',
      keys: [
        { t: 0, v: 1.6 },
        { t: 0.22, v: 1.6 },
        { t: 0.38, v: -3.4, ease: 'outCubic' },
        { t: 0.9, v: 7.4, ease: 'inCubic' },
        { t: 1, v: 6.8, ease: 'inOut' },
      ],
    },
    {
      param: 'clawL',
      keys: [
        { t: 0, v: REST_L },
        { t: 0.22, v: REST_L },
        { t: 0.4, v: 60, ease: 'outCubic' },
        { t: 0.92, v: -34, ease: 'inCubic' },
        { t: 1, v: -30, ease: 'inOut' },
      ],
    },
    {
      param: 'clawR',
      keys: [
        { t: 0, v: REST_R },
        { t: 0.22, v: REST_R },
        { t: 0.4, v: 62, ease: 'outCubic' },
        { t: 0.92, v: -32, ease: 'inCubic' },
        { t: 1, v: -28, ease: 'inOut' },
      ],
    },
    {
      param: 'scaleY',
      keys: [
        { t: 0, v: SEAT_SY },
        { t: 0.22, v: SEAT_SY },
        { t: 0.38, v: 0.87, ease: 'outCubic' }, // the inhale
        { t: 0.92, v: 0.76, ease: 'inCubic' },
        { t: 1, v: 0.76 },
      ],
    },
    {
      param: 'scaleX',
      keys: [
        { t: 0, v: SEAT_SX },
        { t: 0.22, v: SEAT_SX },
        { t: 0.38, v: 1.06, ease: 'outCubic' },
        { t: 0.92, v: 1.17, ease: 'inCubic' },
        { t: 1, v: 1.17 },
      ],
    },
    // Wide for the realisation, then down. Owning the eyes for the whole clip
    // keeps the blinker from firing on the stare, which would soften it.
    {
      param: 'eyeOpenL',
      keys: [
        { t: 0, v: 1 },
        { t: 0.52, v: 1 },
        { t: 0.92, v: 0.36, ease: 'inOut' },
        { t: 1, v: 0.36 },
      ],
    },
    {
      param: 'eyeOpenR',
      keys: [
        { t: 0, v: 1 },
        { t: 0.52, v: 1 },
        { t: 0.92, v: 0.34, ease: 'inOut' },
        { t: 1, v: 0.34 },
      ],
    },
    {
      param: 'eyeY',
      keys: [
        { t: 0, v: 0.2 },
        { t: 0.38, v: 0.35, ease: 'inOut' },
        { t: 0.92, v: 0.8, ease: 'inOut' },
        { t: 1, v: 0.78 },
      ],
    },
    // And whatever he was pleased about a moment ago is gone.
    { param: 'eyeSmile', keys: [{ t: 0, v: 0 }] },
    { param: 'legSwing', keys: [{ t: 0, v: 0 }] },
  ],
})

export const CHESS_MOTIONS = {
  reachHover,
  pullBack,
  chinRest,
  placePiece,
  snatchCapture,
  leanCheck,
  slumpBlunder,
}

/**
 * Everything here except the thinking loop must be allowed to finish.
 *
 * `chinRest` is deliberately absent: it loops, and a loop that the director
 * treated as a one-shot would never report itself finished and would hold the
 * body for the rest of the game.
 */
export const CHESS_ONE_SHOTS = [
  'reachHover',
  'pullBack',
  'placePiece',
  'snatchCapture',
  'leanCheck',
  'slumpBlunder',
] as const
