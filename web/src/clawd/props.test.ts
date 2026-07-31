import { beforeEach, describe, expect, it } from 'vitest'

import { PropStore, PROP_IDS, PROP_SPOTS, propWidth, SPOT_IDS } from './props'
import { MOTIONS, ONE_SHOTS } from './motions'
import { LIFE_MOTIONS } from './motionsLife'

describe('prop spots', () => {
  it('gives every place both a surface and somewhere to stand', () => {
    for (const spot of SPOT_IDS) {
      const at = PROP_SPOTS[spot]
      expect(at, spot).toBeDefined()
      expect(Number.isFinite(at.x), spot).toBe(true)
      expect(Number.isFinite(at.y), spot).toBe(true)
      // An errand to a place he cannot reach is a walk to nowhere.
      expect(at.station, spot).toBeTruthy()
    }
  })

  it('keeps every object inside the walkable part of the room', () => {
    for (const spot of SPOT_IDS) {
      expect(PROP_SPOTS[spot].x, spot).toBeGreaterThanOrEqual(14)
      expect(PROP_SPOTS[spot].x, spot).toBeLessThanOrEqual(155)
    }
  })
})

describe('PropStore errands', () => {
  let store: PropStore

  beforeEach(() => {
    store = new PropStore()
  })

  it('leaves the object where it was until he has actually picked it up', () => {
    store.begin({ id: 'e1', prop: 'mug', from: 'desk', to: 'shelf' })
    expect(store.spotOf('mug')).toBe('desk')

    store.advance('e1', 'lift')
    expect(store.spotOf('mug')).toBe('desk')
  })

  it('carries it with him rather than leaving it behind', () => {
    store.begin({ id: 'e1', prop: 'mug', from: 'desk', to: 'shelf' })
    store.advance('e1', 'carry')

    // The second argument is where his claws are, not where he is standing.
    const claws = { x: 90, y: 62, facing: 1 }
    const at = store.placement('mug', claws)
    expect(at.grip).toBe(1)

    // Placed against his claws rather than left on the desk it came from.
    const desk = PROP_SPOTS.desk
    expect(Math.abs(at.x - desk.x)).toBeGreaterThan(propWidth('mug'))
    expect(Math.abs(at.x - claws.x)).toBeLessThan(propWidth('mug') * 2)
    expect(Math.abs(at.y - claws.y)).toBeLessThan(4)
  })

  it('follows his claws rather than a fixed point in the room', () => {
    store.begin({ id: 'e1', prop: 'mug', from: 'desk', to: 'shelf' })
    store.advance('e1', 'carry')

    const low = store.placement('mug', { x: 90, y: 62, facing: 1 })
    const high = store.placement('mug', { x: 94, y: 60, facing: 1 })
    expect(high.x - low.x).toBeCloseTo(4, 6)
    expect(high.y - low.y).toBeCloseTo(-2, 6)
  })

  it('only lands it once he has set it down', () => {
    store.begin({ id: 'e1', prop: 'mug', from: 'desk', to: 'shelf' })
    store.advance('e1', 'carry')
    store.advance('e1', 'place')
    expect(store.spotOf('mug')).toBe('desk')

    store.advance('e1', 'done')
    expect(store.spotOf('mug')).toBe('shelf')
    expect(store.activeErrand).toBeNull()
    expect(store.placement('mug', { x: 90, y: 68 }).grip).toBe(0)
  })

  it('leaves everything else exactly where it was', () => {
    store.begin({ id: 'e1', prop: 'mug', from: 'desk', to: 'shelf' })
    store.advance('e1', 'carry')
    for (const id of PROP_IDS) {
      if (id === 'mug') continue
      expect(store.placement(id, { x: 90, y: 68 }).grip, id).toBe(0)
    }
  })

  it('ignores phases addressed to an errand that is not running', () => {
    store.begin({ id: 'e1', prop: 'mug', from: 'desk', to: 'shelf' })
    store.advance('other', 'done')
    expect(store.spotOf('mug')).toBe('desk')
    expect(store.activeErrand?.id).toBe('e1')
  })

  it('a cancelled errand still leaves the object where the server says', () => {
    store.begin({ id: 'e1', prop: 'books', from: 'floor_left', to: 'rug' })
    store.advance('e1', 'carry')
    store.cancel('e1')
    expect(store.spotOf('books')).toBe('rug')
    expect(store.activeErrand).toBeNull()
  })

  it('refuses an errand to a place that does not exist', () => {
    store.begin({ id: 'e1', prop: 'mug', from: 'desk', to: 'the_moon' as never })
    expect(store.activeErrand).toBeNull()
  })

  it('adopts a whole arrangement on reconnect', () => {
    store.setLayout({ mug: 'sill', plant: 'rug' })
    expect(store.spotOf('mug')).toBe('sill')
    expect(store.spotOf('plant')).toBe('rug')
    // Unknown places are ignored rather than corrupting the layout.
    store.setLayout({ mug: 'nowhere' as never })
    expect(store.spotOf('mug')).toBe('sill')
  })

  it('tells its listeners when the arrangement changes', () => {
    let calls = 0
    const off = store.subscribe(() => calls++)
    store.begin({ id: 'e1', prop: 'mug', from: 'desk', to: 'shelf' })
    store.advance('e1', 'carry')
    store.advance('e1', 'done')
    off()
    store.setLayout({ mug: 'rug' })
    expect(calls).toBe(3)
  })
})

describe('the occupational motion library', () => {
  it('adds every clip to the registry under its own id', () => {
    for (const [name, clip] of Object.entries(LIFE_MOTIONS)) {
      expect(MOTIONS[name as keyof typeof MOTIONS], name).toBeDefined()
      expect(clip.id, name).toBe(name)
    }
  })

  it('gives every clip real keyframes on real parameters', () => {
    for (const [name, clip] of Object.entries(LIFE_MOTIONS)) {
      expect(clip.duration, name).toBeGreaterThan(0)
      expect(clip.tracks.length, name).toBeGreaterThan(0)
      for (const track of clip.tracks) {
        expect(track.keys.length, `${name}.${track.param}`).toBeGreaterThan(0)
        // Keyframes are sampled by a forward scan, so out-of-order times would
        // silently hold the wrong value for part of the clip.
        const times = track.keys.map((k) => k.t)
        expect([...times].sort((a, b) => a - b), `${name}.${track.param}`).toEqual(times)
        for (const t of times) {
          expect(t, `${name}.${track.param}`).toBeGreaterThanOrEqual(0)
          expect(t, `${name}.${track.param}`).toBeLessThanOrEqual(1)
        }
      }
    }
  })

  it('closes every looping clip so it does not jump at the seam', () => {
    for (const [name, clip] of Object.entries(LIFE_MOTIONS)) {
      if (!clip.loop) continue
      for (const track of clip.tracks) {
        const first = track.keys[0]
        const last = track.keys[track.keys.length - 1]
        if (track.keys.length === 1) continue
        expect(last.t, `${name}.${track.param} must end at t=1`).toBe(1)
        expect(
          Math.abs(last.v - first.v),
          `${name}.${track.param} snaps ${first.v}→${last.v} at the loop point`,
        ).toBeLessThan(0.001)
      }
    }
  })

  /**
   * The director's own punctuation on a walk. Listing these as one-shots would
   * set `rig.busy`, which the director reads to decide whether it may travel —
   * so he would wind up to set off and then be told he was too busy to.
   */
  const DIRECTOR_OWNED = ['turnHop', 'windUp']

  it('lets the one-shots finish before anything else is chosen', () => {
    for (const [name, clip] of Object.entries(LIFE_MOTIONS)) {
      if (clip.loop || DIRECTOR_OWNED.includes(name)) continue
      expect(ONE_SHOTS, `${name} is a one-shot but may be cut off`).toContain(name)
    }
  })

  it('keeps the director-owned beats out of the one-shot list', () => {
    for (const name of DIRECTOR_OWNED) {
      expect(LIFE_MOTIONS[name as keyof typeof LIFE_MOTIONS].loop).toBeFalsy()
      expect(ONE_SHOTS, `${name} would block the travel it punctuates`).not.toContain(name)
    }
  })

  it('only marks clips that actually travel as gaits', () => {
    const travelling = Object.entries(LIFE_MOTIONS)
      .filter(([, clip]) => clip.locomotion)
      .map(([name]) => name)
    expect(travelling.sort()).toEqual(['carry', 'carryBox', 'pace', 'push', 'tiptoe'])
    for (const name of travelling) {
      const clip = LIFE_MOTIONS[name as keyof typeof LIFE_MOTIONS]
      expect(clip.loop, `${name} travels, so it has to loop`).toBe(true)
      // Legs have to be swinging, or he glides.
      expect(
        clip.tracks.some((t) => t.param === 'legSwing' && t.keys.some((k) => k.v > 0)),
        `${name} travels without moving its legs`,
      ).toBe(true)
    }
  })
})
