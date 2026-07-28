/**
 * The card table.
 *
 * A prop rather than a fixture: it exists only while a game does, so it is
 * drawn live each frame with a presence value instead of being baked into the
 * backdrop the way the desk and the shelf are.
 *
 * This module is also where both halves of the game agree about geometry. The
 * canvas draws the table from these numbers and the DOM cards are positioned
 * from the same ones, so "the deck" is one place in the room and not two
 * places that happen to look close. `KITTENS_SURFACE` is that agreement made
 * explicit — the piles are named on the surface, and `gameBridge` hands both
 * halves the same projected rect.
 *
 * The carcass — legs, apron, slab, the wash of lamplight over the middle — is
 * exported on its own, because chess sits at this same table. Two tables that
 * looked *almost* the same would be worse than either: the camera, the seat
 * and the walk are all tuned against these numbers, and a second set of them
 * would drift out of agreement the first time anyone touched one.
 */

import type { TableGame } from './gameChoreographer'
import { ROOM } from './palette'
import { gameBridge } from './gameBridge'
import { contactShadow, FLOOR_Y, rect, STAGE } from './stage'
import type { TableSurface } from './tableSurface'

/**
 * Table geometry, in stage units.
 *
 * `x` matches the `table` station so he sits centred behind it. The deck and
 * discard sit outside his silhouette — he is about 19 units wide seated —
 * so neither pile is ever hidden behind him.
 */
export const GAME_TABLE = {
  x: 72,
  /** Top surface. Just below the underside of his shell when seated. */
  topY: 70,
  /** Total depth of the top slab and the apron under it. */
  h: 5,
  w: 40,
  deckX: 57,
  discardX: 87,
  /** Top edge of a card resting on the surface. */
  cardY: 67,
}

/** A card lying on the table, in stage units. Aspect matches the art. */
export const GAME_CARD = { w: 4.3, h: 6.02 }

/** Where the "you saw" peek cards sit — floating above the deck. */
export const KNOWN_TOP_SPOT = { x: GAME_TABLE.deckX, y: 58.5 }

/**
 * The over-the-shoulder shot.
 *
 * Derived rather than guessed: the camera scales about the middle of the
 * stage, so `x` is just how far the table is off centre. At this zoom the
 * visible band is about 41 units tall, which puts his head a third of the way
 * down, the table across the middle, and leaves the bottom of the frame empty
 * for the hand you are holding.
 */
export const GAME_CAMERA = {
  x: GAME_TABLE.x - STAGE.w / 2,
  y: 24,
  zoom: 2.2,
  lambda: 2.4,
}

/** How dark the room goes outside the light over the table. */
export const GAME_DIM = 0.62

/** How far the table starts below its resting place as it arrives. */
export const TABLE_RISE = 3.2

type Ctx = CanvasRenderingContext2D

/**
 * Legs, apron, slab, and the shadow that keeps it on the floor.
 *
 * Everything that is the *furniture* rather than the game being played on it.
 * Expects the caller to have already set the alpha and the arrival offset, so
 * that whatever is laid out on top rises with it as one object.
 */
export function drawTableCarcass(ctx: Ctx, u: number, presence: number) {
  const t = GAME_TABLE
  const left = t.x - t.w / 2

  // Something this size has to sit on the floor, not hover over it.
  contactShadow(ctx, u, t.x, FLOOR_Y + 6.6, t.w * 0.52, 1.5, 0.46 * presence)

  // Legs first: they belong behind the apron that hides their tops.
  for (const lx of [left + 3, t.x + t.w / 2 - 4.2]) {
    rect(ctx, u, lx, t.topY + t.h - 0.4, 1.2, 3.4, ROOM.woodDeep)
    rect(ctx, u, lx, t.topY + t.h - 0.4, 0.4, 3.4, ROOM.woodShade)
  }

  // Apron under the top, then the top slab with a lit front edge. Four tones
  // rather than one flat fill, the same way every other surface in the room
  // is built — and a dark seam between the slab and the apron, without which
  // the whole thing reads as a shelf on the wall behind him.
  rect(ctx, u, left + 1.2, t.topY + 1.7, t.w - 2.4, t.h - 1.7, ROOM.walnut)
  rect(ctx, u, left + 1.2, t.topY + 1.7, t.w - 2.4, 0.5, ROOM.woodDeep)
  rect(ctx, u, left, t.topY, t.w, 1.7, ROOM.wood)
  rect(ctx, u, left, t.topY, t.w, 0.5, ROOM.woodLit)
  rect(ctx, u, left, t.topY + 1.35, t.w, 0.35, ROOM.woodDeep)
}

/**
 * A slow warm wash over the middle.
 *
 * So the table is lit rather than lying in the same light as the floor
 * around it. Breathes, at a rate you would not consciously notice.
 */
export function drawTableGlow(ctx: Ctx, u: number, presence: number, time: number) {
  const t = GAME_TABLE
  const left = t.x - t.w / 2
  ctx.globalAlpha = (0.06 + Math.sin(time * 0.5) * 0.008) * presence
  rect(ctx, u, left + 4, t.topY, t.w - 8, 0.45, ROOM.lamp)
}

/**
 * Draw the table with the two card piles marked on it.
 *
 * `presence` fades and slides it in as he arrives, so it does not simply
 * appear in a room he is still walking across.
 */
export function drawKittensTable(ctx: Ctx, u: number, presence: number, time: number) {
  if (presence <= 0.002) return
  const t = GAME_TABLE

  ctx.save()
  ctx.globalAlpha = Math.min(1, presence)
  // Rises into place rather than fading on the spot.
  ctx.translate(0, (1 - presence) * TABLE_RISE * u)

  drawTableCarcass(ctx, u, presence)

  // Where the two piles live. Faint, so they read as felt worn by use rather
  // than as a diagram printed on the table.
  ctx.globalAlpha = 0.16 * presence
  for (const sx of [t.deckX, t.discardX]) {
    rect(ctx, u, sx - GAME_CARD.w / 2 - 0.4, t.topY + 0.25, GAME_CARD.w + 0.8, 0.9, '#000000')
  }

  drawTableGlow(ctx, u, presence, time)

  ctx.restore()
}

/** A pile of cards lying on the surface, in stage units. */
function pile(cx: number) {
  return { x: cx - GAME_CARD.w / 2, y: GAME_TABLE.cardY, w: GAME_CARD.w, h: GAME_CARD.h }
}

export const KITTENS_SURFACE: TableSurface = {
  id: 'kittens',
  table: GAME_TABLE,
  camera: GAME_CAMERA,
  dim: GAME_DIM,
  spots: {
    deck: pile(GAME_TABLE.deckX),
    discard: pile(GAME_TABLE.discardX),
  },
  draw: drawKittensTable,
}

/** What each beat of a hand does to his body. */
export const KITTENS_GAME: TableGame = {
  surface: KITTENS_SURFACE,
  verbClips: {
    draw: 'reachDraw',
    play: 'flickPlay',
    nope: 'slamNope',
    kitten: 'kittenRecoil',
    defuse: 'defuseRelief',
    attack: 'smugLean',
    cheer: 'sitCheer',
    slump: 'slumpLoss',
  },
  /** Beats that wipe whatever was queued: nothing outranks the kitten. */
  interrupting: new Set(['kitten', 'cheer', 'slump']),
  /** Beats whose last frame is the point, and so must not be tidied away. */
  terminal: new Set(['cheer', 'slump']),
}

/**
 * The table that was up the last time there was one.
 *
 * The surface is handed back the moment a game ends, but the table it belonged
 * to is still on screen and still fading — and on an aborted start, or a leave
 * taken mid-walk, it is handed back while presence is still most of the way up.
 * So the last frames of a dismissal have a presence and no surface, and
 * something has to be painted for them.
 *
 * It has to be the table that was actually there. Defaulting to the card table
 * meant a chess dismissal spent its fade painting a card table over the board
 * the user was just looking at — invisible at the tail of a normal fade, which
 * is why it read as safe, and a hard flash of the wrong furniture at the eight
 * tenths of presence an aborted start hands back at.
 */
let lastSurface: TableSurface | null = null

/**
 * Paint whichever table is currently up.
 *
 * The scene draws the room and has no business knowing which game is being
 * played on it; the bridge already holds the answer, because the game had to
 * tell it in order to get anything positioned.
 */
export function drawGameTable(ctx: Ctx, u: number, presence: number, time: number) {
  const surface = gameBridge.surface ?? lastSurface
  if (!surface) return
  lastSurface = surface
  surface.draw(ctx, u, presence, time)
}
