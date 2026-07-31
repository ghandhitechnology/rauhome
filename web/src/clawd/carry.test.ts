/**
 * Having hold of something.
 *
 * Two things are being pinned here. First, that an object crosses into and out
 * of his claws rather than teleporting on a phase change — it used to sit on
 * the floor through the entire crouch that was meant to be him picking it up,
 * then appear at his shoulder. Second, that once held it is positioned off the
 * live sprite, so it moves with the bob, the lean and the claw springs instead
 * of floating alongside him at a fixed offset from his feet.
 */

import { describe, expect, it } from 'vitest'

import { MOTIONS } from './motions'
import { defaultParams } from './params'
import { GRIPS, grip, propHeight, PropStore, PROP_IDS, PROP_SPOTS } from './props'
import { ClawdRig } from './rig'
import { clawdAnchors } from './sprite'

const DT = 1 / 60

/** A store mid-errand, wound forward `seconds` into `phase`. */
function midErrand(prop: (typeof PROP_IDS)[number], phase: 'lift' | 'carry' | 'place', seconds: number) {
  const store = new PropStore()
  store.begin({ id: 'e1', prop, from: 'floor_left', to: 'shelf' })
  store.advance('e1', phase)
  for (let t = 0; t < seconds; t += DT) store.tick(DT)
  return store
}

/** Where the sprite's claws actually are this frame, in stage units. */
function clawAt(rig: ClawdRig, worldX: number, u = 12) {
  const anchors = clawdAnchors(rig.params, { unit: u * 1.25, x: worldX * u, y: 68 * u })
  return { x: anchors.fan.x / u, y: anchors.fan.y / u, facing: rig.facing }
}

describe('taking hold', () => {
  it('leaves it on the floor until his claws are actually on it', () => {
    // The lift clip does not reach down until a third of the way through.
    const store = midErrand('box', 'lift', 0.1)
    expect(store.grip).toBe(0)
    const spot = PROP_SPOTS.floor_left
    const at = store.placement('box', { x: 40, y: 60 })
    expect(at.x).toBe(spot.x)
    expect(at.y).toBe(spot.y)
  })

  it('crosses into his claws rather than appearing in them', () => {
    const seen = [0.1, 0.4, 0.55, 0.7, 1.2].map((s) => midErrand('box', 'lift', s).grip)
    // Monotonic, starts on the floor, ends fully held, and passes through the
    // middle instead of stepping from 0 to 1.
    expect(seen[0]).toBe(0)
    expect(seen[seen.length - 1]).toBe(1)
    for (let i = 1; i < seen.length; i++) expect(seen[i]).toBeGreaterThanOrEqual(seen[i - 1])
    expect(seen.some((g) => g > 0.05 && g < 0.95)).toBe(true)
  })

  it('lets go on the way down, not when the phase name changes', () => {
    expect(midErrand('box', 'place', 0.1).grip).toBe(1)
    expect(midErrand('box', 'place', 0.6).grip).toBeLessThan(1)
    expect(midErrand('box', 'place', 1).grip).toBe(0)
  })

  it('holds on through the whole walk across', () => {
    const store = midErrand('plant', 'carry', 4)
    expect(store.grip).toBe(1)
  })
})

describe('riding in his claws', () => {
  it('follows the claws through the bob of a walk', () => {
    const store = midErrand('mug', 'carry', 0)
    const rig = new ClawdRig()
    rig.play('carry', { force: true, restart: true })

    const ys = new Set<number>()
    for (let i = 0; i < 90; i++) {
      rig.advanceGait(MOTIONS.carry.locomotion! * DT)
      rig.update(DT)
      ys.add(Number(store.placement('mug', clawAt(rig, 90)).y.toFixed(3)))
    }
    // A fixed offset from his feet would give exactly one height for the whole
    // walk. Riding the claws gives a different one almost every frame.
    expect(ys.size).toBeGreaterThan(20)
  })

  it('leans with him rather than staying bolt upright', () => {
    const store = midErrand('books', 'carry', 0)
    const rig = new ClawdRig()

    rig.params.angle = 0
    const level = store.placement('books', clawAt(rig, 90))
    rig.params.angle = 18
    const tilted = store.placement('books', clawAt(rig, 90))

    expect(Math.abs(tilted.x - level.x)).toBeGreaterThan(0.2)
  })

  it('changes sides with him when he turns round', () => {
    const store = midErrand('plant', 'carry', 0)
    const rig = new ClawdRig()

    rig.facing = 1
    rig.params.facing = 1
    const ahead = store.placement('plant', clawAt(rig, 90))
    rig.facing = -1
    rig.params.facing = -1
    const behind = store.placement('plant', clawAt(rig, 90))

    // The reach offset is applied along his facing, so it flips with him.
    expect(ahead.x).not.toBe(behind.x)
  })
})

describe('a grip for each thing', () => {
  it('covers every prop', () => {
    for (const id of PROP_IDS) {
      const g = grip(id)
      expect(g, id).toBeDefined()
      expect(MOTIONS[g.gait], `${id} names a gait that exists`).toBeDefined()
      expect(MOTIONS[g.gait].locomotion, `${id}'s gait actually travels`).toBeGreaterThan(0)
      expect(g.care, id).toBeGreaterThan(0)
    }
  })

  /**
   * The one that matters. Clawd is nine and a half units tall and the things he
   * moves are up to eight, so an object held anywhere near the claw anchor
   * covers his face — and a character carrying something is only readable if
   * you can still see what he thinks about carrying it. Every grip has to hold
   * its object low enough that his eyes clear the top of it.
   */
  it('never holds anything in front of his own eyes', () => {
    const rig = new ClawdRig()
    rig.update(DT)
    const u = 12
    const eyes = clawdAnchors(rig.params, { unit: u * 1.25, x: 90 * u, y: 68 * u }).head.y / u

    for (const id of PROP_IDS) {
      const store = midErrand(id, 'carry', 0)
      const at = store.placement(id, clawAt(rig, 90, u))
      // `at.y` is the object's base; it is drawn upward from there, and y grows
      // downward on screen, so the top edge is base minus height.
      const top = at.y - propHeight(id, grip(id).scale)
      expect(top, `${id} covers his eyes`).toBeGreaterThan(eyes)
    }
  })

  it('hugs the big things lower than the small ones', () => {
    expect(GRIPS.box.lift).toBeLessThan(GRIPS.books.lift)
    expect(GRIPS.books.lift).toBeLessThan(GRIPS.mug.lift)
  })

  it('walks slower with the awkward things than with a mug', () => {
    const speed = (id: (typeof PROP_IDS)[number]) => MOTIONS[grip(id).gait].locomotion!
    expect(speed('box')).toBeLessThan(speed('mug'))
  })

  it('takes longer over a plant than over a mug at both ends', () => {
    expect(grip('plant').care).toBeGreaterThan(grip('mug').care)
  })

  it('only watches the thing that can spill', () => {
    expect(GRIPS.plant.watch).toBe(true)
    expect(GRIPS.box.watch).toBe(false)
    expect(GRIPS.mug.watch).toBe(false)
  })
})

describe('the box gait', () => {
  it('is its own clip rather than an offset of the chest carry', () => {
    const angle = (id: 'carry' | 'carryBox') =>
      MOTIONS[id].tracks.find((t) => t.param === 'angle')!.keys[0].v
    const claw = (id: 'carry' | 'carryBox') =>
      MOTIONS[id].tracks.find((t) => t.param === 'clawL')!.keys[0].v

    // Leaning back against the load, not forward over it.
    expect(angle('carryBox')).toBeLessThan(angle('carry'))
    // Claws down and in, hugging it, rather than up and out presenting it.
    expect(claw('carryBox')).toBeLessThan(0)
    expect(claw('carry')).toBeGreaterThan(0)
  })

  it('obeys the same stride geometry as every other gait', () => {
    expect(MOTIONS.carryBox.phaseSource).toBe('distance')
    expect(MOTIONS.carryBox.loop).toBe(true)
  })
})

describe('the shadow', () => {
  it('stays with the floor while the object leaves it', () => {
    // Not a drawing test — the contract is that `grip` is what the shadow
    // fades on, so it has to be readable without a canvas.
    const store = midErrand('box', 'lift', 0.5)
    expect(store.grip).toBeGreaterThan(0)
    expect(store.grip).toBeLessThan(1)
  })
})

describe('a sprite with nothing in its claws', () => {
  it('reports no grip at all', () => {
    const store = new PropStore()
    const rig = new ClawdRig()
    rig.update(DT)
    for (const id of PROP_IDS) {
      expect(store.placement(id, clawAt(rig, 90)).grip, id).toBe(0)
    }
  })

  it('does not move the anchors when the parameters are untouched', () => {
    const a = clawdAnchors(defaultParams(), { unit: 5, x: 100, y: 200 })
    const b = clawdAnchors(defaultParams(), { unit: 5, x: 100, y: 200 })
    expect(a.fan).toEqual(b.fan)
  })
})
