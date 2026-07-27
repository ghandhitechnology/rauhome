/**
 * Coming back to a game that outlived its room (Face's re-seat path).
 *
 * The phase worth pinning is 'summoning': it belongs to a begin()/arrive()
 * whose choreographer went away with the last page, and left alone it never
 * advances — him seated at an empty table, the cards never appearing.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { gameBridge, type GameResult, type TableChoreo } from '../clawd/gameBridge'
import { phaseStore } from '../games/kittens/phase'
import { gameStore, type TableState } from '../games/kittens/useGame'
import { reseatIntoGame } from './Face'

function fakeChoreo() {
  const calls: string[] = []
  const choreo: TableChoreo = {
    summon: () => {
      calls.push('summon')
      // Never resolves: the room whose frame loop would walk him is gone.
      return new Promise<void>(() => {})
    },
    seatInstantly: () => {
      calls.push('seatInstantly')
    },
    startDeal: () => [],
    dismiss: (o?: { fast?: boolean; result?: GameResult }) => {
      calls.push(`dismiss(${o?.fast ? 'fast' : 'slow'},${o?.result ?? 'none'})`)
      // A fresh choreographer has nothing to stand up from.
      return Promise.resolve()
    },
    observe: () => {},
  }
  return { choreo, calls }
}

const TABLE = { game_id: 'g1', hand: [], hand_counts: { user: 0, rau: 0 } } as unknown as TableState

beforeEach(() => {
  gameStore.set(TABLE)
})

afterEach(async () => {
  // Leave the singletons the way the test found them.
  await phaseStore.end({ fast: true })
  gameStore.set(null)
  gameBridge.registerChoreo(null)
})

describe('re-seating a game that outlived the room', () => {
  it('adopts with no ritual when the phase is idle', async () => {
    const room = fakeChoreo()
    gameBridge.registerChoreo(room.choreo)

    await reseatIntoGame()

    expect(room.calls).toEqual(['seatInstantly'])
    expect(phaseStore.get()).toBe('playing')
    expect(gameBridge.active).toBe(true)
  })

  it('seats a fresh choreographer over a game in progress without touching the phase', async () => {
    const old = fakeChoreo()
    gameBridge.registerChoreo(old.choreo)
    phaseStore.adopt()
    expect(phaseStore.get()).toBe('playing')

    // Navigated away mid-game and back: a new choreographer registers while
    // the phase is still 'playing', and he still has to be sat down.
    const fresh = fakeChoreo()
    gameBridge.registerChoreo(fresh.choreo)
    await reseatIntoGame()

    expect(fresh.calls).toEqual(['seatInstantly'])
    expect(phaseStore.get()).toBe('playing')
  })

  it('unwinds a summoning phase whose choreographer is gone', async () => {
    // Play pressed (or he dealt himself in), then the room was left mid-walk:
    // the ritual's promise belongs to a choreographer that no longer exists.
    const old = fakeChoreo()
    gameBridge.registerChoreo(old.choreo)
    void phaseStore.arrive()
    expect(phaseStore.get()).toBe('summoning')

    // Back in the room: a brand-new choreographer registers.
    const fresh = fakeChoreo()
    gameBridge.registerChoreo(fresh.choreo)
    await reseatIntoGame()

    // The dangling ritual was answered and unwound, and he was seated through
    // the no-ritual path — the phase can deal the cards now.
    expect(fresh.calls).toEqual(['dismiss(fast,none)', 'seatInstantly'])
    expect(phaseStore.get()).toBe('playing')
    expect(gameBridge.active).toBe(true)
  })
})
