/**
 * Getting somewhere, as a sequence of things rather than one.
 *
 * The behaviour under test is that Clawd never changes state in zero frames:
 * he does not start moving on the frame he decides to, and he is never simply
 * backwards on the next frame. The awkward cases are the ones that used to be
 * handled by assigning `facing` directly — a target appearing behind him mid
 * walk, and a narrow walk range where that happens constantly.
 */

import { describe, expect, it } from 'vitest'

import { Director, EMPTY_SIGNALS } from './director'
import { MOTIONS } from './motions'
import { ClawdRig } from './rig'
import { station } from './room'

const FRAME = 1 / 60

function run(director: Director, rig: ClawdRig, seconds: number) {
  for (let t = 0; t < seconds; t += FRAME) {
    director.update(FRAME, EMPTY_SIGNALS)
    rig.update(FRAME)
  }
}

function setup(at = station('centre').x) {
  const rig = new ClawdRig()
  const director = new Director(rig, 'room')
  rig.worldX = at
  return { rig, director }
}

/** Every distinct value `facing` took over a run, in order. */
function facingTrace(director: Director, rig: ClawdRig, seconds: number): number[] {
  const seen: number[] = [rig.facing]
  for (let t = 0; t < seconds; t += FRAME) {
    director.update(FRAME, EMPTY_SIGNALS)
    rig.update(FRAME)
    if (rig.facing !== seen[seen.length - 1]) seen.push(rig.facing)
  }
  return seen
}

describe('setting off', () => {
  it('does not move on the frame the decision is made', () => {
    const { rig, director } = setup()
    const before = rig.worldX
    director.goTo('shelf')
    director.update(FRAME, EMPTY_SIGNALS)
    rig.update(FRAME)
    expect(rig.worldX).toBe(before)
  })

  it('looks at where it is going, then shifts its weight, then walks', () => {
    const { rig, director } = setup()
    director.goTo('shelf')

    // The eyes lead. Nothing else has happened yet.
    run(director, rig, 0.1)
    expect(rig.params.eyeX).toBeGreaterThan(0.1)
    expect(rig.currentMotion).not.toBe('walk')

    // Then the weight shift, which throws him back before it throws him on.
    run(director, rig, 0.15)
    expect(rig.currentMotion).toBe('windUp')

    run(director, rig, 0.3)
    expect(rig.currentMotion).toBe('walk')
  })

  it('is under way within half a second', () => {
    const { rig, director } = setup()
    const before = rig.worldX
    director.goTo('shelf')
    run(director, rig, 0.5)
    expect(rig.worldX).toBeGreaterThan(before)
  })

  it('takes its own look and wind-up for a second journey', () => {
    const { rig, director } = setup()
    director.goTo('desk')
    run(director, rig, 8)

    const arrived = rig.worldX
    director.goTo('window')
    director.update(FRAME, EMPTY_SIGNALS)
    rig.update(FRAME)
    expect(rig.worldX).toBe(arrived)
  })
})

describe('turning round', () => {
  it('never flips the mirror without a hop to hide it in', () => {
    const { rig, director } = setup(station('shelf').x)
    expect(rig.facing).toBe(1)

    director.goTo('window')
    // The turn is a clip, and it is playing while the mirror is still unflipped.
    run(director, rig, 0.4)
    expect(rig.currentMotion).toBe('turnHop')

    run(director, rig, 0.3)
    expect(rig.facing).toBe(-1)
  })

  it('flips at the flattest frame of the hop', () => {
    const { rig, director } = setup(station('shelf').x)
    director.goTo('window')

    let widthAtFlip = 1
    let facing = rig.facing
    for (let t = 0; t < 1; t += FRAME) {
      director.update(FRAME, EMPTY_SIGNALS)
      rig.update(FRAME)
      if (rig.facing !== facing) {
        widthAtFlip = rig.params.scaleX
        break
      }
      facing = rig.facing
    }
    // The `turnHop` clip squashes to 0.72 at the flip; a little blend slack
    // either side, but nowhere near his standing width.
    expect(widthAtFlip).toBeLessThan(0.9)
  })

  it('comes to a stop before turning rather than pivoting at a run', () => {
    const { rig, director } = setup(station('centre').x)
    director.goTo('shelf')
    run(director, rig, 2)
    expect(rig.facing).toBe(1)

    // Somewhere behind him, well past the hysteresis band.
    director.goTo('window')

    let movingWhenTurnStarted = 0
    let last = rig.worldX
    for (let t = 0; t < 2; t += FRAME) {
      director.update(FRAME, EMPTY_SIGNALS)
      rig.update(FRAME)
      if (rig.currentMotion === 'turnHop') {
        movingWhenTurnStarted = Math.abs(rig.worldX - last) / FRAME
        break
      }
      last = rig.worldX
    }
    // Stage units per second at the moment the hop begins.
    expect(movingWhenTurnStarted).toBeLessThan(0.5)
  })

  it('turns exactly once for a there-and-back journey', () => {
    const { rig, director } = setup(station('centre').x)
    director.goTo('shelf')
    const out = facingTrace(director, rig, 9)
    expect(out).toEqual([1])

    director.goTo('window')
    const back = facingTrace(director, rig, 12)
    expect(back).toEqual([1, -1])
  })
})

describe('not dithering', () => {
  it('will not turn round for a target barely behind it', () => {
    // Standing two and a half units past the desk, facing away from it. That is
    // inside the hysteresis band, so turning round costs more than the distance
    // is worth — he stops where he is rather than performing a whole hop for it.
    const { rig, director } = setup(station('desk').x + 2.5)
    expect(rig.facing).toBe(1)

    director.goTo('desk')
    run(director, rig, 2)
    expect(rig.facing).toBe(1)
    expect(rig.currentMotion).not.toBe('turnHop')
    // And he has not crept backwards to reach it either.
    expect(rig.worldX).toBeGreaterThan(station('desk').x + 2)
  })

  it('survives a narrow walk range without becoming a metronome', () => {
    // The desktop pet's window: 44 units, so almost everything is a reversal.
    const { rig, director } = setup(80)
    director.setWalkRange({ min: 58, max: 102 })

    let flips = 0
    let facing = rig.facing
    for (let t = 0; t < 30; t += FRAME) {
      director.update(FRAME, EMPTY_SIGNALS)
      rig.update(FRAME)
      if (rig.facing !== facing) {
        flips++
        facing = rig.facing
      }
    }
    // Ambient wandering picks a new spot every 6-16 seconds, so half a dozen
    // turns in thirty is generous. Dithering produced dozens.
    expect(flips).toBeLessThan(8)
  })

  it('does not hunt back and forth across its own destination', () => {
    const { rig, director } = setup(station('centre').x)
    director.goTo('desk')
    run(director, rig, 9)

    const settled = rig.worldX
    run(director, rig, 3)
    // Once he has stopped, he has stopped — no creeping toward a mark he has
    // already glided past.
    expect(Math.abs(rig.worldX - settled)).toBeLessThan(0.5)
  })
})

describe('the hop and the wind-up', () => {
  it('are one-shots the director owns rather than ambient clips', () => {
    expect(MOTIONS.turnHop.loop).toBeFalsy()
    expect(MOTIONS.windUp.loop).toBeFalsy()
    // Both have to outrank whatever loop was running or they never show.
    expect(MOTIONS.turnHop.priority).toBeGreaterThan(MOTIONS.walk.priority)
    expect(MOTIONS.windUp.priority).toBeGreaterThan(MOTIONS.walk.priority)
  })

  it('squash the sprite at the moment the hop hides the flip', () => {
    const flip = MOTIONS.turnHop.tracks.find((t) => t.param === 'scaleX')
    const atHalf = flip?.keys.find((k) => k.t === 0.5)
    expect(atHalf).toBeDefined()
    // Narrower than every other key in the clip: that is what makes it the
    // frame with the least sprite on screen to disagree with.
    for (const key of flip!.keys) {
      if (key.t !== 0.5) expect(key.v).toBeGreaterThan(atHalf!.v)
    }
  })
})
