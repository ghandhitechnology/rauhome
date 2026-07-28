/**
 * Reading two positions as things his body does.
 *
 * A pure function over two server snapshots, which is the whole reason it is
 * its own module — but it is also the one place in the feature that could
 * quietly turn into a chess engine, so half of what is pinned here is what it
 * must *not* say. It reads captures off the two piece counts and checks off the
 * SAN, and it never evaluates anything: `blunder` is "a piece came off him and
 * nothing came back", not "that was a mistake".
 *
 * The other half is attribution. A single push can carry his move and yours,
 * and getting the alternation wrong is how he ends up slumping over a piece he
 * just won.
 */
import { describe, expect, it } from 'vitest'

import { diffBeats } from './beats'
import type { TableState } from './useGame'

/** He is black throughout, so "his move" is never the first one in a push. */
function tableOf(over: Partial<TableState> = {}): TableState {
  return {
    game_id: 'c1',
    phase: 'playing',
    fen: '3qk3/8/8/8/8/8/8/3QK3 w - - 0 1',
    turn: 'white',
    rau_color: 'black',
    user_color: 'white',
    your_turn: true,
    moves: [],
    last_move: null,
    check_square: null,
    thinking: null,
    offer: null,
    result: null,
    winner: null,
    over_reason: '',
    can_claim_draw: false,
    log: [],
    ...over,
  }
}

/** Mid-stare: his move, his delay running, a square he may be eyeing. */
function staring(hover: string | null): TableState {
  return tableOf({
    turn: 'black',
    your_turn: false,
    phase: 'thinking',
    thinking: { hover },
  })
}

/** Both queens still on, his about to come off. */
const BOTH = '3qk3/8/8/8/8/8/8/3QK3 w - - 0 1'
/** She came off and nothing was given back. */
const HIS_QUEEN_GONE = '3Q4/5k2/8/8/8/8/8/4K3 w - - 0 2'
/** Both came off — a trade rather than a loss. */
const TRADED = '3k4/8/8/8/8/8/8/4K3 w - - 0 2'

describe('nothing to say', () => {
  it('says nothing about the first position it sees', () => {
    expect(diffBeats(null, tableOf())).toEqual([])
  })

  it('says nothing across a new game', () => {
    // Different board, different id: not a move, a different evening.
    expect(diffBeats(tableOf(), tableOf({ game_id: 'c2', fen: TRADED }))).toEqual([])
  })

  it('says nothing about your own move', () => {
    const next = tableOf({ moves: ['e4'], turn: 'black', fen: BOTH })
    expect(diffBeats(tableOf(), next)).toEqual([])
  })
})

describe('a man coming off', () => {
  it('folds him up when a piece goes and nothing comes back', () => {
    const next = tableOf({ fen: HIS_QUEEN_GONE, moves: ['Qxd8+'], turn: 'black' })
    expect(diffBeats(tableOf(), next)).toEqual(['blunder'])
  })

  it('does not fold him up over an even trade', () => {
    // Both queens off in one push. A man who slumped at every exchange would
    // be exhausting to sit opposite.
    const next = tableOf({ fen: TRADED, moves: ['Qxd8+', 'Kxd8'], turn: 'white' })
    expect(diffBeats(tableOf(), next)).toEqual(['capture'])
  })

  it('does not fold him up over a pawn', () => {
    const prev = tableOf({ fen: '4k3/p7/8/8/8/8/P7/4K3 w - - 0 1' })
    const next = tableOf({
      fen: '4k3/P7/8/8/8/8/8/4K3 b - - 0 1',
      moves: ['a7'],
      turn: 'black',
    })
    expect(diffBeats(prev, next)).toEqual([])
  })

  it('reacts to the loss before he answers it', () => {
    // Your capture and his reply in one push, in the order they happened.
    const next = tableOf({ fen: HIS_QUEEN_GONE, moves: ['Qxd8+', 'Kf7'], turn: 'white' })
    expect(diffBeats(tableOf(), next)).toEqual(['blunder', 'move'])
  })
})

describe('his own move', () => {
  it('puts a piece down', () => {
    const prev = tableOf({ turn: 'black', your_turn: false })
    const next = tableOf({ turn: 'white', moves: ['Nf6'] })
    expect(diffBeats(prev, next)).toEqual(['move'])
  })

  it('snatches rather than places when it takes something', () => {
    const prev = tableOf({ turn: 'black', your_turn: false })
    const next = tableOf({ turn: 'white', moves: ['Nxe4'] })
    expect(diffBeats(prev, next)).toEqual(['capture'])
  })

  it('leans in after the piece is down, not instead of it', () => {
    const prev = tableOf({ turn: 'black', your_turn: false })
    const next = tableOf({ turn: 'white', moves: ['Qh4+'] })
    expect(diffBeats(prev, next)).toEqual(['move', 'check'])
  })

  it('does not lean in at a check you gave him', () => {
    const next = tableOf({ turn: 'black', moves: ['Qh5+'], your_turn: false })
    expect(diffBeats(tableOf(), next)).toEqual([])
  })
})

describe('the pause', () => {
  it('props his chin when the stare starts', () => {
    const prev = tableOf({ turn: 'black', your_turn: false })
    expect(diffBeats(prev, staring(null))).toEqual(['think'])
  })

  it('reaches for whatever he is eyeing', () => {
    expect(diffBeats(staring(null), staring('d4'))).toEqual(['hover'])
  })

  it('reaches again when he changes his mind', () => {
    expect(diffBeats(staring('d4'), staring('e5'))).toEqual(['hover'])
  })

  it('pulls the claw back when he thinks better of it', () => {
    expect(diffBeats(staring('d4'), staring(null))).toEqual(['pull'])
  })

  it('does not have him considering a move he has already made', () => {
    // The push carries both the end of the pause and the move it ended in.
    const prev = staring('d4')
    const next = tableOf({ turn: 'white', moves: ['d5'], phase: 'playing' })
    expect(diffBeats(prev, next)).toEqual(['move'])
  })
})

describe('the end', () => {
  it('is pleased with himself when you lose', () => {
    const next = tableOf({ phase: 'over', winner: 'rau', over_reason: 'checkmate' })
    expect(diffBeats(tableOf(), next)).toEqual(['cheer'])
  })

  it('folds when you win', () => {
    const next = tableOf({ phase: 'over', winner: 'user', over_reason: 'resignation' })
    expect(diffBeats(tableOf(), next)).toEqual(['slump'])
  })

  it('has nothing honest to do about a draw', () => {
    const next = tableOf({ phase: 'over', winner: null, over_reason: 'stalemate' })
    expect(diffBeats(tableOf(), next)).toEqual([])
  })

  it('only reacts to the ending once', () => {
    const over = tableOf({ phase: 'over', winner: 'rau', over_reason: 'checkmate' })
    expect(diffBeats(over, over)).toEqual([])
  })
})
