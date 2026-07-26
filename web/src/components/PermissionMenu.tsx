import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { api, type PermissionMode } from '../api'
import { live } from '../live'
import './PermissionMenu.css'

const MODES: { id: PermissionMode; label: string; detail: string }[] = [
  { id: 'auto', label: 'Auto', detail: 'Ask when something needs confirmation' },
  { id: 'bypass', label: 'Full bypass', detail: 'Run without asking — full trust' },
  { id: 'readonly', label: 'Read only', detail: 'No writes, shell, or side effects' },
]

function parseMode(raw: unknown): PermissionMode {
  const v = String(raw || 'auto').toLowerCase()
  if (v === 'bypass' || v === 'full_bypass') return 'bypass'
  if (v === 'readonly' || v === 'read_only') return 'readonly'
  return 'auto'
}

function labelFor(mode: PermissionMode): string {
  return MODES.find((m) => m.id === mode)?.label ?? 'Auto'
}

export default function PermissionMenu() {
  const [mode, setMode] = useState<PermissionMode>('auto')
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const rootRef = useRef<HTMLDivElement>(null)
  const listId = useId()

  const hydrate = useCallback(async () => {
    try {
      const s = await api.status()
      if (s?.permission_mode) {
        setMode(parseMode(s.permission_mode))
        return
      }
      if (s?.permissions) {
        setMode(parseMode(s.permissions.room || s.permissions.subagents))
        return
      }
      const p = await api.getPermissions()
      setMode(parseMode(p.mode ?? p.permissions?.room))
    } catch {
      /* keep last */
    }
  }, [])

  useEffect(() => {
    void hydrate()
    return live.subscribe((event) => {
      if (event.kind === 'permissions_changed') {
        setMode(parseMode(event.mode ?? (event.permissions as { room?: string } | undefined)?.room))
        setError('')
      }
      if (event.kind === 'hello' || event.kind === 'ping') {
        const status = event.status as
          | { permission_mode?: string; permissions?: { room?: string } }
          | undefined
        if (status?.permission_mode) setMode(parseMode(status.permission_mode))
        else if (status?.permissions?.room) setMode(parseMode(status.permissions.room))
      }
    })
  }, [hydrate])

  useEffect(() => {
    if (!open) return
    const onPointer = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  async function choose(next: PermissionMode) {
    if (next === mode || saving) {
      setOpen(false)
      return
    }
    const prev = mode
    setMode(next)
    setSaving(true)
    setError('')
    try {
      const res = await api.setPermissions({ mode: next })
      setMode(parseMode(res.mode ?? next))
      setOpen(false)
    } catch (e) {
      setMode(prev)
      setError(e instanceof Error ? e.message : 'Could not update')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className={`perm-menu${open ? ' is-open' : ''}`} ref={rootRef}>
      <button
        type="button"
        className={`perm-trigger mode-${mode}`}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        disabled={saving}
        onClick={() => setOpen((v) => !v)}
        title="Permissions"
      >
        <span>{labelFor(mode)}</span>
        <svg viewBox="0 0 12 12" aria-hidden className="perm-chevron">
          <path
            d="M3 4.5 L6 7.5 L9 4.5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {open && (
        <div className="perm-popover" role="listbox" id={listId} aria-label="Permissions">
          <div className="perm-popover-head">Permissions</div>
          <ul className="perm-popover-list">
            {MODES.map((item) => {
              const active = item.id === mode
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    role="option"
                    aria-selected={active}
                    className={`perm-option${active ? ' is-active' : ''}`}
                    onClick={() => void choose(item.id)}
                  >
                    <span className="perm-option-text">
                      <span className="perm-option-label">{item.label}</span>
                      <span className="perm-option-detail">{item.detail}</span>
                    </span>
                    {active ? (
                      <svg className="perm-check" viewBox="0 0 16 16" aria-hidden>
                        <path
                          d="M3.5 8.5 L6.5 11.5 L12.5 4.5"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="1.8"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    ) : (
                      <span className="perm-check-spacer" />
                    )}
                  </button>
                </li>
              )
            })}
          </ul>
          {error ? <p className="perm-popover-error">{error}</p> : null}
        </div>
      )}
    </div>
  )
}
