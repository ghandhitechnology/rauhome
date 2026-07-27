/**
 * Reading a table diff, both ways: what his body does about it, and which
 * cards visibly move.
 *
 * Both are pure functions over two server snapshots, which is the whole
 * reason they are separate modules from anything that draws.
 */
import { describe, expect, it } from 'vitest'

import { diffBeats } from './beats'
import { arrivedSlots, diffFlights } from './flights'
import type { CardId } from './art'
import type { Seat, TableState } from './useGame'

function tableOf(over: Partial<TableState> = {}): TableState {
  return {
    game_id: 'g1',
    seat: 'user',
    phase: 'playing',
    current: 'user',
    turns_to_take: 1,
    deck_count: 20,
    discard: [],
    hand: ['skip', 'attack', 'tacocat'] as CardId[],
    hand_counts: { user: 3, rau: 4 } as Record<Seat, number>,
    known_top: [],
    awaiting_seat: null,
    pending: null,
    winner: null,
    over_reason: '',
    your_turn: true,
    awaiting_you: false,
    can_nope: false,
    log: [],
    ...over,
  }
}

describe('what his body does about it', () => {
  it('says nothing about the first table it sees', () => {
    expect(diffBeats(null, tableOf())).toEqual([])
  })

  it('says nothing across a fresh deal', () => {
    // A new game_id is a new table, not a hand that changed.
    expect(diffBeats(tableOf(), tableOf({ game_id: 'g2', deck_count: 4 }))).toEqual([])
  })

  it('reaches for the deck when he draws', () => {
    const prev = tableOf({ current: 'rau', your_turn: false })
    const next = tableOf({
      current: 'rau',
      your_turn: false,
      deck_count: 19,
      hand_counts: { user: 3, rau: 5 },
    })
    expect(diffBeats(prev, next)).toEqual(['draw'])
  })

  it('does not confuse a Favor with a draw', () => {
    // His hand grows, but nothing came off the deck.
    const prev = tableOf({ current: 'rau', your_turn: false })
    const next = tableOf({
      current: 'rau',
      your_turn: false,
      hand: ['skip', 'attack'] as CardId[],
      hand_counts: { user: 2, rau: 5 },
    })
    expect(diffBeats(prev, next)).not.toContain('draw')
  })

  it('flicks a card when he plays one', () => {
    const prev = tableOf({ current: 'rau', your_turn: false })
    const next = tableOf({
      current: 'user',
      discard: ['skip'] as CardId[],
      hand_counts: { user: 3, rau: 3 },
    })
    expect(diffBeats(prev, next)).toEqual(['play'])
  })

  it('gets smug about an Attack specifically', () => {
    const prev = tableOf({ current: 'rau', your_turn: false })
    const next = tableOf({ current: 'user', discard: ['attack'] as CardId[] })
    expect(diffBeats(prev, next)).toEqual(['attack'])
  })

  it('ignores a card the player put down', () => {
    const prev = tableOf({ current: 'user' })
    const next = tableOf({ current: 'user', discard: ['skip'] as CardId[] })
    expect(diffBeats(prev, next)).toEqual([])
  })

  it('slams the table when he Nopes', () => {
    const pending = {
      action_id: 'a1',
      actor: 'user' as Seat,
      kind: 'card' as const,
      cards: ['attack'] as CardId[],
      nopes: 0,
      waiting_on: 'rau' as Seat,
      deadline: 100,
    }
    const prev = tableOf({ phase: 'nope_window', pending })
    const next = tableOf({
      phase: 'nope_window',
      pending: { ...pending, nopes: 1, waiting_on: 'user' },
    })
    expect(diffBeats(prev, next)).toEqual(['nope'])
  })

  it('recoils at the kitten and breathes out when it is defused', () => {
    const calm = tableOf({ current: 'rau', your_turn: false })
    const bomb = tableOf({
      current: 'rau',
      your_turn: false,
      phase: 'awaiting_defuse',
      awaiting_seat: 'rau',
    })
    expect(diffBeats(calm, bomb)).toEqual(['kitten'])
    expect(diffBeats(bomb, calm)).toEqual(['defuse'])
  })

  it('does not breathe out when the kitten got him', () => {
    const bomb = tableOf({ phase: 'awaiting_defuse', awaiting_seat: 'rau' })
    const dead = tableOf({ phase: 'over', winner: 'user' })
    expect(diffBeats(bomb, dead)).toEqual(['slump'])
  })

  it('cheers when he wins and slumps when he loses', () => {
    const live = tableOf()
    expect(diffBeats(live, tableOf({ phase: 'over', winner: 'rau' }))).toContain('cheer')
    expect(diffBeats(live, tableOf({ phase: 'over', winner: 'user' }))).toContain('slump')
  })

  it('says it only once, however many times the table is pushed', () => {
    const over = tableOf({ phase: 'over', winner: 'rau' })
    expect(diffBeats(over, over)).toEqual([])
  })
})

describe('which cards visibly move', () => {
  it('flies nothing on the first table, or across a new game', () => {
    expect(diffFlights(null, tableOf())).toEqual([])
    expect(diffFlights(tableOf(), tableOf({ game_id: 'g2' }))).toEqual([])
  })

  it('flies one card off the deck into the hand that grew', () => {
    const prev = tableOf()
    expect(
      diffFlights(prev, tableOf({ deck_count: 19, hand_counts: { user: 3, rau: 5 } })),
    ).toEqual([{ from: 'deck', to: 'rauHand' }])
    expect(
      diffFlights(
        prev,
        tableOf({ deck_count: 19, hand: ['skip', 'attack', 'tacocat', 'nope'] as CardId[] }),
      ),
    ).toEqual([{ from: 'deck', to: 'playerHand' }])
  })

  it('flies a played card from whoever had the turn', () => {
    expect(
      diffFlights(tableOf({ current: 'rau' }), tableOf({ discard: ['skip'] as CardId[] })),
    ).toEqual([{ from: 'rauHand', to: 'discard' }])
    expect(
      diffFlights(tableOf({ current: 'user' }), tableOf({ discard: ['skip'] as CardId[] })),
    ).toEqual([{ from: 'playerHand', to: 'discard' }])
  })

  it('flies a whole combo, one card per card', () => {
    const next = tableOf({ discard: ['tacocat', 'tacocat'] as CardId[] })
    expect(diffFlights(tableOf({ current: 'rau' }), next)).toHaveLength(2)
  })

  it('hands a card over on a Favor', () => {
    const prev = tableOf()
    const next = tableOf({
      hand: ['skip', 'attack'] as CardId[],
      hand_counts: { user: 2, rau: 5 },
    })
    expect(diffFlights(prev, next)).toEqual([{ from: 'playerHand', to: 'rauHand' }])
  })

  it('flies nothing for a shuffle or a peek', () => {
    expect(diffFlights(tableOf(), tableOf({ known_top: ['skip'] as CardId[] }))).toEqual([])
    expect(diffFlights(tableOf(), tableOf())).toEqual([])
  })
})

/*
 * Where a card lands in your fan.
 *
 * The engine sorts a hand whenever it gives you a card, so "the new one" is
 * not "the last one" — and with duplicates in hand, telling the new slot from
 * an old one is the whole job.
 */
describe('arrivedSlots', () => {
  it('finds a card appended to the end', () => {
    expect(arrivedSlots(['skip', 'attack'], ['skip', 'attack', 'nope'])).toEqual([2])
  })

  it('finds a card sorted into the middle', () => {
    expect(arrivedSlots(['attack', 'skip'], ['attack', 'defuse', 'skip'])).toEqual([1])
  })

  it('claims one slot of a duplicate, not all of them', () => {
    expect(arrivedSlots(['skip', 'skip'], ['skip', 'skip', 'skip'])).toEqual([2])
  })

  it('finds every slot when several arrive at once', () => {
    expect(arrivedSlots([], ['skip', 'nope'])).toEqual([0, 1])
  })

  it('finds nothing when the hand only shrank', () => {
    expect(arrivedSlots(['skip', 'nope'], ['skip'])).toEqual([])
  })

  it('finds nothing when a card was swapped for one already held', () => {
    // Two of a kind stolen away and a duplicate handed back: the count is the
    // same and so is the content, so no slot is new.
    expect(arrivedSlots(['skip', 'nope'], ['skip', 'nope'])).toEqual([])
  })
})
