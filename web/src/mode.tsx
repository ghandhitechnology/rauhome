/* oxlint-disable react/only-export-components -- provider and hook form one small state API */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

/**
 * How you talk to Rau.
 *
 * - `chat`  — type in, text out
 * - `voice` — speak in, voice out (mic on)
 * - `talk`  — type in, voice out (mic off)
 *
 * Shift+Space rotates through these in order.
 */
export type Mode = 'chat' | 'voice' | 'talk'

export const MODES: readonly Mode[] = ['chat', 'voice', 'talk'] as const

const MODE_KEY = 'rau.mode'

type ModeContextValue = {
  mode: Mode
  setMode: (mode: Mode) => void
  toggleMode: () => void
}

const ModeContext = createContext<ModeContextValue | null>(null)

const isMode = (v: unknown): v is Mode =>
  v === 'chat' || v === 'voice' || v === 'talk'

export function nextMode(mode: Mode): Mode {
  const i = MODES.indexOf(mode)
  return MODES[(i + 1) % MODES.length]
}

/** Voice socket + TTS are live (mic may or may not be). */
export function modeUsesVoice(mode: Mode): boolean {
  return mode === 'voice' || mode === 'talk'
}

/** Mic is open and listening for speech. */
export function modeListens(mode: Mode): boolean {
  return mode === 'voice'
}

export function modeLabel(mode: Mode): string {
  if (mode === 'voice') return 'voice'
  if (mode === 'talk') return 'talk'
  return 'chat'
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

export function ModeProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>(loadMode)

  useEffect(() => {
    try {
      localStorage.setItem(MODE_KEY, mode)
    } catch {
      /* the mode still holds for this session */
    }
  }, [mode])

  const toggleMode = useCallback(() => setMode((m) => nextMode(m)), [])
  const value = useMemo<ModeContextValue>(() => ({ mode, setMode, toggleMode }), [mode, toggleMode])

  return <ModeContext value={value}>{children}</ModeContext>
}

export function useMode() {
  const ctx = useContext(ModeContext)
  if (!ctx) throw new Error('useMode must be used inside <ModeProvider>')
  return ctx
}
