import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  bakeBackdrop,
  bakeForeground,
  blitBackdrop,
  resetBackdrop,
  ROOM_H,
  ROOM_LEFT,
  ROOM_TOP,
  ROOM_W,
  unitKey,
} from './backdrop'

/**
 * The cache is only reachable where there is a document, so stand one up.
 *
 * Only what `Layer.paint` touches: a canvas that remembers its size and hands
 * back a context that records nothing. What is under test is *when* the painter
 * runs, not what it draws.
 */
const made: { width: number; height: number }[] = []
function fakeDocument() {
  return {
    createElement: () => {
      const canvas = {
        width: 0,
        height: 0,
        getContext: () => ({
          setTransform: () => {},
          clearRect: () => {},
          translate: () => {},
        }),
      }
      made.push(canvas as unknown as { width: number; height: number })
      return canvas
    },
  }
}

const original = (globalThis as { document?: unknown }).document
;(globalThis as { document?: unknown }).document = fakeDocument()
afterAll(() => {
  ;(globalThis as { document?: unknown }).document = original
})

describe('the backdrop cache', () => {
  beforeEach(() => {
    resetBackdrop()
    made.length = 0
  })

  it('paints once and hands back the same bitmap after that', () => {
    const paint = vi.fn()
    const first = bakeBackdrop(10, 'k', paint)
    const second = bakeBackdrop(10, 'k', paint)
    expect(paint).toHaveBeenCalledTimes(1)
    expect(second).toBe(first)
  })

  it('repaints when anything named in the key changes', () => {
    const paint = vi.fn()
    bakeBackdrop(10, 'enhanced|10.00|high|60|mug:desk|', paint)
    // Someone carried the mug to the shelf.
    bakeBackdrop(10, 'enhanced|10.00|high|60|mug:shelf|', paint)
    // The hour turned.
    bakeBackdrop(10, 'enhanced|10.00|high|61|mug:shelf|', paint)
    // The machine was told to work less hard.
    bakeBackdrop(10, 'enhanced|10.00|low|61|mug:shelf|', paint)
    expect(paint).toHaveBeenCalledTimes(4)
  })

  it('reuses the one canvas rather than leaking a bitmap per repaint', () => {
    for (let i = 0; i < 5; i++) bakeBackdrop(10, `k${i}`, () => {})
    expect(made.length).toBe(1)
  })

  it('sizes the bitmap to the zoom and resizes on the way through', () => {
    bakeBackdrop(10, 'a', () => {})
    const at10 = { w: made[0].width, h: made[0].height }
    bakeBackdrop(20, 'b', () => {})
    expect(made[0].width).toBeCloseTo(at10.w * 2, -1)
    expect(made[0].height).toBeCloseTo(at10.h * 2, -1)
  })

  it('stands aside rather than allocating an absurd bitmap', () => {
    const paint = vi.fn()
    // A zoom this high would ask for hundreds of millions of pixels; the cache
    // declines and the caller draws straight to the screen instead.
    expect(bakeBackdrop(4000, 'huge', paint)).toBeNull()
    expect(paint).not.toHaveBeenCalled()
  })

  it('keeps the two layers apart', () => {
    const back = bakeBackdrop(10, 'same-key', () => {})
    const fore = bakeForeground(10, 'same-key', () => {})
    expect(fore).not.toBe(back)
  })

  it('quantises the zoom so a one-pixel drag is not a repaint', () => {
    expect(unitKey(12.01)).toBe(unitKey(12.04))
    expect(unitKey(12.0)).not.toBe(unitKey(12.3))
  })

  it('places the layer by the room it covers, not by its pixel size', () => {
    // The key quantises the zoom, so a resize inside the same bucket reuses a
    // bitmap baked at a different scale. Blitting that at natural size slides
    // the whole backdrop out of register with the live geometry drawn over it
    // — the clock hands leave the dial, the monitor leaves the desk.
    const drawn: number[][] = []
    const ctx = { drawImage: (_c: unknown, ...args: number[]) => drawn.push(args) }
    const canvas = bakeBackdrop(10, 'k', () => {})!
    blitBackdrop(ctx as unknown as CanvasRenderingContext2D, 10.05, canvas)

    expect(drawn[0], 'must give drawImage a destination rect').toHaveLength(4)
    expect(drawn[0]).toEqual([
      ROOM_LEFT * 10.05,
      ROOM_TOP * 10.05,
      ROOM_W * 10.05,
      ROOM_H * 10.05,
    ])
  })

  it('rasterises at device resolution, so the bake is not the soft half', () => {
    // The real canvas is sized width*dpr with a dpr transform, so a layer
    // rasterised at CSS scale is upsampled on any retina display: a soft
    // backdrop behind a crisp character.
    bakeBackdrop(10, 'one-x', () => {}, 1)
    const at1 = made[0].width
    bakeBackdrop(10, 'two-x', () => {}, 2)
    expect(made[0].width).toBe(at1 * 2)
  })

  it('hands the painter the scale it is actually painting at', () => {
    let seen = 0
    bakeBackdrop(10, 'scale', (_ctx, u) => {
      seen = u
    }, 2)
    expect(seen).toBe(20)
  })

  it('re-rasterises when the window moves to a different pixel density', () => {
    expect(unitKey(12)).toBe(unitKey(12))
    // The ratio rides in the key, so the same zoom on a new display repaints.
    expect(unitKey(12)).toContain('@')
  })
})
