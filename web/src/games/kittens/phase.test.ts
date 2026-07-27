/**
 * The table's own life cycle, with the room stubbed out.
 *
 * What is worth pinning here is the ordering: the deal and the walk run at
 * the same time and the cards wait for whichever finishes last, a deal that
 * fails still has to put him back on his feet, and leaving at any point has
 * to end in a room with no table in it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { gameBridge, type GameResult, type TableChoreo } from '../../clawd/gameBridge'
import { phaseStore } from './phase'
import { gameStore, type TableState } from './useGame'

const flush = () => new Promise((r) => setTimeout(r, 0))

function fakeChoreo() {
  let seat = () => {}
  let stand = () => {}
  const calls: string[] = []
  const choreo: TableChoreo = {
    summon: () => {
      calls.push('summon')
      return new Promise<void>((r) => {
        seat = r
      })
    },
    seatInstantly: () => {
      calls.push('seatInstantly')
    },
    startDeal: (n) => {
      calls.push(`startDeal(${n})`)
      return []
    },
    dismiss: (o?: { fast?: boolean; result?: GameResult }) => {
      calls.push(`dismiss(${o?.fast ? 'fast' : 'slow'},${o?.result ?? 'none'})`)
      return new Promise<void>((r) => {
        stand = r
      })
    },
    observe: () => {},
  }
  return {
    choreo,
    calls,
    seated: () => seat(),
    stood: () => stand(),
  }
}

const TABLE = { game_id: 'g1', hand: [], hand_counts: { user: 0, rau: 0 } } as unknown as TableState

let fake: ReturnType<typeof fakeChoreo>

beforeEach(() => {
  fake = fakeChoreo()
  gameBridge.registerChoreo(fake.choreo)
  vi.spyOn(gameStore, 'deal').mockImplementation(async () => {
    gameStore.set(TABLE)
  })
  vi.spyOn(gameStore, 'leave').mockImplementation(async () => {
    gameStore.set(null)
  })
})

afterEach(async () => {
  // Every test has to leave the singleton the way it found it.
  const done = phaseStore.end({ fast: true })
  fake.stood()
  await done
  gameStore.set(null)
  gameBridge.registerChoreo(null)
  vi.restoreAllMocks()
})

describe('pressing Play', () => {
  it('posts the deal and starts the walk at the same time', async () => {
    void phaseStore.begin()
    // Both are already in flight before anything has been awaited.
    expect(phaseStore.get()).toBe('summoning')
    expect(gameBridge.active).toBe(true)
    expect(gameStore.deal).toHaveBeenCalledTimes(1)
    expect(fake.calls).toContain('summon')
  })

  it('waits for the walk even once the cards have arrived', async () => {
    void phaseStore.begin()
    await flush()
    // The server has answered; he is still crossing the room.
    expect(gameStore.get()).not.toBeNull()
    expect(phaseStore.get()).toBe('summoning')

    fake.seated()
    await flush()
    expect(phaseStore.get()).toBe('dealing')
  })

  it('hands over once every card has landed', async () => {
    void phaseStore.begin()
    fake.seated()
    await flush()
    phaseStore.dealt()
    expect(phaseStore.get()).toBe('playing')
  })

  it('ignores a second press', async () => {
    void phaseStore.begin()
    void phaseStore.begin()
    await flush()
    expect(gameStore.deal).toHaveBeenCalledTimes(1)
  })
})

describe('when the deal fails', () => {
  it('puts him back on his feet and says why', async () => {
    vi.spyOn(gameStore, 'deal').mockRejectedValue(new Error('hub is down'))
    const done = phaseStore.begin()
    fake.seated()
    await flush()
    fake.stood()
    await done

    expect(phaseStore.get()).toBe('idle')
    expect(phaseStore.error).toBe('hub is down')
    expect(gameBridge.active).toBe(false)
    expect(fake.calls.some((c) => c.startsWith('dismiss'))).toBe(true)
  })
})

describe('a table that was already there', () => {
  it('seats him with no ritual on a reload', () => {
    phaseStore.adopt()
    expect(fake.calls).toEqual(['seatInstantly'])
    expect(phaseStore.get()).toBe('playing')
    expect(gameBridge.active).toBe(true)
  })

  it('re-seats a fresh room over a game already in progress', () => {
    phaseStore.adopt()
    expect(fake.calls).toEqual(['seatInstantly'])
    // Navigated away from /face mid-game and back: a new choreographer
    // registers while the phase is still 'playing', and he still has to be
    // sat down — adopting again is what puts him there.
    const fresh = fakeChoreo()
    gameBridge.registerChoreo(fresh.choreo)
    phaseStore.adopt()
    expect(fresh.calls).toEqual(['seatInstantly'])
    expect(phaseStore.get()).toBe('playing')
    // Hand the original back so the afterEach unwind lands on it.
    gameBridge.registerChoreo(fake.choreo)
  })

  it('gives him the whole walk when he deals himself in', async () => {
    void phaseStore.arrive()
    expect(phaseStore.get()).toBe('summoning')
    // He already dealt; nobody posts a second one.
    expect(gameStore.deal).not.toHaveBeenCalled()
    fake.seated()
    await flush()
    expect(phaseStore.get()).toBe('dealing')
  })
})

describe('dealing again', () => {
  it('skips the ritual — he never got up', async () => {
    phaseStore.adopt()
    await phaseStore.redeal()
    expect(phaseStore.get()).toBe('dealing')
    expect(fake.calls).toEqual(['seatInstantly'])
  })

  it('only works from a game in progress', async () => {
    await phaseStore.redeal()
    expect(phaseStore.get()).toBe('idle')
  })
})

describe('leaving', () => {
  it('clears the server table and unwinds the room together', async () => {
    phaseStore.adopt()
    const done = phaseStore.leave('win')
    expect(phaseStore.get()).toBe('ending')
    expect(gameStore.leave).toHaveBeenCalled()
    expect(fake.calls).toContain('dismiss(slow,win)')

    fake.stood()
    await done
    expect(phaseStore.get()).toBe('idle')
    expect(gameBridge.active).toBe(false)
    expect(gameBridge.hoverPoint).toBeNull()
  })

  it('cancels a ritual that was still starting', async () => {
    const begun = phaseStore.begin()
    const left = phaseStore.end({ fast: true })
    expect(phaseStore.get()).toBe('ending')
    fake.seated()
    fake.stood()
    await Promise.all([begun, left])
    // The deal landed, but he already walked away from it.
    expect(phaseStore.get()).toBe('idle')
  })

  it('stands him up when the game disappears from under him', async () => {
    gameStore.set(TABLE)
    phaseStore.adopt()
    // `game_ended` from the hub, or a socket that came back empty.
    gameStore.set(null)
    await flush()
    expect(phaseStore.get()).toBe('ending')
    fake.stood()
    await flush()
    expect(phaseStore.get()).toBe('idle')
  })

  it('stands him up when the game ends while he is still walking to it', async () => {
    const begun = phaseStore.begin()
    await flush()
    expect(phaseStore.get()).toBe('summoning')
    // `game_ended` from the hub before he ever reached the chair: the walk
    // must not complete into a game that is gone.
    gameStore.set(null)
    await flush()
    expect(phaseStore.get()).toBe('ending')
    expect(fake.calls).toContain('dismiss(fast,none)')

    fake.stood()
    await flush()
    expect(phaseStore.get()).toBe('idle')
    // And the begin that was awaiting the walk is answered, not left dangling.
    fake.seated()
    await begun
    expect(phaseStore.get()).toBe('idle')
  })
})

describe('without a room to sit in', () => {
  it('still runs, so the table works before the canvas is up', async () => {
    gameBridge.registerChoreo(null)
    await phaseStore.begin()
    expect(phaseStore.get()).toBe('dealing')
    phaseStore.dealt()
    expect(phaseStore.get()).toBe('playing')
    await phaseStore.end()
    expect(phaseStore.get()).toBe('idle')
  })
})
