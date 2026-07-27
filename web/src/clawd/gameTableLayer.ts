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
 * places that happen to look close.
 */

import { ROOM } from './palette'
import { contactShadow, FLOOR_Y, rect, STAGE } from './stage'

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

type Ctx = CanvasRenderingContext2D

/**
 * Draw the table.
 *
 * `presence` fades and slides it in as he arrives, so it does not simply
 * appear in a room he is still walking across.
 */
export function drawGameTable(ctx: Ctx, u: number, presence: number, time: number) {
  if (presence <= 0.002) return
  const t = GAME_TABLE
  const left = t.x - t.w / 2

  ctx.save()
  ctx.globalAlpha = Math.min(1, presence)
  // Rises into place rather than fading on the spot.
  ctx.translate(0, (1 - presence) * 3.2 * u)

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

  // Where the two piles live. Faint, so they read as felt worn by use rather
  // than as a diagram printed on the table.
  ctx.globalAlpha = 0.16 * presence
  for (const sx of [t.deckX, t.discardX]) {
    rect(ctx, u, sx - GAME_CARD.w / 2 - 0.4, t.topY + 0.25, GAME_CARD.w + 0.8, 0.9, '#000000')
  }

  // A slow warm wash over the middle, so the table is lit rather than lying
  // in the same light as the floor around it.
  ctx.globalAlpha = (0.06 + Math.sin(time * 0.5) * 0.008) * presence
  rect(ctx, u, left + 4, t.topY, t.w - 8, 0.45, ROOM.lamp)

  ctx.restore()
}
