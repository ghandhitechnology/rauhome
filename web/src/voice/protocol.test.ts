import { describe, expect, it } from 'vitest'

import { negotiateVoiceCapabilities } from './protocol'

describe('voice protocol negotiation', () => {
  it('sends no optional commands to a legacy hub', () => {
    expect(negotiateVoiceCapabilities({})).toEqual({
      profileCommand: false,
      latencyMetrics: false,
    })
  })

  it('supports the transitional profile-bearing hello', () => {
    expect(negotiateVoiceCapabilities({ profile: 'normal' })).toEqual({
      profileCommand: true,
      latencyMetrics: true,
    })
  })

  it('honors explicit capabilities independently', () => {
    expect(
      negotiateVoiceCapabilities({ capabilities: ['latency_profile'] }),
    ).toEqual({
      profileCommand: true,
      latencyMetrics: false,
    })
  })
})
