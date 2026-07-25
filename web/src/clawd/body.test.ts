import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  BodyController,
  compactCue,
  normalizePhrase,
  phraseVisible,
  WALK_IN_PLACE_MS,
  type BodyCue,
  type BodyPlan,
  type BodyTarget,
} from './body'

const TURN = 'turn_1'

function cue(partial: Partial<BodyCue> & Pick<BodyCue, 'anchor'>): BodyCue {
  return { hold_ms: 1000, ...partial }
}

function plan(cues: BodyCue[], overrides: Partial<BodyPlan> = {}): BodyPlan {
  return { turn_id: TURN, plan_id: 'plan_1', cues, ...overrides }
}

/** Records what the controller asked an avatar to do, in order. */
function spy() {
  const applied: BodyCue[] = []
  let released = 0
  const target: BodyTarget = {
    applyCue: (c) => {
      applied.push(c)
    },
    releaseCue: () => {
      released += 1
    },
  }
  return {
    target,
    applied,
    get released() {
      return released
    },
  }
}

describe('phrase matching', () => {
  it('ignores case and runs of whitespace', () => {
    expect(normalizePhrase('  The   Desk\n')).toBe('the desk')
    expect(phraseVisible('I am at   THE\nDESK now', 'the desk')).toBe(true)
  })

  it('waits for the whole phrase to arrive', () => {
    expect(phraseVisible('let me che', 'check this')).toBe(false)
    expect(phraseVisible('let me check thi', 'check this')).toBe(false)
    expect(phraseVisible('let me check this out', 'check this')).toBe(true)
  })

  it('counts occurrences without overlapping them', () => {
    expect(phraseVisible('hahaha', 'ha', 3)).toBe(true)
    expect(phraseVisible('hahaha', 'ha', 4)).toBe(false)
    expect(phraseVisible('again and again', 'again', 2)).toBe(true)
    expect(phraseVisible('again and', 'again', 2)).toBe(false)
  })

  it('never matches an empty phrase', () => {
    expect(phraseVisible('anything at all', '   ')).toBe(false)
  })
})

describe('compact avatar fallback', () => {
  it('turns a station into a bounded walk on the spot', () => {
    expect(compactCue(cue({ anchor: 'reply_start', station: 'desk', hold_ms: 8000 }))).toEqual({
      walkMs: WALK_IN_PLACE_MS,
      motion: null,
    })
    expect(compactCue(cue({ anchor: 'reply_start', station: 'desk', hold_ms: 1000 }))).toEqual({
      walkMs: 450,
      motion: null,
    })
  })

  it('never lets the walk outlast the cue that asked for it', () => {
    const step = compactCue(cue({ anchor: 'reply_start', station: 'desk', hold_ms: 300 }))
    expect(step.walkMs).toBeLessThan(300)
  })

  it('gestures straight away when there is nowhere to go', () => {
    expect(compactCue(cue({ anchor: 'reply_end', motion: 'wave' }))).toEqual({
      walkMs: 0,
      motion: 'wave',
    })
  })
})

describe('BodyController', () => {
  let body: BodyController
  let avatar: ReturnType<typeof spy>

  beforeEach(() => {
    vi.useFakeTimers()
    body = new BodyController()
    body.now = () => Date.now()
    avatar = spy()
    body.registerTarget(avatar.target)
  })

  afterEach(() => {
    body.dispose()
    vi.useRealTimers()
  })

  it('fires reply_start on the first words, not on the plan', () => {
    body.startTurn(TURN)
    body.applyPlan(plan([cue({ anchor: 'reply_start', motion: 'perk' })]))
    expect(avatar.applied).toHaveLength(0)

    body.advance(TURN, 'Right')
    expect(avatar.applied.map((c) => c.motion)).toEqual(['perk'])
  })

  it('fires a phrase cue exactly when its phrase becomes visible, once', () => {
    body.startTurn(TURN)
    body.applyPlan(plan([cue({ anchor: 'phrase', phrase: 'over here', motion: 'wave' })]))

    body.advance(TURN, 'Look over')
    expect(avatar.applied).toHaveLength(0)

    body.advance(TURN, 'Look over here')
    expect(avatar.applied.map((c) => c.motion)).toEqual(['wave'])

    body.advance(TURN, 'Look over here, right over here.')
    expect(avatar.applied).toHaveLength(1)
  })

  it('honours the occurrence a cue asked for', () => {
    body.startTurn(TURN)
    body.applyPlan(
      plan([cue({ anchor: 'phrase', phrase: 'again', occurrence: 2, motion: 'nod' })]),
    )
    body.advance(TURN, 'again')
    expect(avatar.applied).toHaveLength(0)
    body.advance(TURN, 'again and again')
    expect(avatar.applied).toHaveLength(1)
  })

  it('releases the body when the hold expires', () => {
    body.startTurn(TURN)
    body.applyPlan(plan([cue({ anchor: 'reply_start', motion: 'perk', hold_ms: 800 })]))
    body.advance(TURN, 'hi')

    vi.advanceTimersByTime(799)
    expect(avatar.released).toBe(0)
    vi.advanceTimersByTime(2)
    expect(avatar.released).toBe(1)
  })

  it('queues cues that come due together and plays them in plan order', () => {
    body.startTurn(TURN)
    body.applyPlan(
      plan([
        cue({ anchor: 'reply_start', motion: 'perk', hold_ms: 500 }),
        cue({ anchor: 'phrase', phrase: 'hello', motion: 'wave', hold_ms: 500 }),
      ]),
    )
    // Both anchors are satisfied by the same update.
    body.advance(TURN, 'hello there')
    expect(avatar.applied.map((c) => c.motion)).toEqual(['perk'])

    vi.advanceTimersByTime(500)
    expect(avatar.applied.map((c) => c.motion)).toEqual(['perk', 'wave'])
    expect(avatar.released).toBe(1)
  })

  it('fires reply_end at the end and skips anchors that never appeared', () => {
    body.startTurn(TURN)
    body.applyPlan(
      plan([
        cue({ anchor: 'phrase', phrase: 'never said', motion: 'shrug' }),
        cue({ anchor: 'reply_end', motion: 'wave' }),
      ]),
    )
    body.advance(TURN, 'something else entirely')
    body.endTurn(TURN, 'something else entirely')

    expect(avatar.applied.map((c) => c.motion)).toEqual(['wave'])
  })

  it('takes a plan that arrived after the model already spoke', () => {
    body.startTurn(TURN)
    body.advance(TURN, 'Look over here now')
    body.applyPlan(
      plan([
        cue({ anchor: 'reply_start', motion: 'perk', hold_ms: 100 }),
        cue({ anchor: 'phrase', phrase: 'over here', motion: 'wave', hold_ms: 100 }),
      ]),
    )
    expect(avatar.applied.map((c) => c.motion)).toEqual(['perk'])
    vi.advanceTimersByTime(100)
    expect(avatar.applied.map((c) => c.motion)).toEqual(['perk', 'wave'])
  })

  it('lets a human take the controls and drops the rest of the plan', () => {
    body.startTurn(TURN)
    body.applyPlan(
      plan([
        cue({ anchor: 'reply_start', motion: 'perk', hold_ms: 5000 }),
        cue({ anchor: 'phrase', phrase: 'later', motion: 'wave' }),
      ]),
    )
    body.advance(TURN, 'hi')
    expect(avatar.applied).toHaveLength(1)

    body.humanTakeover()
    expect(avatar.released).toBe(1)

    body.advance(TURN, 'hi, and later on')
    vi.advanceTimersByTime(10_000)
    expect(avatar.applied).toHaveLength(1)
  })

  it('drops unfired cues when the turn is interrupted', () => {
    body.startTurn(TURN)
    body.applyPlan(
      plan([
        cue({ anchor: 'reply_start', motion: 'perk', hold_ms: 5000 }),
        cue({ anchor: 'reply_end', motion: 'wave' }),
      ]),
    )
    body.advance(TURN, 'hi')
    body.cancel(TURN, 'interrupted')
    expect(avatar.released).toBe(1)

    body.endTurn(TURN, 'hi')
    vi.advanceTimersByTime(10_000)
    expect(avatar.applied).toHaveLength(1)
  })

  it('ignores a cancellation aimed at a different turn', () => {
    body.startTurn(TURN)
    body.applyPlan(plan([cue({ anchor: 'reply_start', motion: 'perk', hold_ms: 5000 })]))
    body.advance(TURN, 'hi')
    body.cancel('turn_other', 'interrupted')
    expect(avatar.released).toBe(0)
  })

  it('drops the previous plan when a new turn starts', () => {
    body.startTurn(TURN)
    body.applyPlan(plan([cue({ anchor: 'reply_start', motion: 'perk', hold_ms: 5000 })]))
    body.advance(TURN, 'hi')

    body.startTurn('turn_2')
    expect(avatar.released).toBe(1)
    expect(body.activeCue).toBeNull()

    // The old turn's text can still trail in; it must not resurrect anything.
    body.advance(TURN, 'hi there')
    vi.advanceTimersByTime(10_000)
    expect(avatar.applied).toHaveLength(1)
  })

  it('lets audio timing take a turn away from the text stream', () => {
    body.startTurn(TURN)
    body.applyPlan(plan([cue({ anchor: 'phrase', phrase: 'over here', motion: 'wave' })]))

    // Playback has only reached the first word.
    body.advance(TURN, 'Look', 'audio')
    // The whole reply is already on the socket, but it has not been spoken.
    body.advance(TURN, 'Look over here now', 'text')
    expect(avatar.applied).toHaveLength(0)

    body.advance(TURN, 'Look over here', 'audio')
    expect(avatar.applied.map((c) => c.motion)).toEqual(['wave'])
  })

  it('never rewinds on an out-of-order update', () => {
    body.startTurn(TURN)
    body.applyPlan(plan([cue({ anchor: 'phrase', phrase: 'over here', motion: 'wave' })]))
    body.advance(TURN, 'Look over here now')
    expect(avatar.applied).toHaveLength(1)
    body.advance(TURN, 'Look')
    expect(avatar.applied).toHaveLength(1)
  })

  it('drops a plan that outlived its own deadline', () => {
    let clock = 1_000
    body.now = () => clock
    body.startTurn(TURN)
    body.applyPlan(plan([cue({ anchor: 'phrase', phrase: 'late', motion: 'wave' })], {
      expires_ms: 5_000,
    }))

    clock += 6_000
    body.advance(TURN, 'much too late')
    expect(avatar.applied).toHaveLength(0)
  })

  it('brings an avatar mounted mid-cue into what is already happening', () => {
    body.startTurn(TURN)
    body.applyPlan(plan([cue({ anchor: 'reply_start', motion: 'perk', hold_ms: 5000 })]))
    body.advance(TURN, 'hi')

    const late = spy()
    const unregister = body.registerTarget(late.target)
    expect(late.applied.map((c) => c.motion)).toEqual(['perk'])

    vi.advanceTimersByTime(5000)
    expect(late.released).toBe(1)

    unregister()
    body.startTurn('turn_3')
    expect(late.released).toBe(1)
  })

  it('keeps going when one avatar throws', () => {
    body.registerTarget({
      applyCue: () => {
        throw new Error('canvas is gone')
      },
      releaseCue: () => {
        throw new Error('canvas is gone')
      },
    })
    body.startTurn(TURN)
    body.applyPlan(plan([cue({ anchor: 'reply_start', motion: 'perk', hold_ms: 100 })]))
    body.advance(TURN, 'hi')
    expect(avatar.applied).toHaveLength(1)
    vi.advanceTimersByTime(100)
    expect(avatar.released).toBe(1)
  })

  it('ignores a plan with no cues at all', () => {
    body.startTurn(TURN)
    body.applyPlan(plan([]))
    body.advance(TURN, 'hi')
    body.endTurn(TURN, 'hi')
    expect(avatar.applied).toHaveLength(0)
  })
})
