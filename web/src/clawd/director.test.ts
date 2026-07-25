import { beforeEach, describe, expect, it } from 'vitest'

import type { BodyCue } from './body'
import { Director, EMPTY_SIGNALS, type Signals } from './director'
import { ClawdRig } from './rig'
import { station } from './room'

const FRAME = 1 / 60

function cue(partial: Partial<BodyCue> & Pick<BodyCue, 'anchor'>): BodyCue {
  return { hold_ms: 2000, ...partial }
}

/**
 * Run the director for `seconds` of wall clock at a fixed frame rate.
 *
 * The rig has to be ticked alongside it, exactly as the canvas loop does:
 * without that, no clip ever finishes and every one-shot pins the body.
 */
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

/** Arrival has a deadband — he eases to a stop rather than hitting the mark. */
function expectStandingAt(rig: ClawdRig, id: Parameters<typeof station>[0]) {
  expect(Math.abs(rig.worldX - station(id).x)).toBeLessThanOrEqual(1.5)
}

describe('Director cues', () => {
  let rig: ClawdRig
  let director: Director

  beforeEach(() => {
    rig = new ClawdRig()
    director = new Director(rig, 'room')
    // Nothing here is about ambient wandering; hold him still until cued.
    director.manual = true
  })

  it('plays a cue motion immediately when there is nowhere to go', () => {
    director.applyCue(cue({ anchor: 'reply_start', motion: 'wave' }))
    expect(rig.currentMotion).toBe('wave')
    expect(director.cued).toBe(true)
  })

  it('walks to the station first and gestures on arrival', () => {
    director.manual = false
    rig.worldX = station('centre').x
    director.applyCue(cue({ anchor: 'reply_start', motion: 'type', station: 'desk' }))

    // Still travelling: the walk clip owns the body, not the gesture.
    director.update(FRAME, EMPTY_SIGNALS)
    expect(rig.currentMotion).toBe('walk')

    run(director, rig, 8)
    expectStandingAt(rig, 'desk')
    expect(rig.currentMotion).toBe('type')
  })

  it('keeps the spot it was sent to after the cue is released', () => {
    director.manual = false
    director.applyCue(cue({ anchor: 'reply_start', station: 'window' }))
    run(director, rig, 8)
    const arrived = rig.worldX
    expectStandingAt(rig, 'window')

    director.releaseCue()
    expect(director.cued).toBe(false)
    run(director, rig, 1)
    // No snap back to the middle of the room the instant control returns.
    expect(Math.abs(rig.worldX - arrived)).toBeLessThan(2)
  })

  it('aims the eyes where the cue said, and lets go afterwards', () => {
    const aims: unknown[] = []
    rig.setGaze = (aim) => aims.push(aim)

    director.applyCue(cue({ anchor: 'reply_start', gaze: 'floor', motion: 'think' }))
    director.update(FRAME, EMPTY_SIGNALS)
    expect(aims.at(-1)).toMatchObject({ y: 0.85 })

    director.releaseCue()
    director.update(FRAME, EMPTY_SIGNALS)
    expect(aims.at(-1)).toBeNull()
  })

  it('holds a looping cue pose for the whole cue', () => {
    director.manual = false
    director.applyCue(cue({ anchor: 'reply_start', motion: 'think' }))
    run(director, rig, 3)
    expect(rig.currentMotion).toBe('think')
  })

  it('does not freeze on the last frame of a finished one-shot', () => {
    director.manual = false
    director.applyCue(cue({ anchor: 'reply_start', motion: 'wave' }))
    run(director, rig, 6)
    expect(rig.currentMotion).not.toBe('wave')
    expect(director.cued).toBe(true)
  })

  it('outranks an ambient reaction but not an interruption', () => {
    director.manual = false
    director.applyCue(cue({ anchor: 'reply_start', motion: 'think' }))
    run(director, rig, 2)

    // A sentence tag would normally fire a nod; under a cue it must not.
    const tagged: Signals = { ...EMPTY_SIGNALS, sentenceTag: 'agree' }
    director.update(FRAME, tagged)
    expect(rig.currentMotion).toBe('think')

    // Being cut off is a different matter — that always lands.
    director.update(FRAME, { ...tagged, interruptedAt: Date.now() })
    expect(rig.currentMotion).toBe('recoil')
  })

  it('is not walked back to the centre by a reply arriving mid-cue', () => {
    director.manual = false
    director.applyCue(cue({ anchor: 'reply_start', station: 'shelf' }))
    run(director, rig, 8)
    expectStandingAt(rig, 'shelf')

    run(director, rig, 0.5, {
      ...EMPTY_SIGNALS,
      lastReplyAt: Date.now(),
      speech: 'here you go',
    })
    expect(director.targetStation).toBe('shelf')
  })

  it('is not dragged to the centre when conversation mode switches on', () => {
    director.manual = false
    director.applyCue(cue({ anchor: 'reply_start', station: 'shelf' }))
    run(director, rig, 8)
    director.setMode('conversing')
    run(director, rig, 0.5)
    expect(director.targetStation).toBe('shelf')
    expectStandingAt(rig, 'shelf')
  })

  it('returns to autonomous behaviour once released', () => {
    director.manual = false
    director.applyCue(cue({ anchor: 'reply_start', station: 'window', motion: 'gaze' }))
    run(director, rig, 8)
    expectStandingAt(rig, 'window')

    director.releaseCue()
    run(director, rig, 40)
    expect(director.cued).toBe(false)
    // The ambient behaviour has the room back: he has moved on from where the
    // cue parked him, or at least chosen for himself what to do there.
    expect(rig.currentMotion).not.toBeNull()
    expect(director.targetStation).toBeTruthy()
  })
})
