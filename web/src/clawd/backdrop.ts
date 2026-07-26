/**
 * The backdrop cache.
 *
 * Most of a room does not change between frames. The wall, the panelling, the
 * floorboards and their nail heads, the radiator, the shelf — all of it was
 * being redrawn sixty times a second, and it accounted for the large majority
 * of the draw calls in the frame. The floor alone is around eight hundred
 * operations: fifty board fills, fifty joint strokes with a bevel each, and
 * some three hundred nail heads.
 *
 * So it is painted once into an offscreen canvas and blitted. The cost moves
 * from every frame to once per resize — which means the *detail* of the
 * backdrop stops being a performance decision at all, and the classic room can
 * afford the same architecture as the enhanced one.
 *
 * What must stay outside the bake is anything that moves: the sky as the hour
 * turns, the light shaft and its dust, the curtains, the plant, the screen, the
 * lamp. Those are cheap. It is the still life that was expensive.
 */

import { FLOOR_Y, STAGE } from './stage'

/** How far past the stage the room is painted, so a camera pan finds paint. */
export const BLEED = 26
export const ROOM_LEFT = -BLEED
export const ROOM_W = STAGE.w + BLEED * 2
/** Above the stage, so the ceiling line survives a downward pan. */
export const ROOM_TOP = -10
/**
 * Below the stage too. The out-of-focus foreground is drawn past the floor on
 * purpose, so the blur has material to work with rather than fading out; if
 * the layer stopped at the stage the blur would end in mid-air.
 */
export const ROOM_BOTTOM = STAGE.h + 6
export const ROOM_H = ROOM_BOTTOM - ROOM_TOP

void FLOOR_Y

/** Matches the ceiling `useClawdCanvas` puts on the real canvas. */
function pixelRatio(): number {
  if (typeof window === 'undefined') return 1
  return Math.min(window.devicePixelRatio || 1, 2)
}

type Ctx = CanvasRenderingContext2D

type Baked = {
  key: string
  canvas: HTMLCanvasElement
}

/**
 * The scale a layer is rasterised at.
 *
 * Deliberately not the unit the caller draws at. The bitmap always covers the
 * same rectangle of the room, and `blitBackdrop` maps that rectangle onto
 * whatever the live unit happens to be — so resolution and placement are
 * independent, and the quantised cache key cannot pull the baked room out of
 * register with the live one drawn over it.
 */
function bakeUnit(unit: number, ratio: number): number {
  return (Math.round(unit * 4) / 4) * ratio
}

/**
 * One cached layer. Two exist: the backdrop behind the character, and the
 * out-of-focus foreground in front of him.
 */
class Layer {
  private baked: Baked | null = null

  paint(
    unit: number,
    key: string,
    render: (ctx: Ctx, u: number) => void,
    ratio = 1,
  ): HTMLCanvasElement | null {
    if (typeof document === 'undefined') return null
    if (this.baked && this.baked.key === key) return this.baked.canvas

    const scale = bakeUnit(unit, ratio)
    const width = Math.max(1, Math.round(ROOM_W * scale))
    const height = Math.max(1, Math.round(ROOM_H * scale))
    // A very large window would ask for a very large bitmap; past this the
    // memory costs more than the redraw it saves.
    if (width * height > 40e6) return null

    const canvas = this.baked?.canvas ?? document.createElement('canvas')
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width
      canvas.height = height
    }
    const ctx = canvas.getContext('2d')
    if (!ctx) return null

    ctx.setTransform(1, 0, 0, 1, 0, 0)
    // A reused context keeps whatever state the last painter left; nothing
    // does today, but a bake is the wrong place to find that out.
    ctx.globalAlpha = 1
    ctx.globalCompositeOperation = 'source-over'
    ctx.filter = 'none'
    ctx.clearRect(0, 0, width, height)
    // The painter works in stage coordinates exactly as it would on the real
    // canvas; the offset lives here so nothing downstream has to know.
    ctx.translate(-ROOM_LEFT * scale, -ROOM_TOP * scale)
    render(ctx, scale)
    ctx.setTransform(1, 0, 0, 1, 0, 0)

    this.baked = { key, canvas }
    return canvas
  }

  reset(): void {
    this.baked = null
  }
}

const backLayer = new Layer()
const foreLayer = new Layer()

/**
 * Paint `render` once for this key and return the bitmap.
 *
 * `key` must name everything the painting depends on — the zoom, which room is
 * being drawn, the quality tier, the hour the sky was painted at, and any
 * state baked into it. Get that wrong and the room silently stops responding
 * to the thing you forgot.
 *
 * Returns null where there is no DOM (tests), so callers fall back to drawing
 * directly and nothing depends on the cache existing.
 */
export function bakeBackdrop(
  unit: number,
  key: string,
  render: (ctx: Ctx, u: number) => void,
  ratio = pixelRatio(),
): HTMLCanvasElement | null {
  return backLayer.paint(unit, key, render, ratio)
}

/** As `bakeBackdrop`, for the layer that sits in front of the character. */
export function bakeForeground(
  unit: number,
  key: string,
  render: (ctx: Ctx, u: number) => void,
  ratio = pixelRatio(),
): HTMLCanvasElement | null {
  return foreLayer.paint(unit, key, render, ratio)
}

/** Put a baked layer back over the room it was painted from. */
export function blitBackdrop(ctx: Ctx, unit: number, canvas: HTMLCanvasElement): void {
  // Onto the rectangle it covers, in the caller's units — never at natural
  // size. The bitmap's own scale is an internal detail: it is rasterised at
  // device resolution and at a quantised unit, so drawing it 1:1 would both
  // soften it on a high-DPI screen and slide it out of register with the live
  // geometry whenever a resize landed inside the same quantisation bucket.
  ctx.drawImage(
    canvas,
    ROOM_LEFT * unit,
    ROOM_TOP * unit,
    ROOM_W * unit,
    ROOM_H * unit,
  )
}

/** Drop both caches. A resize handles itself through the key; this is for tests. */
export function resetBackdrop(): void {
  backLayer.reset()
  foreLayer.reset()
}

/**
 * Quantised so a one-pixel drag does not repaint the whole room.
 *
 * Safe to quantise only because `blitBackdrop` places the bitmap by the room
 * rectangle rather than by its pixel size. The ratio is in here because moving
 * the window to a display with a different pixel density has to re-rasterise.
 */
export function unitKey(unit: number): string {
  return `${(Math.round(unit * 4) / 4).toFixed(2)}@${pixelRatio()}`
}
