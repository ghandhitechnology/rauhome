import { afterAll, beforeEach, describe, expect, it } from 'vitest'

import { resetBackdrop } from './backdrop'
import { drawRoomFore } from './roomClassic'

/**
 * The blur behind the classic room's foreground is the expensive kind of draw
 * — `ctx.filter` forces its own compositing pass — so it is paid once, into
 * the bake, and frames after that are one blit. The cache only exists where
 * there is a document, so stand one up the way backdrop.test.ts does.
 */
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
          save: () => {},
          restore: () => {},
          fillRect: () => {},
          globalAlpha: 1,
          globalCompositeOperation: 'source-over',
          filter: 'none',
          fillStyle: '',
        }),
      }
      return canvas
    },
  }
}

const original = (globalThis as { document?: unknown }).document
;(globalThis as { document?: unknown }).document = fakeDocument()
afterAll(() => {
  ;(globalThis as { document?: unknown }).document = original
})

describe('the classic foreground', () => {
  beforeEach(() => {
    resetBackdrop()
  })

  it('pays the blur once, into the bake, rather than per frame', () => {
    const ops: string[] = []
    const ctx = {
      save: () => {},
      restore: () => {},
      fillRect: () => ops.push('fillRect'),
      drawImage: () => ops.push('drawImage'),
      globalAlpha: 1,
      fillStyle: '',
      filter: 'none',
    } as unknown as CanvasRenderingContext2D

    drawRoomFore(ctx, 10)
    drawRoomFore(ctx, 10)
    // A live filter would show up as fillRects on every call; a working bake
    // is a blit and nothing else.
    expect(ops).toEqual(['drawImage', 'drawImage'])
  })

  it('still draws the chair directly where there is no cache', () => {
    const prev = (globalThis as { document?: unknown }).document
    ;(globalThis as { document?: unknown }).document = undefined
    const ops: string[] = []
    try {
      const ctx = {
        save: () => {},
        restore: () => {},
        fillRect: () => ops.push('fillRect'),
        drawImage: () => ops.push('drawImage'),
        globalAlpha: 1,
        fillStyle: '',
        filter: 'none',
      } as unknown as CanvasRenderingContext2D
      drawRoomFore(ctx, 10)
    } finally {
      ;(globalThis as { document?: unknown }).document = prev
    }
    expect(ops).toEqual(['fillRect', 'fillRect'])
  })
})
