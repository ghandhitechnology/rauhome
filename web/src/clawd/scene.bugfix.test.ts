import { describe, expect, it } from 'vitest'

import { drawBubble } from './scene'

/**
 * A 2x display: the bitmap is 2000 device pixels wide, which is 1000 CSS
 * pixels — the space every coordinate handed to drawBubble lives in.
 */
function fakeCtx(cssCharWidth = 10) {
  return {
    canvas: { width: 2000, height: 1200 },
    font: '',
    textBaseline: '',
    save: () => {},
    restore: () => {},
    getTransform: () => ({ a: 2 }),
    measureText: (t: string) => ({ width: t.length * cssCharWidth }),
    fillRect: () => {},
    fillText: () => {},
  } as unknown as CanvasRenderingContext2D
}

describe('drawBubble on a hidpi canvas', () => {
  it('keeps the bubble inside the CSS-pixel viewport', () => {
    const ctx = fakeCtx()
    // Anchored at the right edge of the visible area.
    const bubble = drawBubble(ctx, 'hello', 990, 500, 400, 1)
    expect(bubble).not.toBeNull()
    expect(bubble!.x + bubble!.w).toBeLessThanOrEqual(1000 - 12 + 1e-6)
  })
})
