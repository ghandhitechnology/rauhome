import { describe, expect, it } from 'vitest'
import {
  IDLE_FACE_STREAM,
  bubbleSpeechFromStream,
  reduceFaceStream,
  revealCompleteWords,
  streamCaughtUp,
} from './faceStream'

describe('faceStream', () => {
  it('grows cumulative deltas for one turn', () => {
    let state = reduceFaceStream(IDLE_FACE_STREAM, {
      kind: 'chat_started',
      turn_id: 't1',
      text: 'hi',
    })
    expect(state).toEqual({ turnId: 't1', text: '', phase: 'wait' })

    state = reduceFaceStream(state, {
      kind: 'chat_delta',
      turn_id: 't1',
      text: 'Hel',
    })
    expect(state.phase).toBe('live')
    expect(state.text).toBe('Hel')

    state = reduceFaceStream(state, {
      kind: 'chat_delta',
      turn_id: 't1',
      text: 'Hello there',
    })
    expect(state.text).toBe('Hello there')

    state = reduceFaceStream(state, {
      kind: 'chat_done',
      turn_id: 't1',
      text: 'Hello there',
    })
    expect(state.phase).toBe('done')
    expect(streamCaughtUp(state, 'Hello there')).toBe(true)
  })

  it('ignores deltas from a different turn', () => {
    const state = reduceFaceStream(
      { turnId: 't1', text: 'A', phase: 'live' },
      { kind: 'chat_delta', turn_id: 't2', text: 'B' },
    )
    expect(state.text).toBe('A')
  })

  it('adopts a real turn id after a local pending buffer', () => {
    const pending = { turnId: '', text: '', phase: 'wait' as const }
    const state = reduceFaceStream(pending, {
      kind: 'chat_delta',
      turn_id: 't9',
      text: 'Yo',
    })
    expect(state).toEqual({ turnId: 't9', text: 'Yo', phase: 'live' })
  })

  it('reveals the bubble word by word while live, then the full line when done', () => {
    expect(revealCompleteWords('Hello wor', false)).toBe('Hello ')
    expect(revealCompleteWords('Hello world', false)).toBe('Hello ')
    expect(revealCompleteWords('Hello world ', false)).toBe('Hello world ')
    expect(revealCompleteWords('Hello world', true)).toBe('Hello world')

    expect(
      bubbleSpeechFromStream({ turnId: 't', text: 'Hello wor', phase: 'live' }),
    ).toBe('Hello')
    expect(
      bubbleSpeechFromStream({ turnId: 't', text: 'Hi', phase: 'live' }),
    ).toBeNull()
    expect(
      bubbleSpeechFromStream({ turnId: 't', text: 'Hello world', phase: 'done' }),
    ).toBe('Hello world')
  })
})
