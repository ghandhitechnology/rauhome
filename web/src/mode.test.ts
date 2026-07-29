import { describe, expect, it } from 'vitest'

import {
  MODES,
  modeLabel,
  modeListens,
  modeSupportsHyper,
  modeUsesVoice,
  nextMode,
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

  it('is visible for Voice and Space Talk, never typed Talk or Chat', () => {
    expect(modeSupportsHyper('voice')).toBe(true)
    expect(modeSupportsHyper('space-talk')).toBe(true)
    expect(modeSupportsHyper('talk')).toBe(false)
    expect(modeSupportsHyper('chat')).toBe(false)
    expect(modeUsesVoice('talk')).toBe(true)
    expect(modeListens('talk')).toBe(false)
    expect(modeUsesVoice('space-talk')).toBe(true)
    expect(modeListens('space-talk')).toBe(true)
  })

  it('adds Space Talk to the end of the Shift+Space rotation', () => {
    expect(MODES).toEqual(['chat', 'voice', 'talk', 'space-talk'])
    expect(nextMode('talk')).toBe('space-talk')
    expect(nextMode('space-talk')).toBe('chat')
    expect(modeLabel('space-talk')).toBe('space talk')
  })
})
