/**
 * The board's own life cycle, with the room stubbed out.
 *
 * Most of this is the card table's story with the deal taken out, and it is
 * worth pinning again rather than assumed: the two stores are separate objects
 * and nothing but a test says they agree about the order things happen in.
 *
 * Two of these are about the seam between the two games rather than about
 * chess, and both are things that were wrong. There is one surface and one
 * body, and the server swaps the games either way round — asking for a board
 * puts the cards away, asking for cards puts the board away — so for about a
 * second the room is clearing one table while raising the other. The table
 * going away must not take the arriving one down with it. And a pose that is
 * meant to be held has to be let go of when the same seat starts a new game,
 * because nothing else is ever going to.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CHESS_SURFACE } from '../../clawd/chessTableLayer'
import { KITTENS_SURFACE } from '../../clawd/gameTableLayer'
import { gameBridge, type GameResult, type TableChoreo } from '../../clawd/gameBridge'
import { gameStore, phaseStore, type TableState } from './useGame'

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
    startDeal: () => {
      calls.push('startDeal')
      return []
    },
    dismiss: (o?: { fast?: boolean; result?: GameResult }) => {
      calls.push(`dismiss(${o?.fast ? 'fast' : 'slow'},${o?.result ?? 'none'})`)
      return new Promise<void>((r) => {
        stand = r
      })
    },
    observe: () => {},
    settle: () => {
      calls.push('settle')
    },
  }
  return { choreo, calls, seated: () => seat(), stood: () => stand() }
}

const BOARD = { game_id: 'c1', fen: '', moves: [] } as unknown as TableState

let fake: ReturnType<typeof fakeChoreo>

beforeEach(() => {
  fake = fakeChoreo()
  gameBridge.registerChoreo(fake.choreo)
  vi.spyOn(gameStore, 'start').mockImplementation(async () => {
    gameStore.set(BOARD)
  })
  vi.spyOn(gameStore, 'leave').mockImplementation(async () => {
    gameStore.set(null)
  })
})

afterEach(async () => {
  gameBridge.activate(CHESS_SURFACE)
  const done = phaseStore.end({ fast: true })
  fake.stood()
  await done
  gameStore.set(null)
  gameBridge.activate(null)
  gameBridge.registerChoreo(null)
  vi.restoreAllMocks()
})

describe('pressing Chess', () => {
  it('puts the table up before he starts walking to it', async () => {
    void phaseStore.begin()
    // Both already in flight, and the surface raised first: the room paints
    // whichever table the bridge is holding, and he must not spend the walk
    // approaching a card table.
    expect(gameBridge.surface).toBe(CHESS_SURFACE)
    expect(phaseStore.get()).toBe('summoning')
    expect(gameStore.start).toHaveBeenCalledTimes(1)
    expect(fake.calls).toContain('summon')
  })

  it('waits for the walk even once the position has arrived', async () => {
    void phaseStore.begin()
    await flush()
    expect(gameStore.get()).not.toBeNull()
    expect(phaseStore.get()).toBe('summoning')

    fake.seated()
    await flush()
    // No dealing phase: the position simply arrives.
    expect(phaseStore.get()).toBe('playing')
  })

  it('ignores a second press', async () => {
    void phaseStore.begin()
    void phaseStore.begin()
    await flush()
    expect(gameStore.start).toHaveBeenCalledTimes(1)
  })
})

describe('a board that was already there', () => {
  it('seats him with no ritual on a reload', () => {
    phaseStore.adopt()
    expect(gameBridge.surface).toBe(CHESS_SURFACE)
    expect(fake.calls).toEqual(['seatInstantly'])
    expect(phaseStore.get()).toBe('playing')
  })

  it('gives him the whole walk when he sets it up himself', async () => {
    void phaseStore.arrive()
    expect(gameBridge.surface).toBe(CHESS_SURFACE)
    expect(fake.calls).toContain('summon')
    expect(phaseStore.get()).toBe('summoning')
    fake.seated()
    await flush()
    expect(phaseStore.get()).toBe('playing')
  })
})

describe('setting them up again', () => {
  it('lets go of the pose he ended the last game in', async () => {
    void phaseStore.begin()
    fake.seated()
    await flush()
    fake.calls.length = 0

    await phaseStore.again()
    // Without this he sets the new position up still folded over the old one:
    // `slump` is held on purpose and a new game emits no beat to replace it.
    expect(fake.calls).toContain('settle')
  })

  it('only works from a game in progress', async () => {
    await phaseStore.again()
    expect(gameStore.start).not.toHaveBeenCalled()
  })
})

describe('leaving', () => {
  it('clears the server board and unwinds the room together', async () => {
    void phaseStore.begin()
    fake.seated()
    await flush()

    const done = phaseStore.leave('win')
    expect(phaseStore.get()).toBe('ending')
    fake.stood()
    await done
    expect(phaseStore.get()).toBe('idle')
    expect(gameBridge.surface).toBeNull()
    expect(fake.calls).toContain('dismiss(slow,win)')
  })

  it('stands him up when the board disappears from under him', async () => {
    void phaseStore.begin()
    fake.seated()
    await flush()

    gameStore.set(null)
    await flush()
    expect(phaseStore.get()).toBe('ending')
    fake.stood()
    await flush()
    expect(phaseStore.get()).toBe('idle')
  })
})

describe('handing the room to the other game', () => {
  it('does not take down a table that is no longer its own', async () => {
    void phaseStore.begin()
    fake.seated()
    await flush()

    // The cards came out: the server ended this game, and the card table has
    // already raised its own surface by the time this one finishes standing up.
    const done = phaseStore.end({ fast: true })
    gameBridge.activate(KITTENS_SURFACE)
    fake.stood()
    await done

    expect(phaseStore.get()).toBe('idle')
    expect(gameBridge.surface).toBe(KITTENS_SURFACE)
  })
})
