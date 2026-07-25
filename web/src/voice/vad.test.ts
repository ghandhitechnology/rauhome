import { describe, expect, it } from 'vitest'

import { Vad } from './vad'

const options = {
  threshold: 0.05,
  onsetMs: 60,
  hangoverMs: 100,
  bargeMs: 100,
}

describe('Vad', () => {
  it('requires sustained loud frames before speech starts', () => {
    const vad = new Vad(options)

    expect(vad.push(0.1, 20)).toBeNull()
    expect(vad.push(0.1, 20)).toBeNull()
    expect(vad.speaking).toBe(false)
    expect(vad.push(0.1, 20)).toBe('start')
    expect(vad.speaking).toBe(true)
  })

  it('ignores a short transient and starts timing again after silence', () => {
    const vad = new Vad(options)

    expect(vad.push(0.1, 20)).toBeNull()
    expect(vad.push(0.1, 20)).toBeNull()
    expect(vad.push(0, 20)).toBeNull()
    expect(vad.sustainedMs).toBe(0)

    expect(vad.push(0.1, 20)).toBeNull()
    expect(vad.push(0.1, 20)).toBeNull()
    expect(vad.push(0.1, 20)).toBe('start')
  })

  it('waits through the hangover before ending an utterance', () => {
    const vad = new Vad(options)
    vad.push(0.1, 20)
    vad.push(0.1, 20)
    expect(vad.push(0.1, 20)).toBe('start')

    for (let elapsed = 20; elapsed < options.hangoverMs; elapsed += 20) {
      expect(vad.push(0, 20)).toBeNull()
      expect(vad.speaking).toBe(true)
    }
    expect(vad.push(0, 20)).toBe('end')
    expect(vad.speaking).toBe(false)
  })

  it('uses the longer threshold for barge-in and resets session state', () => {
    const vad = new Vad(options)
    for (let elapsed = 20; elapsed <= 80; elapsed += 20) vad.push(0.1, 20)
    expect(vad.shouldBarge()).toBe(false)

    vad.push(0.1, 20)
    expect(vad.shouldBarge()).toBe(true)
    vad.reset()
    expect(vad.speaking).toBe(false)
    expect(vad.sustainedMs).toBe(0)
    expect(vad.shouldBarge()).toBe(false)
  })
})
