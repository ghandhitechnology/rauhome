import { useEffect, useRef } from 'react'

export type HotkeyOptions = {
  /** Set false to keep the binding declared but inert (e.g. while a modal owns the keyboard). */
  enabled?: boolean
  /** Fire even while a text field has focus — for app-wide keys that must never be swallowed. */
  allowInInput?: boolean
  preventDefault?: boolean
}

type Handler = (e: KeyboardEvent) => void

type Combo = {
  key: string
  code: string | null
  ctrl: boolean
  shift: boolean
  alt: boolean
  meta: boolean
}

type Settings = {
  enabled: boolean
  allowInInput: boolean
  preventDefault: boolean
}

type Binding = {
  combo: Combo
  handler: { current: Handler }
  settings: { current: Settings }
}

type Registry = {
  bindings: Binding[]
  detach: () => void
}

const KEY_ALIASES: Record<string, string> = {
  space: ' ',
  esc: 'escape',
  return: 'enter',
  up: 'arrowup',
  down: 'arrowdown',
  left: 'arrowleft',
  right: 'arrowright',
}

const isMac = () => typeof navigator !== 'undefined' && /mac/i.test(navigator.userAgent)

/** Physical-key twin of a combo, so layouts that remap `key` still match. */
const codeFor = (key: string): string | null => {
  if (key === ' ') return 'Space'
  if (/^[a-z]$/.test(key)) return `Key${key.toUpperCase()}`
  if (/^[0-9]$/.test(key)) return `Digit${key}`
  return null
}

const parseCombo = (combo: string): Combo => {
  const parsed: Combo = { key: '', code: null, ctrl: false, shift: false, alt: false, meta: false }
  for (const part of combo.toLowerCase().split('+')) {
    const token = part.trim()
    if (!token) continue
    switch (token) {
      case 'ctrl':
      case 'control':
        parsed.ctrl = true
        break
      case 'shift':
        parsed.shift = true
        break
      case 'alt':
      case 'option':
        parsed.alt = true
        break
      case 'meta':
      case 'cmd':
      case 'command':
        parsed.meta = true
        break
      case 'mod':
        if (isMac()) parsed.meta = true
        else parsed.ctrl = true
        break
      default:
        parsed.key = KEY_ALIASES[token] ?? token
    }
  }
  parsed.code = codeFor(parsed.key)
  return parsed
}

const matches = (combo: Combo, e: KeyboardEvent) => {
  if (e.ctrlKey !== combo.ctrl || e.shiftKey !== combo.shift) return false
  if (e.altKey !== combo.alt || e.metaKey !== combo.meta) return false
  return e.key.toLowerCase() === combo.key || (combo.code !== null && e.code === combo.code)
}

const resolve = (opts: HotkeyOptions): Settings => ({
  enabled: opts.enabled ?? true,
  allowInInput: opts.allowInInput ?? false,
  preventDefault: opts.preventDefault ?? false,
})

const isTextEntry = (target: EventTarget | null) => {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable
}

let active: Registry | null = null

const registry = (): Registry => {
  if (active) return active

  const bindings: Binding[] = []
  // Capture phase, so the combo is seen before any component handler along the
  // path can swallow it — that is what makes these bindings app-wide.
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.isComposing) return
    if (e.repeat) return
    for (let i = bindings.length - 1; i >= 0; i--) {
      const b = bindings[i]
      const { enabled, allowInInput, preventDefault } = b.settings.current
      if (!enabled || !matches(b.combo, e)) continue
      if (!allowInInput && isTextEntry(e.target)) continue
      if (preventDefault) e.preventDefault()
      b.handler.current(e)
      return
    }
  }

  window.addEventListener('keydown', onKeyDown, { capture: true })
  active = {
    bindings,
    detach: () => window.removeEventListener('keydown', onKeyDown, { capture: true }),
  }
  return active
}

/**
 * Binds a key combo ('shift+space', 'mod+k') app-wide. The most recently
 * mounted binding for a combo handles it and stops there, so a transient view
 * can shadow a shell-level shortcut for as long as it lives.
 */
export function useGlobalHotkey(combo: string, handler: Handler, opts: HotkeyOptions = {}) {
  const handlerRef = useRef(handler)
  const settingsRef = useRef(resolve(opts))

  // Both are read live at dispatch, so registration stays keyed on the combo
  // alone — re-registering would push the binding to the head of the dispatch
  // order and let a shell shortcut jump ahead of the view shadowing it.
  useEffect(() => {
    handlerRef.current = handler
    settingsRef.current = resolve(opts)
  })

  useEffect(() => {
    const reg = registry()
    const binding: Binding = {
      combo: parseCombo(combo),
      handler: handlerRef,
      settings: settingsRef,
    }
    reg.bindings.push(binding)

    return () => {
      const i = reg.bindings.indexOf(binding)
      if (i >= 0) reg.bindings.splice(i, 1)
      if (reg.bindings.length === 0 && active === reg) {
        reg.detach()
        active = null
      }
    }
  }, [combo])
}
