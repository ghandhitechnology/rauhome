import { describe, expect, it } from 'vitest'

import {
  modeListens,
  modeSupportsHyper,
  modeUsesVoice,
  normalizeVoiceLatency,
} from './mode'

describe('voice latency profile', () => {
  it('defaults invalid or missing persisted values to Normal', () => {
    expect(normalizeVoiceLatency(null)).toBe('normal')
    expect(normalizeVoiceLatency('fast')).toBe('normal')
    expect(normalizeVoiceLatency('normal')).toBe('normal')
  })

  it('restores the persisted Hyper value', () => {
    expect(normalizeVoiceLatency('hyper')).toBe('hyper')
  })

  it('is visible only for microphone Voice, never Talk or Chat', () => {
    expect(modeSupportsHyper('voice')).toBe(true)
    expect(modeSupportsHyper('talk')).toBe(false)
    expect(modeSupportsHyper('chat')).toBe(false)
    expect(modeUsesVoice('talk')).toBe(true)
    expect(modeListens('talk')).toBe(false)
  })
})
