/**
 * Objects Rau can pick up and carry, and where they may rest.
 *
 * The server owns the truth (`rau/face/props.py`); this owns the performance.
 * When an errand arrives the object does not teleport: it stays where it was
 * until he has crouched and taken its weight, rides with him while he walks,
 * and only lands when he puts it down. That sequencing is the whole reason
 * this is a module rather than a lookup table.
 */

import { mixHex, ROOM } from './palette'
import type { StationId } from './room'
import { FLOOR_Y } from './stage'

export const PROP_IDS = ['mug', 'books', 'box', 'plant'] as const
export type PropId = (typeof PROP_IDS)[number]

export const SPOT_IDS = [
  'desk',
  'shelf',
  'sill',
  'rug',
  'floor_far_left',
  'floor_left',
  'floor_mid',
  'floor_right',
] as const
export type SpotId = (typeof SPOT_IDS)[number]

/**
 * Where a resting object sits, and where Rau stands to reach it.
 *
 * `y` is the surface the object's base rests on, so the same mug reads as
 * being on the desk or on the floor without the drawing code caring which.
 */
export const PROP_SPOTS: Record<SpotId, { x: number; y: number; station: StationId }> = {
  desk: { x: 119, y: 60, station: 'desk' },
  shelf: { x: 137, y: 41, station: 'shelf' },
  sill: { x: 46, y: 44, station: 'window' },
  rug: { x: 74, y: FLOOR_Y + 1, station: 'rug' },
  floor_far_left: { x: 18, y: FLOOR_Y, station: 'window' },
  floor_left: { x: 46, y: FLOOR_Y, station: 'plant' },
  floor_mid: { x: 66, y: FLOOR_Y, station: 'rug' },
  floor_right: { x: 150, y: FLOOR_Y, station: 'shelf' },
}

/** How far off the floor an object rides while being carried. */
const CARRY_LIFT = 7.5

type Ctx = CanvasRenderingContext2D

function r(ctx: Ctx, u: number, x: number, y: number, w: number, h: number, fill: string) {
  ctx.fillStyle = fill
  ctx.fillRect(x * u, y * u, w * u, h * u)
}

// ── the objects ───────────────────────────────────────────────────────
//
// Each draws from its own base point, so it can be put down anywhere.

function drawMug(ctx: Ctx, u: number, x: number, base: number, s: number) {
  const w = 3.3 * s
  const h = 3.4 * s
  r(ctx, u, x, base - h, w, h, ROOM.paper)
  r(ctx, u, x, base - h, w, 0.45 * s, '#FFFFFF')
  r(ctx, u, x + w * 0.72, base - h, w * 0.28, h, ROOM.paperShade)
  r(ctx, u, x + w, base - h * 0.76, 1 * s, 1.8 * s, ROOM.paper)
  r(ctx, u, x + w + 0.5 * s, base - h * 0.64, 0.5 * s, 1 * s, ROOM.wall)
}

function drawBooks(ctx: Ctx, u: number, x: number, base: number, s: number) {
  const spines = ['#8A4B3A', '#5C6B7A', '#7A6A44', '#6B4A5C', '#4A6355']
  for (let i = 0; i < 5; i++) {
    const bw = (6.5 - i * 0.5) * s
    const off = Math.sin(i * 1.7) * 0.5 * s
    const tone = spines[i % spines.length]
    const y = base - (1.2 + i * 1.2) * s
    r(ctx, u, x + off, y, bw, 1.2 * s, tone)
    r(ctx, u, x + off, y, bw, 0.3 * s, mixHex(tone, '#FFFFFF', 0.28))
    r(ctx, u, x + off, y + 0.8 * s, bw, 0.25 * s, mixHex(tone, '#000000', 0.4))
  }
}

function drawBox(ctx: Ctx, u: number, x: number, base: number, s: number) {
  const w = 10 * s
  const h = 8 * s
  r(ctx, u, x, base - h, w, h, ROOM.cork)
  r(ctx, u, x, base - h, w, 0.5 * s, mixHex(ROOM.cork, '#FFFFFF', 0.2))
  r(ctx, u, x, base - 0.5 * s, w, 0.5 * s, mixHex(ROOM.cork, '#000000', 0.4))
  r(ctx, u, x + w * 0.46, base - h, 0.8 * s, h, mixHex(ROOM.cork, '#000000', 0.35))
  r(ctx, u, x + w * 0.1, base - h * 0.62, w * 0.6, 0.8 * s, mixHex(ROOM.paper, ROOM.cork, 0.4))
}

function drawPlant(ctx: Ctx, u: number, x: number, base: number, s: number, time: number) {
  const potW = 8 * s
  const potH = 8 * s
  ctx.fillStyle = ROOM.fabricDeep
  ctx.beginPath()
  ctx.moveTo((x + 0.6 * s) * u, (base - potH) * u)
  ctx.lineTo((x + potW - 0.6 * s) * u, (base - potH) * u)
  ctx.lineTo((x + potW - 1.6 * s) * u, base * u)
  ctx.lineTo((x + 1.6 * s) * u, base * u)
  ctx.closePath()
  ctx.fill()
  r(ctx, u, x + 1.2 * s, base - potH, 1.2 * s, potH, mixHex(ROOM.fabric, '#FFFFFF', 0.12))
  r(ctx, u, x - 0.2 * s, base - potH - 1 * s, potW + 0.4 * s, 1.4 * s, ROOM.fabric)
  r(ctx, u, x - 0.2 * s, base - potH - 1 * s, potW + 0.4 * s, 0.4 * s, ROOM.fabricLit)

  const blades = [
    { dx: 1.2, h: 17, lean: -1.4 },
    { dx: 2.8, h: 23, lean: -0.4 },
    { dx: 4.4, h: 26, lean: 0.3 },
    { dx: 5.8, h: 21, lean: 1.2 },
    { dx: 7, h: 14, lean: 1.9 },
  ]
  blades.forEach((b, i) => {
    const sway = Math.sin(time * 0.55 + i * 1.3) * 1.1
    for (let seg = 0; seg < b.h; seg += 1.3) {
      const t = seg / b.h
      const off = (b.lean + sway * 0.4) * t * t * 2.6
      const width = (1.3 - t * 0.5) * s
      r(
        ctx, u,
        x + (b.dx + off) * s, base - potH - 1.6 * s - seg * s,
        width, 1.35 * s,
        t > 0.62 ? ROOM.leafLit : ROOM.leaf,
      )
    }
  })
}

/** Footprint used for the contact shadow, in stage units at scale 1. */
const PROP_WIDTH: Record<PropId, number> = { mug: 3.3, books: 6.5, box: 10, plant: 8 }

export function drawProp(
  ctx: Ctx,
  u: number,
  id: PropId,
  x: number,
  base: number,
  time: number,
  scale = 1,
) {
  switch (id) {
    case 'mug':
      return drawMug(ctx, u, x, base, scale)
    case 'books':
      return drawBooks(ctx, u, x, base, scale)
    case 'box':
      return drawBox(ctx, u, x, base, scale)
    case 'plant':
      return drawPlant(ctx, u, x, base, scale, time)
  }
}

export function propWidth(id: PropId, scale = 1): number {
  return PROP_WIDTH[id] * scale
}

// ── the errand ────────────────────────────────────────────────────────

export type ErrandPhase = 'travel' | 'lift' | 'carry' | 'place' | 'done'

export type Errand = {
  id: string
  prop: PropId
  from: SpotId
  to: SpotId
  phase: ErrandPhase
}

type Listener = () => void

/**
 * Where every object is, and what is currently in Rau's claws.
 *
 * One store for the page: the room scene and any other view read the same
 * arrangement, so an object cannot be on the shelf in one place and the floor
 * in another.
 */
export class PropStore {
  private layout: Record<PropId, SpotId> = {
    mug: 'desk',
    books: 'floor_left',
    box: 'floor_far_left',
    plant: 'floor_mid',
  }
  private errand: Errand | null = null
  private listeners = new Set<Listener>()

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn)
    return () => {
      this.listeners.delete(fn)
    }
  }

  private notify() {
    for (const fn of [...this.listeners]) {
      try {
        fn()
      } catch {
        /* one bad view must not stop the rest updating */
      }
    }
  }

  /** Adopt a whole arrangement (a reconnect, or a reset). */
  setLayout(next: Partial<Record<PropId, SpotId>>) {
    let changed = false
    for (const id of PROP_IDS) {
      const spot = next[id]
      if (spot && spot in PROP_SPOTS && this.layout[id] !== spot) {
        this.layout[id] = spot
        changed = true
      }
    }
    if (changed) this.notify()
  }

  spotOf(id: PropId): SpotId {
    return this.layout[id]
  }

  get activeErrand(): Errand | null {
    return this.errand
  }

  /** Begin an errand. The object does not move yet. */
  begin(errand: Omit<Errand, 'phase'>) {
    if (!(errand.prop in this.layout)) return
    if (!(errand.from in PROP_SPOTS) || !(errand.to in PROP_SPOTS)) return
    this.errand = { ...errand, phase: 'travel' }
    // Hold it at its origin until he has actually picked it up.
    this.layout[errand.prop] = errand.from
    this.notify()
  }

  advance(id: string, phase: ErrandPhase) {
    const errand = this.errand
    if (!errand || errand.id !== id) return
    errand.phase = phase
    if (phase === 'done') {
      this.layout[errand.prop] = errand.to
      this.errand = null
    }
    this.notify()
  }

  /** Abandon an errand — the object lands wherever the server says it is. */
  cancel(id?: string) {
    const errand = this.errand
    if (!errand) return
    if (id && errand.id !== id) return
    this.layout[errand.prop] = errand.to
    this.errand = null
    this.notify()
  }

  /**
   * Where to draw an object this frame.
   *
   * Anything not in his claws sits on its spot. The carried one rides at his
   * shoulder, which is what makes the walk read as carrying rather than as
   * walking next to something that happens to be moving.
   */
  placement(id: PropId, carrier: { x: number; y: number }): { x: number; y: number; carried: boolean } {
    const errand = this.errand
    if (errand && errand.prop === id && (errand.phase === 'carry' || errand.phase === 'place')) {
      return { x: carrier.x - propWidth(id) / 2, y: carrier.y - CARRY_LIFT, carried: true }
    }
    const spot = PROP_SPOTS[this.layout[id]]
    return { x: spot.x, y: spot.y, carried: false }
  }
}

/** One arrangement per page. */
export const propStore = new PropStore()
