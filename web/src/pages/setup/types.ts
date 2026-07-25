import type { Catalog, SetupState } from '../../api'

export type StepId =
  | 'welcome'
  | 'origin'
  | 'identity'
  | 'brains'
  | 'models'
  | 'voice'
  | 'forge'
  | 'done'

export type Origin = 'fresh' | 'guided' | null

export type SlotDraft = { provider: string; model: string }

export type Draft = {
  origin: Origin
  identity: string
  backstory: string
  slots: Record<'face' | 'subagent' | 'dream', SlotDraft>
  tts: { voice_id: string; model: string }
  voiceSkipped: boolean
}

/** Verification outcome per provider id, kept out of the persisted draft. */
export type VerifyState = {
  status: 'idle' | 'checking' | 'ok' | 'bad'
  detail?: string
}

export type StepProps = {
  draft: Draft
  patch: (p: Partial<Draft>) => void
  state: SetupState | null
  catalog: Catalog | null
  reload: () => Promise<void>
  verify: Record<string, VerifyState>
  setVerify: (id: string, v: VerifyState) => void
  go: (to: StepId) => void
}

export const EMPTY_DRAFT: Draft = {
  origin: null,
  identity: '',
  backstory: '',
  slots: {
    face: { provider: '', model: '' },
    subagent: { provider: '', model: '' },
    dream: { provider: '', model: '' },
  },
  tts: { voice_id: 'TX3LPaxmHKxFdv7VOQHJ', model: 'eleven_flash_v2_5' },
  voiceSkipped: false,
}

/** Chat-capable auth slots — excludes voice and app-actions providers. */
export const CHAT_AUTH_IDS = ['openrouter', 'deepseek', 'kimi', 'kimi_code', 'codex']
