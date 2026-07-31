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

// ── how each thing is held ────────────────────────────────────────────

/**
 * How Clawd handles one particular object.
 *
 * A mug and a cardboard box are not carried the same way, and the difference
 * is mostly not in the animation — it is in where the thing sits against him,
 * how fast he is willing to walk with it, and how much attention it gets. One
 * table beats four sets of near-identical clips, and a new prop costs a row
 * rather than three more clips to keep in step with the stride maths.
 */
export type Grip = {
  /** The gait that carries it. */
  gait: 'carry' | 'carryBox'
  /** How far above the claw anchor it rides, in stage units. */
  lift: number
  /** How far in front of him it sits, in stage units. Positive is forward. */
  reach: number
  /** Drawn scale while held. */
  scale: number
  /** Multiplier on how long he spends picking it up and putting it down. */
  care: number
  /** Whether his eyes stay on it while he walks. */
  watch: boolean
}

/**
 * `lift` is measured from the claw anchor, which sits low on the shell — well
 * below his eyes. Every one of these is negative because Clawd is nine and a
 * half units tall and the things he moves are up to eight: held anywhere near
 * the claws, the object covers his face, and a character carrying something is
 * only readable if you can still see what he thinks about carrying it. So he
 * hugs them, and his eyes clear the top edge. These were set by looking at him
 * hold each one; `carry.test.ts` keeps them honest.
 */
export const GRIPS: Record<PropId, Grip> = {
  // Small and light: hangs off the claw out to one side, no slowing down for it.
  mug: { gait: 'carry', lift: -1.8, reach: 2.6, scale: 1, care: 0.75, watch: false },
  // A stack wants both claws under it and holding it in against the body,
  // because a stack held out in front is a stack on the floor.
  books: { gait: 'carry', lift: -3.1, reach: 0.2, scale: 0.95, care: 1, watch: false },
  // Wide and awkward: hugged low, leaned back against, and walked slowly.
  box: { gait: 'carryBox', lift: -4.3, reach: 0.4, scale: 0.92, care: 1.15, watch: false },
  // Top-heavy and spillable. Walked carefully and checked on the whole way —
  // the glancing is most of what makes it read as fragile. Carried lowest of
  // the lot, because the pot alone is as tall as he is; the fronds are left to
  // cross his face on purpose, being thin enough to see him through.
  plant: { gait: 'carry', lift: -4.6, reach: 1.2, scale: 0.94, care: 1.3, watch: true },
}

export function grip(id: PropId): Grip {
  return GRIPS[id]
}

// ── taking hold and letting go ────────────────────────────────────────
//
// Seconds into the lift and place clips where his claws actually close on the
// object and open again. Taken from the clips themselves: `lift` reaches down
// at t=0.3 of 1.05s and has it up by t=0.82, `place` starts lowering at t=0.4
// of 1.1s and lets go at t=0.72. The object crosses between its spot and his
// claws over those windows instead of teleporting on a phase change.

const LIFT_GRAB = 0.32
const LIFT_HELD = 0.87
const PLACE_LOWER = 0.44
const PLACE_RELEASED = 0.8

/** Smooth 0..1 across a window, so nothing starts or stops with a jerk. */
function ramp(value: number, from: number, to: number): number {
  if (to <= from) return value >= to ? 1 : 0
  const t = (value - from) / (to - from)
  const c = t < 0 ? 0 : t > 1 ? 1 : t
  return c * c * (3 - 2 * c)
}

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

/**
 * How tall each object stands above its base, in stage units at scale 1.
 *
 * The plant is its pot only. Its fronds go half as high again, and are meant
 * to — they are thin enough to see his face through, which a solid object is
 * not. Everything here must match what the `draw*` functions below paint.
 */
const PROP_HEIGHT: Record<PropId, number> = { mug: 3.4, books: 6, box: 8, plant: 8 }

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

export function propHeight(id: PropId, scale = 1): number {
  return PROP_HEIGHT[id] * scale
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
  /** Seconds since the current errand phase began. */
  private phaseAge = 0
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
    this.phaseAge = 0
    // Hold it at its origin until he has actually picked it up.
    this.layout[errand.prop] = errand.from
    this.notify()
  }

  /**
   * Advance the clock the grip runs off.
   *
   * The object crossing into and out of his claws is a movement rather than a
   * phase change, so it needs a clock of its own. Driven by the render loop.
   */
  tick(dt: number) {
    if (this.errand) this.phaseAge += dt
  }

  /**
   * How much of the object's weight he has, 0..1.
   *
   * 0 is resting on its spot, 1 is fully in his claws. In between it is
   * crossing — which is the whole point: it used to teleport into his grip the
   * instant the phase name changed, having sat on the floor through the entire
   * crouch that was supposed to be him taking hold of it.
   */
  get grip(): number {
    const errand = this.errand
    if (!errand) return 0
    switch (errand.phase) {
      case 'lift':
        return ramp(this.phaseAge, LIFT_GRAB, LIFT_HELD)
      case 'carry':
        return 1
      case 'place':
        return 1 - ramp(this.phaseAge, PLACE_LOWER, PLACE_RELEASED)
      default:
        return 0
    }
  }

  advance(id: string, phase: ErrandPhase) {
    const errand = this.errand
    if (!errand || errand.id !== id) return
    errand.phase = phase
    this.phaseAge = 0
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
    this.phaseAge = 0
    this.notify()
  }

  /**
   * Where to draw an object this frame, in stage units.
   *
   * Anything he is not handling sits on its spot. Anything he is crosses from
   * that spot into his claws and back out again, following `hold` — which is
   * the claw anchor off the live sprite, so a carried box rises and falls with
   * his bob, leans with him and swings with the claw springs. Held at a fixed
   * offset from his feet, as this used to be, a box reads as something moving
   * alongside him rather than as something he has hold of.
   */
  placement(
    id: PropId,
    hold: { x: number; y: number; facing?: number },
  ): { x: number; y: number; grip: number } {
    const spot = PROP_SPOTS[this.layout[id]]
    const errand = this.errand
    if (!errand || errand.prop !== id) return { x: spot.x, y: spot.y, grip: 0 }

    const g = this.grip
    if (g <= 0) return { x: spot.x, y: spot.y, grip: 0 }

    const { lift, reach } = GRIPS[id]
    const facing = hold.facing ?? 1
    const heldX = hold.x - propWidth(id) / 2 + reach * facing
    const heldY = hold.y - lift
    return {
      x: spot.x + (heldX - spot.x) * g,
      y: spot.y + (heldY - spot.y) * g,
      grip: g,
    }
  }
}

/** One arrangement per page. */
export const propStore = new PropStore()
