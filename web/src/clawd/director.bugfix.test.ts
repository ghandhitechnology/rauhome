import { beforeEach, describe, expect, it } from 'vitest'

import type { BodyCue } from './body'
import { Director, EMPTY_SIGNALS, type Signals } from './director'
import type { MotionName } from './motions'
import { ClawdRig } from './rig'
import { station } from './room'

const FRAME = 1 / 60

function cue(partial: Partial<BodyCue> & Pick<BodyCue, 'anchor'>): BodyCue {
  return { hold_ms: 2000, ...partial }
}

/** Mirrors the runner in director.test.ts: rig ticked alongside the director. */
function run(
  director: Director,
  rig: ClawdRig,
  seconds: number,
  signals: Signals = EMPTY_SIGNALS,
) {
  for (let t = 0; t < seconds; t += FRAME) {
    director.update(FRAME, signals)
    rig.update(FRAME)
  }
}

describe('Director bugfixes', () => {
  let rig: ClawdRig
  let director: Director

  beforeEach(() => {
    rig = new ClawdRig()
    director = new Director(rig, 'room')
    director.manual = true
  })

  it('settles out of the walk once a station-only cue arrives', () => {
    director.manual = false
    rig.worldX = station('centre').x
    // A cue with somewhere to be but nothing to do there: walk, then stand.
    director.applyCue(cue({ anchor: 'reply_start', station: 'window' }))
    run(director, rig, 8)
    expect(Math.abs(rig.worldX - station('window').x)).toBeLessThanOrEqual(1.5)
    // The walk clip's work is done — marching on the spot at the destination
    // reads as a treadmill, not as having arrived.
    expect(rig.currentMotion).not.toBe('walk')
    expect(rig.currentMotion).toBe('idle')
  })

  it('replays a finished one-shot when it is asked for again', () => {
    expect(rig.play('wave')).toBe(true)
    for (let t = 0; t < 3; t += FRAME) rig.update(FRAME)
    expect(rig.player.isFinished).toBe(true)

    expect(rig.play('wave')).toBe(true)
    // It must actually have started again, not just claimed to.
    expect(rig.player.isFinished).toBe(false)
    expect(rig.player.progress).toBeLessThan(1)
  })

  it('does not treat a finished one-shot as still playing when swapping loops', () => {
    director.force('stretch')
    run(director, rig, 4) // stretch runs 2.4s
    expect(rig.currentMotion).toBe('stretch')
    expect(rig.player.isFinished).toBe(true)

    // The ambient picker landing on the same clip again must replay it, not
    // leave him frozen on its last frame for the next decision cycle.
    const loops = director as unknown as {
      setLoop(name: MotionName, restart?: boolean): void
    }
    loops.setLoop('stretch')
    expect(rig.player.isFinished).toBe(false)
  })

  it('does not restart the gait clip on the doorstep', () => {
    director.manual = false
    rig.worldX = station('centre').x
    const calls: { name: string; restart?: boolean }[] = []
    const original = rig.play.bind(rig)
    rig.play = (name, opts = {}) => {
      calls.push({ name, restart: opts.restart })
      return original(name, opts)
    }

    director.applyCue(cue({ anchor: 'reply_start', motion: 'carry', station: 'desk' }))
    run(director, rig, 8)
    expect(Math.abs(rig.worldX - station('desk').x)).toBeLessThanOrEqual(1.5)
    // The carry clip carried him the whole way; restarting it for the single
    // frame before the pose swap is a stumble, not an arrival.
    expect(calls.filter((c) => c.name === 'carry' && c.restart)).toHaveLength(0)
  })
})
