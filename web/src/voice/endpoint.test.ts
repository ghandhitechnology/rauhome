import { describe, expect, it } from 'vitest'

import { classifyEndpoint, ENDPOINT_SCALE } from './endpoint'
import { Vad } from './vad'

describe('reading whether someone has finished', () => {
  it('waits longer when the sentence is left hanging', () => {
    for (const text of [
      'I was going to ask about the',
      'can you tell me if',
      'the thing is that it depends on',
      'I think so but',
    ]) {
      expect(classifyEndpoint(text), text).toBe('continuing')
    }
  })

  it('waits longer through a filler, which is the point of one', () => {
    for (const text of ['so um', 'what I mean is uh', 'hmm']) {
      expect(classifyEndpoint(text), text).toBe('continuing')
    }
  })

  it('treats a trailing comma as a held breath', () => {
    expect(classifyEndpoint('first of all,')).toBe('continuing')
  })

  it('answers a finished question promptly', () => {
    for (const text of ['what time is it?', 'is the deploy done?', 'that works.']) {
      expect(classifyEndpoint(text), text).toBe('complete')
    }
  })

  it('does not mistake a two-word opener for a whole thought', () => {
    // "Can you" is never the request; cutting in here is the rudest failure.
    expect(classifyEndpoint('can you')).toBe('continuing')
    expect(classifyEndpoint('I need')).toBe('continuing')
  })

  it('still lets the short replies a conversation runs on through', () => {
    for (const text of ['yes', 'no', 'thanks', 'stop']) {
      expect(classifyEndpoint(text), text).not.toBe('continuing')
    }
  })

  it('falls back to the old fixed behaviour when it cannot tell', () => {
    // Backends that stream no partials, and text this cannot read, must leave
    // endpointing exactly as it was rather than guessing.
    expect(classifyEndpoint('')).toBe('neutral')
    expect(classifyEndpoint('   ')).toBe('neutral')
    expect(ENDPOINT_SCALE.neutral).toBe(1)
  })

  it('scales in the direction each verdict implies', () => {
    expect(ENDPOINT_SCALE.continuing).toBeGreaterThan(ENDPOINT_SCALE.neutral)
    expect(ENDPOINT_SCALE.complete).toBeLessThan(ENDPOINT_SCALE.neutral)
  })
})

describe('the endpointer driving the VAD', () => {
  /** Talk for `speechMs`, then go quiet for `silenceMs`. */
  const utterance = (vad: Vad, speechMs: number, silenceMs: number) => {
    let ended = false
    for (let t = 0; t < speechMs; t += 20) vad.push(0.06, 20)
    for (let t = 0; t < silenceMs; t += 20) {
      if (vad.push(0.0, 20) === 'end') ended = true
    }
    return ended
  }

  it('holds on through a pause after an unfinished phrase', () => {
    const base = new Vad({ hangoverMs: 300 })
    expect(utterance(base, 400, 340), 'baseline should end').toBe(true)

    const patient = new Vad({ hangoverMs: 300 })
    patient.setHangoverScale(ENDPOINT_SCALE.continuing)
    expect(utterance(patient, 400, 340), 'cut off mid-thought').toBe(false)
  })

  it('answers sooner once the question is clearly finished', () => {
    const prompt = new Vad({ hangoverMs: 300 })
    prompt.setHangoverScale(ENDPOINT_SCALE.complete)
    expect(utterance(prompt, 400, 200)).toBe(true)

    const base = new Vad({ hangoverMs: 300 })
    expect(utterance(base, 400, 200), 'baseline should still be waiting').toBe(false)
  })

  it('refuses to let a bad transcript take the timing over entirely', () => {
    const vad = new Vad({ hangoverMs: 300 })
    vad.setHangoverScale(100)
    expect(vad.hangoverMs).toBeLessThanOrEqual(900)
    vad.setHangoverScale(0)
    expect(vad.hangoverMs).toBeGreaterThanOrEqual(150)
    vad.setHangoverScale(Number.NaN)
    expect(vad.hangoverMs).toBe(300)
  })

  it('forgets one utterance patience before the next', () => {
    const vad = new Vad({ hangoverMs: 300 })
    vad.setHangoverScale(ENDPOINT_SCALE.continuing)
    vad.reset()
    expect(vad.hangoverMs).toBe(300)
  })

  it('keeps counting speech through the quiet part of a word', () => {
    // Stop consonants drop the level below the entry threshold mid-word. With
    // a single gate those frames count as silence, so the hangover restarts
    // inside the word and a slow speaker gets cut off between syllables.
    // `speaking` alone cannot show this — the hangover has not run out either
    // way — so watch whether the frames were counted as speech at all.
    const vad = new Vad({ onsetMs: 60, hangoverMs: 300, threshold: 0.02 })
    for (let t = 0; t < 200; t += 20) vad.push(0.08, 20)
    expect(vad.speaking).toBe(true)
    const before = vad.sustainedMs

    // Above the noise floor, below the entry threshold: the quiet part of a 't'.
    for (let t = 0; t < 60; t += 20) vad.push(0.018, 20)
    expect(vad.sustainedMs, 'counted mid-word quiet as silence').toBeGreaterThan(before)
    expect(vad.speaking).toBe(true)
  })

  it('still needs the full threshold to start, so a room does not open a turn', () => {
    // The relaxed gate must apply only once speech is already established.
    const vad = new Vad({ onsetMs: 60, hangoverMs: 300, threshold: 0.02 })
    for (let t = 0; t < 400; t += 20) vad.push(0.018, 20)
    expect(vad.speaking, 'background noise opened an utterance').toBe(false)
  })
})
