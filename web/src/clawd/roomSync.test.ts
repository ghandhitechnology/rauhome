import { beforeEach, describe, expect, it } from 'vitest'

import * as classic from './roomClassic'
import * as enhanced from './room'
import { PROP_SPOTS, propStore } from './props'
import { panelStore } from '../panels'
import { resetBackdrop } from './backdrop'
import type { RoomState } from './room'

/**
 * A canvas that records what was asked of it.
 *
 * Enough of the 2D API for both rooms to draw a whole frame. Fills are kept in
 * stage units so a test can ask "was something painted where the shelf is"
 * without knowing anything about the renderer.
 */
function recordingCtx(unit: number) {
  const fills: { x: number; y: number; w: number; h: number }[] = []
  const gradient = { addColorStop: () => {} }
  const ctx = {
    canvas: { width: 1600, height: 900 },
    fillStyle: '' as unknown,
    strokeStyle: '' as unknown,
    lineWidth: 0,
    lineCap: '',
    globalAlpha: 1,
    globalCompositeOperation: '',
    filter: '',
    font: '',
    textBaseline: '',
    fillRect: (x: number, y: number, w: number, h: number) =>
      fills.push({ x: x / unit, y: y / unit, w: w / unit, h: h / unit }),
    clearRect: () => {},
    strokeRect: () => {},
    fillText: () => {},
    measureText: () => ({ width: 10 }),
    save: () => {},
    restore: () => {},
    translate: () => {},
    rotate: () => {},
    scale: () => {},
    setTransform: () => {},
    beginPath: () => {},
    closePath: () => {},
    moveTo: () => {},
    lineTo: () => {},
    bezierCurveTo: () => {},
    ellipse: () => {},
    arc: () => {},
    rect: () => {},
    fill: () => {},
    stroke: () => {},
    clip: () => {},
    drawImage: () => {},
    createLinearGradient: () => gradient,
    createRadialGradient: () => gradient,
    createPattern: () => null,
    getImageData: () => ({ data: new Uint8ClampedArray(4) }),
    putImageData: () => {},
    createImageData: () => ({ data: new Uint8ClampedArray(4) }),
  }
  return { ctx: ctx as unknown as CanvasRenderingContext2D, fills }
}

const STATE: RoomState = { hour: 13, lamp: 0, screen: 0.3, time: 4 }
const UNIT = 10

/** Was anything painted inside this stage-unit box? */
function paintedNear(
  fills: { x: number; y: number; w: number; h: number }[],
  x: number,
  y: number,
  pad = 5,
): boolean {
  return fills.some(
    (f) =>
      f.w > 0.2 &&
      f.h > 0.2 &&
      f.x > x - pad &&
      f.x < x + pad &&
      f.y > y - pad * 1.2 &&
      f.y < y + pad * 1.2,
  )
}

function render(room: { drawRoomBack: typeof enhanced.drawRoomBack }) {
  // No document in this environment, so the backdrop cache stands aside and
  // the painter runs straight onto the recording context.
  resetBackdrop()
  const { ctx, fills } = recordingCtx(UNIT)
  room.drawRoomBack(ctx, UNIT, STATE)
  return fills
}

describe('the two rooms show the same room', () => {
  beforeEach(() => {
    resetBackdrop()
    panelStore.clear()
    propStore.setLayout({
      mug: 'desk',
      books: 'floor_left',
      box: 'floor_far_left',
      plant: 'floor_mid',
    })
  })

  it('both draw the mug on the desk to start with', () => {
    const spot = PROP_SPOTS.desk
    for (const [name, room] of [
      ['enhanced', enhanced],
      ['classic', classic],
    ] as const) {
      expect(paintedNear(render(room), spot.x, spot.y), name).toBe(true)
    }
  })

  it('both follow the mug to the shelf', () => {
    propStore.setLayout({ mug: 'shelf' })
    const shelf = PROP_SPOTS.shelf
    for (const [name, room] of [
      ['enhanced', enhanced],
      ['classic', classic],
    ] as const) {
      const fills = render(room)
      expect(paintedNear(fills, shelf.x, shelf.y, 4), `${name} shelf`).toBe(true)
    }
  })

  it('neither leaves a second copy behind on the old surface', () => {
    // The classic room used to draw its own mug, bolted to the desk, so an
    // errand produced two mugs: one that moved and one that never did.
    const desk = PROP_SPOTS.desk
    const count = (fills: ReturnType<typeof render>) =>
      fills.filter((f) => f.w < 5 && paintedNear([f], desk.x + 1.5, desk.y - 1.5, 3)).length

    for (const [name, room] of [
      ['enhanced', enhanced],
      ['classic', classic],
    ] as const) {
      propStore.setLayout({ mug: 'desk' })
      const before = count(render(room))
      propStore.setLayout({ mug: 'shelf' })
      const after = count(render(room))
      expect(before, `${name} should draw a mug on the desk`).toBeGreaterThan(0)
      expect(after, `${name} left a mug behind`).toBeLessThan(before)
    }
  })

  it('both hang the panels Rau makes', () => {
    // The newest panel takes the poster's hook, so the count of fills can fall
    // even as a panel appears — assert on the place, not the tally.
    panelStore.add({ panel_id: 'p1', title: 'This week', kind: 'dashboard', created: 1 })
    for (const [name, room] of [
      ['enhanced', enhanced],
      ['classic', classic],
    ] as const) {
      // Slot 0 is the poster hook at stage (76, 12), 15 x 21.
      expect(paintedNear(render(room), 83, 22, 6), `${name} panel`).toBe(true)
    }
  })

  it('both put every object somewhere, wherever it has been moved', () => {
    for (const spot of ['desk', 'shelf', 'sill', 'rug', 'floor_right'] as const) {
      propStore.setLayout({ mug: spot })
      const at = PROP_SPOTS[spot]
      for (const [name, room] of [
        ['enhanced', enhanced],
        ['classic', classic],
      ] as const) {
        expect(paintedNear(render(room), at.x, at.y, 4), `${name} @ ${spot}`).toBe(true)
      }
    }
  })
})
