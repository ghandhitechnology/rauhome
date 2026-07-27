/**
 * The ritual, driven the way the canvas drives it.
 *
 * Every test here runs the real rig, director and scene through a real frame
 * loop, because the whole point of the machine is what happens when those
 * three disagree — a clip still playing, a walk not finished, a camera still
 * moving — and a stubbed rig has no opinions to disagree with.
 */
import { beforeEach, describe, expect, it } from 'vitest'

import { Director, EMPTY_SIGNALS } from './director'
import { GameChoreographer, type ChoreoState } from './gameChoreographer'
import { GAME_CAMERA, GAME_DIM } from './gameTableLayer'
import { ClawdRig } from './rig'
import { station } from './room'
import { Scene } from './scene'

const FRAME = 1 / 60

function harness() {
  const rig = new ClawdRig()
  const director = new Director(rig, 'room')
  const scene = new Scene()
  scene.layout(1440, 900, 1, {})
  const choreo = new GameChoreographer(rig, director)

  /** One frame, in the order `ClawdRoom` runs them. */
  const step = (seconds: number) => {
    for (let t = 0; t < seconds; t += FRAME) {
      choreo.update(FRAME, scene)
      director.update(FRAME, EMPTY_SIGNALS)
      rig.update(FRAME)
      scene.update(FRAME, rig.worldX, {
        follow: true,
        cameraTarget: choreo.cameraTarget,
      })
    }
  }
  return { rig, director, scene, choreo, step }
}

/** Run until the machine reaches `want`, or give up. */
function stepUntil(
  h: ReturnType<typeof harness>,
  want: ChoreoState,
  limit = 20,
): boolean {
  for (let t = 0; t < limit; t += 0.1) {
    if (h.choreo.state === want) return true
    h.step(0.1)
  }
  return h.choreo.state === want
}

describe('sitting down', () => {
  it('walks over, sits, frames the shot, and reports back', async () => {
    const h = harness()
    let seated = false
    void h.choreo.summon().then(() => {
      seated = true
    })

    expect(h.choreo.state).toBe('perk')
    // The body is his the moment the ritual starts, not once he arrives.
    expect(h.director.manual).toBe(true)

    expect(stepUntil(h, 'playing')).toBe(true)
    await Promise.resolve()

    expect(seated).toBe(true)
    expect(h.rig.worldX).toBeCloseTo(station('table').x, 0)
    expect(h.rig.currentMotion).toBe('sitTable')
    expect(h.choreo.cameraTarget).toEqual(GAME_CAMERA)
    expect(h.choreo.presence).toBeGreaterThan(0.95)
    expect(h.choreo.dim).toBeGreaterThan(GAME_DIM * 0.9)
    expect(h.scene.camera.zoom).toBeCloseTo(GAME_CAMERA.zoom, 1)
  })

  it('passes through every state in order', () => {
    const h = harness()
    const seen: ChoreoState[] = []
    void h.choreo.summon()
    for (let t = 0; t < 20 && h.choreo.state !== 'playing'; t += FRAME) {
      if (seen[seen.length - 1] !== h.choreo.state) seen.push(h.choreo.state)
      h.step(FRAME)
    }
    expect(seen).toEqual(['perk', 'walk', 'sitting', 'framing'])
  })

  it('takes no more than about four seconds from the middle of the room', () => {
    const h = harness()
    void h.choreo.summon()
    let elapsed = 0
    while (h.choreo.state !== 'playing' && elapsed < 20) {
      h.step(FRAME)
      elapsed += FRAME
    }
    expect(h.choreo.state).toBe('playing')
    expect(elapsed).toBeLessThan(5)
  })

  it('is idempotent — a second Play changes nothing', () => {
    const h = harness()
    void h.choreo.summon()
    h.step(0.2)
    const state = h.choreo.state
    void h.choreo.summon()
    expect(h.choreo.state).toBe(state)
  })

  it('seats him instantly when a game was already going', () => {
    const h = harness()
    h.choreo.seatInstantly()
    expect(h.choreo.state).toBe('playing')
    expect(h.rig.worldX).toBe(station('table').x)
    expect(h.choreo.presence).toBe(1)
    expect(h.choreo.cameraTarget).toEqual(GAME_CAMERA)
  })

  it('seatInstantly is idempotent — adopting twice changes nothing', () => {
    const h = harness()
    h.choreo.seatInstantly()
    const x = h.rig.worldX
    h.choreo.seatInstantly()
    expect(h.choreo.state).toBe('playing')
    expect(h.rig.worldX).toBe(x)
  })
})

describe('dealing', () => {
  it('gives one flick per card, in order', () => {
    const h = harness()
    h.choreo.seatInstantly()
    const times = h.choreo.startDeal(7)
    expect(times).toHaveLength(7)
    expect([...times]).toEqual([...times].sort((a, b) => a - b))
    expect(h.rig.currentMotion).toBe('dealFlick')
  })

  it('deals nothing for no cards', () => {
    const h = harness()
    h.choreo.seatInstantly()
    expect(h.choreo.startDeal(0)).toEqual([])
  })

  it('keeps the flourish going for every lap of a long deal', () => {
    const h = harness()
    h.choreo.seatInstantly()
    // Sixteen cards over four flicks a lap is four laps — about five seconds.
    h.choreo.startDeal(16)
    // Past the first lap (1.3s) he is still dealing, not back in his seat.
    h.step(1.5)
    expect(h.rig.currentMotion).toBe('dealFlick')
    // Once the last card has left, he settles back into the seat.
    h.step(4.5)
    expect(h.rig.currentMotion).toBe('sitTable')
  })
})

describe('beats', () => {
  it('plays what the table did, one at a time and in order', () => {
    const h = harness()
    h.choreo.seatInstantly()
    h.choreo.observe(['draw', 'play'])
    h.step(0.05)
    expect(h.rig.currentMotion).toBe('reachDraw')
    // The second beat waits for the first to finish and for the gap after it.
    h.step(1.2)
    expect(h.rig.currentMotion).toBe('flickPlay')
    // And then he is sitting there holding his cards again, rather than
    // frozen on the last frame of the flick.
    h.step(1.5)
    expect(h.rig.currentMotion).toBe('sitTable')
  })

  it('holds the pose the game ended on', () => {
    const h = harness()
    h.choreo.seatInstantly()
    h.choreo.observe(['slump'])
    h.step(3)
    // Still slumped while you read the result, not tidied back into the seat.
    expect(h.rig.currentMotion).toBe('slumpLoss')
  })

  it('collapses a burst that repeats itself', () => {
    const h = harness()
    h.choreo.seatInstantly()
    h.choreo.observe(['draw', 'draw', 'draw'])
    h.step(0.05)
    expect(h.rig.currentMotion).toBe('reachDraw')
    // One draw happened, so one draw is played; the rest were the same push.
    h.step(3)
    expect(h.rig.currentMotion).toBe('sitTable')
  })

  it('lets the kitten cut the queue', () => {
    const h = harness()
    h.choreo.seatInstantly()
    h.choreo.observe(['draw', 'play', 'nope'])
    h.choreo.observe(['kitten'])
    h.step(0.05)
    expect(h.rig.currentMotion).toBe('kittenRecoil')
  })

  it('ignores beats once the table is gone', () => {
    const h = harness()
    h.choreo.observe(['kitten'])
    h.step(0.2)
    expect(h.rig.currentMotion).not.toBe('kittenRecoil')
  })

  it('remembers how it went, so the exit knows without being told', async () => {
    const h = harness()
    h.choreo.seatInstantly()
    h.choreo.observe(['cheer'])
    h.step(2.5)
    void h.choreo.dismiss()
    expect(stepUntil(h, 'idle')).toBe(true)
    await Promise.resolve()
    expect(h.director.manual).toBe(false)
  })
})

describe('standing back up', () => {
  it('unwinds the camera, the table and the room', async () => {
    const h = harness()
    void h.choreo.summon()
    stepUntil(h, 'playing')

    let done = false
    void h.choreo.dismiss({ result: 'win' }).then(() => {
      done = true
    })
    expect(stepUntil(h, 'idle')).toBe(true)
    await Promise.resolve()

    expect(done).toBe(true)
    expect(h.choreo.cameraTarget).toBeNull()
    expect(h.choreo.presence).toBeLessThan(0.05)
    expect(h.director.manual).toBe(false)
    h.step(0.5)
    expect(h.choreo.dim).toBeLessThan(0.02)
  })

  it('ends cleanly from every state it can be interrupted in', async () => {
    // Leaving mid-walk, mid-sit, mid-camera-push and mid-hand all have to
    // land in the same place: a room that is his again, with nothing stuck.
    for (const at of ['perk', 'walk', 'sitting', 'framing', 'playing'] as ChoreoState[]) {
      const h = harness()
      void h.choreo.summon()
      expect(stepUntil(h, at)).toBe(true)

      void h.choreo.dismiss({ fast: true })
      expect(stepUntil(h, 'idle')).toBe(true)
      await Promise.resolve()

      expect(h.director.manual, `stuck manual after leaving at ${at}`).toBe(false)
      expect(h.choreo.cameraTarget, `stuck camera after leaving at ${at}`).toBeNull()
      expect(h.choreo.presence, `orphaned table after leaving at ${at}`).toBeLessThan(0.05)
    }
  })

  it('skips getting up from a chair he never reached', async () => {
    const h = harness()
    void h.choreo.summon()
    h.step(0.2)
    expect(h.choreo.state).toBe('perk')
    void h.choreo.dismiss({ fast: true })
    // Straight to releasing: there is no seat to stand out of.
    expect(h.choreo.state).toBe('releasing')
    expect(stepUntil(h, 'idle')).toBe(true)
    await Promise.resolve()
    expect(h.director.manual).toBe(false)
  })

  it('does nothing when there was no table', () => {
    const h = harness()
    expect(h.choreo.state).toBe('idle')
    void h.choreo.dismiss()
    expect(h.choreo.state).toBe('idle')
  })

  it('resolves the walk it was waiting on when the ritual is cancelled', async () => {
    // begin() awaits the summon promise alongside the deal; a game that ends
    // mid-walk must still answer it or the table stack wedges for good.
    const h = harness()
    let seated = false
    void h.choreo.summon().then(() => {
      seated = true
    })
    h.step(1)
    expect(h.choreo.state).toBe('walk')

    void h.choreo.dismiss({ fast: true })
    expect(stepUntil(h, 'idle')).toBe(true)
    await Promise.resolve()
    expect(seated).toBe(true)
  })

  it('does not leave him walking to a table that is gone', async () => {
    const h = harness()
    void h.choreo.summon()
    h.step(1)
    expect(h.choreo.state).toBe('walk')

    void h.choreo.dismiss({ fast: true })
    expect(stepUntil(h, 'idle')).toBe(true)
    await Promise.resolve()

    // The directed goTo is cancelled with the ritual: he never finishes the
    // trip to where the table was, and never sits down at bare floor.
    h.step(2)
    expect(h.director.targetStation).not.toBe('table')
    expect(h.rig.currentMotion).not.toBe('sitTable')
  })

  it('survives being told to leave twice', async () => {
    const h = harness()
    void h.choreo.summon()
    stepUntil(h, 'playing')
    void h.choreo.dismiss()
    void h.choreo.dismiss({ fast: true })
    expect(stepUntil(h, 'idle')).toBe(true)
    await Promise.resolve()
    expect(h.director.manual).toBe(false)
  })
})

describe('the eyes', () => {
  let h: ReturnType<typeof harness>
  beforeEach(() => {
    h = harness()
  })

  it('are held for the whole game, so conversing cannot pull them back', () => {
    void h.choreo.summon()
    expect(h.director.gazeHeld).toBe(true)
    stepUntil(h, 'playing')
    expect(h.director.gazeHeld).toBe(true)
  })

  it('are handed back when he gets up', async () => {
    void h.choreo.summon()
    stepUntil(h, 'playing')
    void h.choreo.dismiss({ fast: true })
    stepUntil(h, 'idle')
    await Promise.resolve()
    expect(h.director.gazeHeld).toBe(false)
  })
})
