import { useCallback, useEffect, useRef, useState, type MouseEvent } from 'react'
import ClawdRoom, { type HitRect } from '../components/ClawdRoom'
import { EMPTY_SIGNALS, type Signals } from '../clawd/director'
import {
  isPetShell,
  petHide,
  petMoveCorner,
  petQuit,
  petSetVisible,
  reportHitRect,
} from '../clawd/petBridge'
import { api } from '../api'
import { live } from '../live'
import './Pet.css'

/**
 * Desktop-pet view: full Director + speech bubble, no room art.
 * Meant to run inside the Tauri companion window (or a browser tab for debug).
 */
export default function Pet() {
  const [signals, setSignals] = useState<Signals>(EMPTY_SIGNALS)
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null)
  const [paused, setPaused] = useState(false)
  const lastReply = useRef({ at: 0, text: '', sig: '' })
  const seeded = useRef(false)
  const hitRef = useRef<HitRect>({ x: 0, y: 0, w: 0, h: 0 })

  const refresh = useCallback(async () => {
    try {
      const [log, emo, status] = await Promise.all([api.log(), api.emotion(), api.status()])
      const entries: { role?: string; text?: string; time?: string }[] = log.log || []
      const idx = entries.map((m) => m.role !== 'user').lastIndexOf(true)
      const reply = idx >= 0 ? entries[idx] : null
      if (reply?.text) {
        const sig = `${idx}|${reply.time}|${reply.text}`
        if (sig !== lastReply.current.sig) {
          lastReply.current = {
            at: seeded.current ? Date.now() : 0,
            text: reply.text,
            sig,
          }
        }
      }
      seeded.current = true
      const awaiting = entries.length > 0 && entries[entries.length - 1]?.role === 'user'
      setSignals((prev) => ({
        ...prev,
        emotion: (emo.emotion || 'idle').toLowerCase(),
        listening: !!status.listening,
        hardState: status.hard_task?.state || 'idle',
        awaitingConfirm: !!status.confirm,
        thinking: awaiting,
        lastReplyAt: awaiting ? prev.lastReplyAt : lastReply.current.at,
        speech: awaiting ? null : lastReply.current.text || null,
      }))
    } catch {
      /* hub down — keep idle animation */
    }
  }, [])

  useEffect(() => {
    void refresh()
    const id = window.setInterval(() => {
      if (!live.isConnected()) void refresh()
    }, 15_000)
    const off = live.subscribe((event) => {
      if (
        event.kind === 'chat_done' ||
        event.kind === 'chat_error' ||
        event.kind === 'hard_task' ||
        event.kind === 'confirm_request' ||
        event.kind === 'confirm_result'
      ) {
        void refresh()
      }
    })
    return () => {
      window.clearInterval(id)
      off()
    }
  }, [refresh])

  // Face mutex + user hide: hub broadcasts pet_visibility over /ws.
  useEffect(() => {
    live.start()
    void api
      .getPet()
      .then((snap) => {
        const visible = snap.visible !== false
        setPaused(!visible)
        void petSetVisible(visible)
      })
      .catch(() => undefined)
    return live.subscribe((event) => {
      if (event.kind !== 'pet_visibility') return
      const visible = event.visible !== false
      setPaused(!visible)
      void petSetVisible(visible)
    })
  }, [])

  useEffect(() => {
    document.documentElement.classList.add('pet-shell')
    document.body.classList.add('pet-shell')
    // color-scheme: dark (index.html) forces an opaque page fill in WKWebView.
    const scheme = document.querySelector('meta[name="color-scheme"]')
    const theme = document.querySelector('meta[name="theme-color"]')
    const prevScheme = scheme?.getAttribute('content') ?? null
    const prevTheme = theme?.getAttribute('content') ?? null
    scheme?.setAttribute('content', 'normal')
    theme?.setAttribute('content', 'transparent')
    return () => {
      document.documentElement.classList.remove('pet-shell')
      document.body.classList.remove('pet-shell')
      if (scheme) {
        if (prevScheme == null) scheme.removeAttribute('content')
        else scheme.setAttribute('content', prevScheme)
      }
      if (theme) {
        if (prevTheme == null) theme.removeAttribute('content')
        else theme.setAttribute('content', prevTheme)
      }
    }
  }, [])

  const onHitRect = useCallback((rect: HitRect) => {
    hitRef.current = rect
    reportHitRect(rect)
  }, [])

  const onContextMenu = useCallback((e: MouseEvent) => {
    const r = hitRef.current
    const inside =
      e.clientX >= r.x && e.clientX <= r.x + r.w && e.clientY >= r.y && e.clientY <= r.y + r.h
    if (!inside) return
    e.preventDefault()
    setMenu({ x: e.clientX, y: e.clientY })
  }, [])

  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(null)
    window.addEventListener('pointerdown', close)
    return () => window.removeEventListener('pointerdown', close)
  }, [menu])

  if (paused) {
    return <div className="pet-root pet-paused" aria-hidden />
  }

  return (
    <div className="pet-root" onContextMenu={onContextMenu}>
      <ClawdRoom
        signals={signals}
        cinematic={false}
        showRoom={false}
        charScale={1.35}
        onHitRect={onHitRect}
      />
      {menu && (
        <ul
          className="pet-menu"
          style={{ left: menu.x, top: menu.y }}
          onPointerDown={(e) => e.stopPropagation()}
        >
          <li>
            <button
              type="button"
              onClick={() => {
                void petHide()
                setMenu(null)
              }}
            >
              Hide pet
            </button>
          </li>
          {(['tl', 'tr', 'bl', 'br'] as const).map((c) => (
            <li key={c}>
              <button
                type="button"
                onClick={() => {
                  void petMoveCorner(c)
                  setMenu(null)
                }}
              >
                Move {c.toUpperCase()}
              </button>
            </li>
          ))}
          <li>
            <button
              type="button"
              onClick={() => {
                void petQuit()
                setMenu(null)
              }}
            >
              Quit pet
            </button>
          </li>
          {!isPetShell() && (
            <li className="pet-menu-note">Browser debug — Tauri shell inactive</li>
          )}
        </ul>
      )}
    </div>
  )
}
