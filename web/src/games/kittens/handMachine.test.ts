import { describe, expect, it } from 'vitest'

import {
  DRAG_THRESHOLD,
  handLocked,
  handReducer,
  IDLE_HAND,
  raisedIndices,
  type HandState,
} from './handMachine'

const run = (start: HandState, ...events: Parameters<typeof handReducer>[1][]) =>
  events.reduce(handReducer, start)

describe('click versus drag', () => {
  it('a press released without travel raises the card', () => {
    const state = run(
      IDLE_HAND,
      { type: 'press', index: 2, at: { x: 100, y: 400 } },
      { type: 'release', overDiscard: false },
    )
    expect(state).toEqual({ mode: 'raised', indices: [2], picker: 'none' })
  })

  it('stays a press until the pointer clears the threshold', () => {
    const short = run(
      IDLE_HAND,
      { type: 'press', index: 1, at: { x: 100, y: 400 } },
      { type: 'move', at: { x: 100 + DRAG_THRESHOLD - 1, y: 400 }, overDiscard: false },
    )
    expect(short.mode).toBe('pressed')

    const long = handReducer(short, {
      type: 'move',
      at: { x: 100 + DRAG_THRESHOLD + 1, y: 400 },
      overDiscard: false,
    })
    expect(long.mode).toBe('dragging')
  })

  it('tracks the discard as the pointer passes over it', () => {
    const state = run(
      IDLE_HAND,
      { type: 'press', index: 0, at: { x: 0, y: 0 } },
      { type: 'move', at: { x: 40, y: 0 }, overDiscard: false },
      { type: 'move', at: { x: 80, y: 0 }, overDiscard: true },
    )
    expect(state).toMatchObject({ mode: 'dragging', overDiscard: true })
  })
})

describe('dropping', () => {
  const dragging = run(
    IDLE_HAND,
    { type: 'press', index: 3, at: { x: 0, y: 0 } },
    { type: 'move', at: { x: 60, y: 0 }, overDiscard: true },
  )

  it('plays the card when it lands on the pile', () => {
    const state = handReducer(dragging, { type: 'release', overDiscard: true })
    expect(state).toEqual({ mode: 'confirming', indices: [3], picker: 'none' })
  })

  it('opens the picker over the pile when the card needs one first', () => {
    const state = handReducer(dragging, {
      type: 'release',
      overDiscard: true,
      needsPicker: 'demand',
    })
    expect(state).toEqual({ mode: 'raised', indices: [3], picker: 'demand' })
  })

  it('springs back when it lands anywhere else', () => {
    const state = handReducer(dragging, { type: 'release', overDiscard: false })
    expect(state).toEqual(IDLE_HAND)
  })
})

describe('building a set', () => {
  const raised: HandState = { mode: 'raised', indices: [0], picker: 'none' }

  it('adds and removes cards', () => {
    const two = handReducer(raised, { type: 'raiseAdd', index: 4 })
    expect(raisedIndices(two)).toEqual([0, 4])
    const back = handReducer(two, { type: 'raiseAdd', index: 4 })
    expect(raisedIndices(back)).toEqual([0])
  })

  it('falls back to nothing raised once the last card is removed', () => {
    expect(handReducer(raised, { type: 'raiseAdd', index: 0 })).toEqual(IDLE_HAND)
  })

  it('drops a choice made about the old set', () => {
    const demanding: HandState = { mode: 'raised', indices: [0, 1, 2], picker: 'demand' }
    const changed = handReducer(demanding, { type: 'raiseAdd', index: 5 })
    expect(changed).toMatchObject({ picker: 'none' })
  })
})

describe('sending a move', () => {
  const confirming = handReducer(
    { mode: 'raised', indices: [1, 2], picker: 'none' },
    { type: 'confirm' },
  )

  it('locks the hand while the server is answering', () => {
    expect(confirming.mode).toBe('confirming')
    expect(handLocked(confirming)).toBe(true)
    // Nothing may start a new gesture underneath a move in flight.
    expect(handReducer(confirming, { type: 'press', index: 0, at: { x: 0, y: 0 } })).toBe(
      confirming,
    )
    expect(handReducer(confirming, { type: 'cancel' })).toBe(confirming)
  })

  it('clears the hand when the move is taken', () => {
    expect(handReducer(confirming, { type: 'resolved', ok: true })).toEqual(IDLE_HAND)
  })

  it('puts a refused move back on the raised card, cards intact', () => {
    // The refusal is shown next to the thing it is about, rather than
    // dumping the selection and leaving the message floating.
    expect(handReducer(confirming, { type: 'resolved', ok: false })).toEqual({
      mode: 'raised',
      indices: [1, 2],
      picker: 'none',
    })
  })
})

describe('the hand changing underneath', () => {
  it('resets from any state', () => {
    const states: HandState[] = [
      { mode: 'pressed', index: 0, origin: { x: 0, y: 0 } },
      { mode: 'dragging', index: 0, at: { x: 0, y: 0 }, overDiscard: true },
      { mode: 'raised', indices: [0, 1], picker: 'demand' },
      { mode: 'confirming', indices: [0], picker: 'none' },
    ]
    for (const state of states) {
      expect(handReducer(state, { type: 'reset' })).toEqual(IDLE_HAND)
    }
  })
})

describe('the server asking for a card', () => {
  it('raises one without a gesture', () => {
    const state = handReducer(IDLE_HAND, { type: 'raise', indices: [2], picker: 'defuse' })
    expect(state).toEqual({ mode: 'raised', indices: [2], picker: 'defuse' })
  })

  it('does not interrupt a move already in flight', () => {
    const confirming: HandState = { mode: 'confirming', indices: [0], picker: 'none' }
    expect(handReducer(confirming, { type: 'raise', indices: [1] })).toBe(confirming)
  })
})
