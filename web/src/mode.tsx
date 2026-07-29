/* oxlint-disable react/only-export-components -- provider and hook form one small state API */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { tr } from './i18n'

/**
 * How you talk to Rau.
 *
 * - `chat`  — type in, text out
 * - `voice` — speak in, voice out (mic on)
 * - `talk`  — type in, voice out (mic off)
 * - `space-talk` — hold Space to speak, voice out
 *
 * Shift+Space rotates through these in order.
 */
export type Mode = 'chat' | 'voice' | 'talk' | 'space-talk'
export type VoiceLatencyProfile = 'normal' | 'hyper'

export const MODES: readonly Mode[] = ['chat', 'voice', 'talk', 'space-talk'] as const

const MODE_KEY = 'rau.mode'
const VOICE_LATENCY_KEY = 'rau.voice.latency'

type ModeContextValue = {
  mode: Mode
  setMode: (mode: Mode) => void
  toggleMode: () => void
  voiceLatency: VoiceLatencyProfile
  setVoiceLatency: (profile: VoiceLatencyProfile) => void
}

const ModeContext = createContext<ModeContextValue | null>(null)

const isMode = (v: unknown): v is Mode =>
  v === 'chat' || v === 'voice' || v === 'talk' || v === 'space-talk'

export function nextMode(mode: Mode): Mode {
  const i = MODES.indexOf(mode)
  return MODES[(i + 1) % MODES.length]
}

/** Voice socket + TTS are live (mic may or may not be). */
export function modeUsesVoice(mode: Mode): boolean {
  return mode === 'voice' || mode === 'talk' || mode === 'space-talk'
}

/** Mic is open and listening for speech. */
export function modeListens(mode: Mode): boolean {
  return mode === 'voice' || mode === 'space-talk'
}

/** Hyper belongs to microphone modes; typed Talk always stays Normal. */
export function modeSupportsHyper(mode: Mode): boolean {
  return mode === 'voice' || mode === 'space-talk'
}

export function normalizeVoiceLatency(value: unknown): VoiceLatencyProfile {
  return value === 'hyper' ? 'hyper' : 'normal'
}

export function modeLabel(mode: Mode): string {
  if (mode === 'voice') return tr('mode.voice')
  if (mode === 'talk') return tr('mode.talk')
  if (mode === 'space-talk') return tr('mode.spaceTalk')
  return tr('mode.chat')
}

// Storage can be unavailable (private windows, blocked third-party contexts),
// so a missing or hostile value just falls back to chat.
function loadMode(): Mode {
  try {
    const raw = localStorage.getItem(MODE_KEY)
    return isMode(raw) ? raw : 'chat'
  } catch {
    return 'chat'
  }
}

function loadVoiceLatency(): VoiceLatencyProfile {
  try {
    return normalizeVoiceLatency(localStorage.getItem(VOICE_LATENCY_KEY))
  } catch {
    return 'normal'
  }
}

export function ModeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>(loadMode)
  const [voiceLatency, setVoiceLatency] = useState<VoiceLatencyProfile>(loadVoiceLatency)

  useEffect(() => {
    try {
      localStorage.setItem(MODE_KEY, mode)
    } catch {
      /* the mode still holds for this session */
    }
  }, [mode])

  useEffect(() => {
    try {
      localStorage.setItem(VOICE_LATENCY_KEY, voiceLatency)
    } catch {
      /* the latency profile still holds for this session */
    }
  }, [voiceLatency])

  const toggleMode = useCallback(() => setMode((m) => nextMode(m)), [])
  const value = useMemo<ModeContextValue>(
    () => ({ mode, setMode, toggleMode, voiceLatency, setVoiceLatency }),
    [mode, toggleMode, voiceLatency],
  )

  return <ModeContext value={value}>{children}</ModeContext>
}

export function useMode() {
  const ctx = useContext(ModeContext)
  if (!ctx) throw new Error('useMode must be used inside <ModeProvider>')
  return ctx
}
