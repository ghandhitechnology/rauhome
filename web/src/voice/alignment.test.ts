import { describe, expect, it } from 'vitest'

import {
  spokenSentence,
  spokenSentenceSoFar,
  spokenSoFar,
  type AlignedSentence,
} from './alignment'

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

describe('spokenSentence', () => {
  const first = sentence('Hello.', 0)
  const second = sentence('Bye.', 600)
  const reply = [first, second]

  it('is empty before the first sentence starts', () => {
    expect(spokenSentence(reply, 0)).toBe('')
    expect(spokenSentence(reply, -1)).toBe('')
  })

  it('returns the sentence whose audio has started', () => {
    expect(spokenSentence(reply, 1)).toBe('Hello.')
    expect(spokenSentence(reply, 599)).toBe('Hello.')
  })

  it('advances to the next sentence once playback enters it', () => {
    expect(spokenSentence(reply, 600)).toBe('Hello.')
    expect(spokenSentence(reply, 601)).toBe('Bye.')
    expect(spokenSentence(reply, 999)).toBe('Bye.')
  })

  it('holds the last started sentence across a gap', () => {
    const gapped = [first, sentence('Bye.', 5_000)]
    expect(spokenSentence(gapped, 1_200)).toBe('Hello.')
    expect(spokenSentence(gapped, 5_000)).toBe('Hello.')
    expect(spokenSentence(gapped, 5_001)).toBe('Bye.')
  })

  it('reports nothing with no alignment yet', () => {
    expect(spokenSentence([], 400)).toBe('')
  })
})

describe('spokenSentenceSoFar', () => {
  const first = sentence('Hello.', 0)
  const second = sentence('Bye.', 600)
  const reply = [first, second]

  it('streams only the audible prefix of the current sentence', () => {
    expect(spokenSentenceSoFar(reply, 0)).toBe('')
    expect(spokenSentenceSoFar(reply, 150)).toBe('He')
    expect(spokenSentenceSoFar(reply, 350)).toBe('Hell')
    expect(spokenSentenceSoFar(reply, 599)).toBe('Hello.')
  })

  it('starts over progressively when playback enters the next sentence', () => {
    expect(spokenSentenceSoFar(reply, 600)).toBe('Hello.')
    expect(spokenSentenceSoFar(reply, 650)).toBe('B')
    expect(spokenSentenceSoFar(reply, 850)).toBe('Bye')
    expect(spokenSentenceSoFar(reply, 1_000)).toBe('Bye.')
  })

  it('does not invent progress without character timing', () => {
    const blank: AlignedSentence[] = [
      { turnId: 'turn_1', text: 'Hello.', offsetMs: 0, durationMs: 600, charMs: [] },
    ]
    expect(spokenSentenceSoFar(blank, 300)).toBe('')
    expect(spokenSentenceSoFar(blank, 600)).toBe('Hello.')
  })
})
