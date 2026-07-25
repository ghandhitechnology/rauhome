import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type Mode = 'chat' | 'voice'

const MODE_KEY = 'rau.mode'

type ModeContextValue = {
  mode: Mode
  setMode: (mode: Mode) => void
  toggleMode: () => void
}

const ModeContext = createContext<ModeContextValue | null>(null)

const isMode = (v: unknown): v is Mode => v === 'chat' || v === 'voice'

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

  const toggleMode = useCallback(() => setMode((m) => (m === 'chat' ? 'voice' : 'chat')), [])
  const value = useMemo<ModeContextValue>(() => ({ mode, setMode, toggleMode }), [mode, toggleMode])

  return <ModeContext value={value}>{children}</ModeContext>
}

export function useMode() {
  const ctx = useContext(ModeContext)
  if (!ctx) throw new Error('useMode must be used inside <ModeProvider>')
  return ctx
}
