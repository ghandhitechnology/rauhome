import type { VoiceLatencyProfile } from '../mode'

export type VoiceProtocolHello = {
  profile?: VoiceLatencyProfile
  capabilities?: unknown
}

export type VoiceProtocolCapabilities = {
  profileCommand: boolean
  latencyMetrics: boolean
}

/** Negotiate optional commands without breaking an older running hub. */
export function negotiateVoiceCapabilities(
  hello: VoiceProtocolHello,
): VoiceProtocolCapabilities {
  const capabilities = Array.isArray(hello.capabilities)
    ? hello.capabilities.filter((item): item is string => typeof item === 'string')
    : []
  // `profile` was introduced alongside both commands. This supports builds
  // from that transition while a legacy hello receives neither command.
  const modernProfile = hello.profile === 'normal' || hello.profile === 'hyper'
  return {
    profileCommand: modernProfile || capabilities.includes('latency_profile'),
    latencyMetrics: modernProfile || capabilities.includes('latency_metrics'),
  }
}
