import { beforeEach, describe, expect, it } from 'vitest'

import * as classic from './roomClassic'
import * as enhanced from './room'
import { PROP_SPOTS, propStore, propWidth, type SpotId } from './props'
import { restingPropsKey } from './propsLayer'
import { wallPanelsKey } from './panelsLayer'
import { panelStore } from '../panels'
import { resetBackdrop } from './backdrop'
import type { RoomState } from './room'

/**
 * A canvas that records what was asked of it.
 *
 * Enough of the 2D API for both rooms to draw a whole frame. Fills are kept in
 * stage units, with their colour, so one frame can be subtracted from another.
 */
type Fill = {
  x: number
  y: number
  w: number
  h: number
  fill: string
  /** Enough to tell an opaque surface from a glaze of light over one. */
  alpha: number
  op: string
}

function recordingCtx(unit: number) {
  const fills: Fill[] = []
  const gradient = { addColorStop: () => {} }
  // A real save/restore stack. Without one, globalAlpha set by a shadow leaks
  // into everything drawn after it, and the two rooms end up recording the
  // same mug under whatever alpha their previous fixture happened to leave.
  const stack: Record<string, unknown>[] = []
  const STATEFUL = [
    'fillStyle',
    'strokeStyle',
    'lineWidth',
    'lineCap',
    'globalAlpha',
    'globalCompositeOperation',
    'filter',
    'font',
    'textBaseline',
  ] as const

  const ctx = {
    canvas: { width: 1600, height: 900 },
    fillStyle: '' as unknown,
    strokeStyle: '' as unknown,
    lineWidth: 0,
    lineCap: '',
    globalAlpha: 1,
    globalCompositeOperation: 'source-over',
    filter: 'none',
    font: '',
    textBaseline: '',
    fillRect: (x: number, y: number, w: number, h: number) =>
      fills.push({
        x: x / unit,
        y: y / unit,
        w: w / unit,
        h: h / unit,
        fill: String(ctx.fillStyle),
        alpha: ctx.globalAlpha,
        op: String(ctx.globalCompositeOperation || 'source-over'),
      }),
    clearRect: () => {},
    strokeRect: () => {},
    // Recorded, because a panel's title is drawn as text: without this a
    // retitled panel is an invisible change and the key invariant sleeps
    // through it.
    fillText: (text: string, x: number, y: number) =>
      fills.push({
        x: x / unit,
        y: y / unit,
        w: 0,
        h: 0,
        fill: `text:${text}`,
        alpha: ctx.globalAlpha,
        op: 'source-over',
      }),
    measureText: () => ({ width: 10 }),
    save: () => {
      const held: Record<string, unknown> = {}
      for (const k of STATEFUL) held[k] = (ctx as Record<string, unknown>)[k]
      stack.push(held)
    },
    restore: () => {
      const held = stack.pop()
      if (!held) return
      for (const k of STATEFUL) (ctx as Record<string, unknown>)[k] = held[k]
    },
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

type Room = { drawRoomBack: typeof enhanced.drawRoomBack }
const ROOMS: [string, Room][] = [
  ['enhanced', enhanced],
  ['classic', classic],
]

function render(room: Room): Fill[] {
  // No document in this environment, so the backdrop cache stands aside and
  // the painter runs straight onto the recording context.
  resetBackdrop()
  const { ctx, fills } = recordingCtx(UNIT)
  room.drawRoomBack(ctx, UNIT, STATE)
  return fills
}

function tag(f: Fill): string {
  return (
    [f.x, f.y, f.w, f.h, f.alpha].map((n) => n.toFixed(3)).join(',') + `|${f.fill}|${f.op}`
  )
}

/**
 * A fill that actually hides what is under it.
 *
 * Alpha and composite mode are the whole test — not whether it is a flat
 * colour. A gradient sky is as opaque as a wall, which is exactly how a mug
 * left on the sill disappeared; the light shaft is a glaze because it is drawn
 * under full alpha's reach, not because of what its fillStyle is.
 */
function opaque(f: Fill): boolean {
  return f.alpha >= 0.999 && f.op === 'source-over' && !f.fill.startsWith('text:')
}

/**
 * The fills in `after` that are not in `before`.
 *
 * This is what gives these tests teeth. Asking "did anything get painted near
 * the shelf" is satisfied by the shelf itself; asking what *changed* when the
 * mug moved there cancels every fixture in the room and leaves the mug.
 */
function added(before: Fill[], after: Fill[]): Fill[] {
  const pool = new Map<string, number>()
  for (const f of before) pool.set(tag(f), (pool.get(tag(f)) ?? 0) + 1)
  const out: Fill[] = []
  for (const f of after) {
    const key = tag(f)
    const left = pool.get(key) ?? 0
    if (left > 0) pool.set(key, left - 1)
    else out.push(f)
  }
  return out
}

/** Every fill in the set lies inside the box, in stage units. */
function within(fills: Fill[], box: { x: number; y: number; w: number; h: number }) {
  return fills.every(
    (f) =>
      f.x >= box.x - 0.01 &&
      f.y >= box.y - 0.01 &&
      f.x + f.w <= box.x + box.w + 0.01 &&
      f.y + f.h <= box.y + box.h + 0.01,
  )
}

/** Where an object and its contact shadow may paint when it rests at `spot`. */
function propBox(spot: SpotId) {
  const at = PROP_SPOTS[spot]
  const w = propWidth('mug')
  // Generous downwards for the shadow, upwards for the object's own height.
  return { x: at.x - w, y: at.y - 12, w: w * 3, h: 16 }
}

const SPOTS: SpotId[] = ['desk', 'shelf', 'sill', 'rug', 'floor_right']
/** Somewhere to park the mug so that moving it away is what the diff sees. */
const PARK: SpotId = 'floor_far_left'

describe('the two rooms show the same room', () => {
  beforeEach(() => {
    resetBackdrop()
    panelStore.clear()
    propStore.cancel()
    propStore.setLayout({
      mug: 'desk',
      books: 'floor_left',
      box: 'floor_far_left',
      plant: 'floor_mid',
    })
  })

  it('draws the mug at whichever spot it has been moved to, and only there', () => {
    for (const spot of SPOTS) {
      for (const [name, room] of ROOMS) {
        propStore.setLayout({ mug: PARK })
        const before = render(room)
        propStore.setLayout({ mug: spot })
        const appeared = added(before, render(room))

        expect(appeared.length, `${name} paints nothing new at ${spot}`).toBeGreaterThan(0)
        expect(
          within(appeared, propBox(spot)),
          `${name} painted outside the mug's box at ${spot}: ` +
            JSON.stringify(appeared.slice(0, 3)),
        ).toBe(true)
      }
    }
  })

  it('draws the same mug, fill for fill, in both rooms', () => {
    // The real sync requirement: not merely that each room paints something,
    // but that they paint the same object in the same place.
    for (const spot of SPOTS) {
      const perRoom = ROOMS.map(([, room]) => {
        propStore.setLayout({ mug: PARK })
        const before = render(room)
        propStore.setLayout({ mug: spot })
        return added(before, render(room)).map(tag).sort()
      })
      expect(perRoom[1], `rooms disagree about the mug at ${spot}`).toEqual(perRoom[0])
    }
  })

  it('takes the mug off the surface while Rau is carrying it', () => {
    // The backdrop bakes resting objects, so the errand has to reach the cache
    // key. When it did not, the baked mug stayed on the desk while a second
    // one rode across the room in his claws.
    for (const [name, room] of ROOMS) {
      propStore.cancel()
      propStore.setLayout({ mug: 'desk' })
      const resting = render(room)

      propStore.begin({ id: 'e1', prop: 'mug', from: 'desk', to: 'shelf' })
      propStore.advance('e1', 'carry')
      const carrying = render(room)

      const removed = added(carrying, resting)
      expect(removed.length, `${name} still paints the mug on the desk`).toBeGreaterThan(0)
      expect(within(removed, propBox('desk')), `${name} removed the wrong fills`).toBe(true)
      expect(added(resting, carrying).length, `${name} painted something extra`).toBe(0)
    }
  })

  it('puts the mug down at the far end once the errand is done', () => {
    for (const [name, room] of ROOMS) {
      propStore.cancel()
      propStore.setLayout({ mug: 'desk' })
      const before = render(room)
      propStore.begin({ id: 'e2', prop: 'mug', from: 'desk', to: 'shelf' })
      propStore.advance('e2', 'done')
      const appeared = added(before, render(room))
      expect(appeared.length, `${name} paints nothing at the shelf`).toBeGreaterThan(0)
      expect(within(appeared, propBox('shelf')), `${name} put it somewhere else`).toBe(true)
    }
  })

  it('hangs a panel on the wall, and takes the poster down for it', () => {
    for (const [name, room] of ROOMS) {
      panelStore.clear()
      const before = render(room)
      panelStore.add({ panel_id: 'p1', title: 'This week', kind: 'dashboard', created: 1 })
      const after = render(room)

      // Slot 0 is the poster's hook: 15 x 21 at stage (76, 12).
      const slot = { x: 74, y: 10, w: 19, h: 25 }
      const appeared = added(before, after)
      expect(appeared.length, `${name} hangs nothing`).toBeGreaterThan(0)
      expect(within(appeared, slot), `${name} hung the panel off the slot`).toBe(true)

      // And the decorative poster stands down, rather than showing round it.
      const removed = added(after, before)
      expect(removed.length, `${name} left the poster up behind the panel`).toBeGreaterThan(0)
    }
  })

  /**
   * The invariant the cache lives or dies by.
   *
   * The backdrop is painted once and reused until its key changes, so any
   * state that alters the frame must alter the key. Nothing else in this file
   * can catch a violation: with no document the cache stands aside, every
   * render is live, and a key that names nothing at all still passes.
   */
  it('changes its cache key whenever the room it would bake changes', () => {
    const bakeKey = () => `${restingPropsKey()}|${wallPanelsKey()}`
    const errands = [
      ['carrying the mug', () => {
        propStore.begin({ id: 'k1', prop: 'mug', from: 'desk', to: 'shelf' })
        propStore.advance('k1', 'carry')
      }],
      ['setting it down', () => propStore.advance('k1', 'done')],
      ['hanging a panel', () =>
        panelStore.add({ panel_id: 'k', title: 'This week', kind: 'dashboard', created: 1 })],
      ['retitling that panel', () =>
        panelStore.replaceAll([
          { panel_id: 'k', title: 'Last week', kind: 'dashboard', created: 1 },
        ])],
      ...SPOTS.map(
        (spot) => [`moving the mug to ${spot}`, () => propStore.setLayout({ mug: spot })] as const,
      ),
    ] as const

    for (const [what, mutate] of errands) {
      const before = { frame: render(enhanced).map(tag).join(';'), key: bakeKey() }
      mutate()
      const after = { frame: render(enhanced).map(tag).join(';'), key: bakeKey() }
      if (before.frame === after.frame) continue
      expect(after.key, `${what} changes the room but not the bake key`).not.toBe(before.key)
    }
  })

  it('never paints the room back over an object resting on a surface', () => {
    // A recording canvas records fills, not visibility, so every other test
    // here passes happily while an object sits behind the scenery. Classic
    // baked the window view *after* the props and then repainted the glass
    // live on top, so a mug left on the sill vanished completely.
    for (const spot of SPOTS) {
      for (const [name, room] of ROOMS) {
        propStore.setLayout({ mug: PARK })
        const before = render(room)
        propStore.setLayout({ mug: spot })
        const after = render(room)

        const mug = new Set(added(before, after).map(tag))
        const first = after.findIndex((f) => mug.has(tag(f)))
        expect(first, `${name} paints no mug at ${spot}`).toBeGreaterThanOrEqual(0)

        const at = PROP_SPOTS[spot]
        const buried = after.slice(first + 1).find(
          (f) =>
            !mug.has(tag(f)) &&
            opaque(f) &&
            f.w > 4 &&
            f.h > 4 &&
            f.x <= at.x &&
            f.x + f.w >= at.x + propWidth('mug') &&
            f.y <= at.y - 2 &&
            f.y + f.h >= at.y,
        )
        expect(buried, `${name} paints over the mug at ${spot}: ${JSON.stringify(buried)}`)
          .toBeUndefined()
      }
    }
  })
})
