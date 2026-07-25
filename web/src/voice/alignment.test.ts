import { describe, expect, it } from 'vitest'

import { spokenSoFar, type AlignedSentence } from './alignment'

/** "Hi." at 100ms per character, starting at `offsetMs`. */
function sentence(text: string, offsetMs: number, perChar = 100): AlignedSentence {
  return {
    turnId: 'turn_1',
    text,
    offsetMs,
    durationMs: text.length * perChar,
    charMs: text.split('').map((_c, i) => i * perChar),
  }
}

describe('spokenSoFar', () => {
  const first = sentence('Hello.', 0) // 0..600
  const second = sentence('Bye.', 600) // 600..1000
  const reply = [first, second]

  it('is empty before anything has played', () => {
    expect(spokenSoFar(reply, 0)).toBe('')
  })

  it('reveals the sentence in flight character by character', () => {
    expect(spokenSoFar(reply, 150)).toBe('He')
    expect(spokenSoFar(reply, 350)).toBe('Hell')
    expect(spokenSoFar(reply, 599)).toBe('Hello.')
  })

  it('keeps finished sentences whole and joins them with a space', () => {
    expect(spokenSoFar(reply, 600)).toBe('Hello.')
    expect(spokenSoFar(reply, 750)).toBe('Hello. By')
    expect(spokenSoFar(reply, 1000)).toBe('Hello. Bye.')
  })

  it('does not run past the end of the reply', () => {
    expect(spokenSoFar(reply, 99_999)).toBe('Hello. Bye.')
  })

  it('stops at a gap rather than skipping ahead to a later sentence', () => {
    const gapped = [first, sentence('Bye.', 5_000)]
    expect(spokenSoFar(gapped, 1_200)).toBe('Hello.')
  })

  it('is monotonic, so a cue can never fire and then un-fire', () => {
    let previous = ''
    for (let played = 0; played <= 1_100; played += 17) {
      const spoken = spokenSoFar(reply, played)
      expect(spoken.length).toBeGreaterThanOrEqual(previous.length)
      previous = spoken
    }
  })

  it('falls back to the sentence duration when timestamps are missing', () => {
    const blank: AlignedSentence[] = [
      { turnId: 'turn_1', text: 'Hello.', offsetMs: 0, durationMs: 600, charMs: [] },
    ]
    // Nothing to reveal part-way through...
    expect(spokenSoFar(blank, 300)).toBe('')
    // ...but the sentence still lands whole once its audio has played.
    expect(spokenSoFar(blank, 600)).toBe('Hello.')
  })

  it('reports nothing for a reply that has not started arriving', () => {
    expect(spokenSoFar([], 500)).toBe('')
  })
})
