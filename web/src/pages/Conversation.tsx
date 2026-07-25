import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type RefObject,
} from 'react'
import { Link } from 'react-router-dom'
import ChatMarkdown from '../components/ChatMarkdown'
import ClawdAvatar from '../components/ClawdAvatar'
import SlashMenu from '../components/SlashMenu'
import { api } from '../api'
import {
  filterSlashCommands,
  matchSlash,
  mergeSkillCommands,
  readSlashDraft,
  type SlashCmd,
} from '../slash'
import './Conversation.css'

/** Rubber-band overscroll: past the bottom, compress/repulse the composer. */
function useComposerRubberBand(
  threadRef: RefObject<HTMLElement | null>,
  composeRef: RefObject<HTMLElement | null>,
) {
  useEffect(() => {
    const thread = threadRef.current
    const compose = composeRef.current
    if (!thread || !compose) return

    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) return

    const MAX = 72
    let raw = 0
    let touching = false
    let lastTouchY = 0
    let releaseTimer: number | null = null
    let springing = false

    const atBottom = () =>
      thread.scrollTop + thread.clientHeight >= thread.scrollHeight - 2

    const paint = (nextRaw: number, snapping: boolean) => {
      raw = snapping ? 0 : Math.max(0, nextRaw)
      // Soft resistance — more drag → less travel.
      const pull = MAX * (1 - Math.exp(-raw / MAX))
      const t = pull / MAX
      compose.style.transition = snapping
        ? 'transform 480ms cubic-bezier(0.34, 1.55, 0.45, 1)'
        : 'none'
      // Push the box up into the thread and squash it a little.
      compose.style.transform = pull
        ? `translate3d(0, ${(-pull * 0.92).toFixed(2)}px, 0) scale(${(1 - t * 0.055).toFixed(4)}, ${(1 - t * 0.12).toFixed(4)})`
        : ''
      compose.classList.toggle('is-compressed', pull > 0.5)
      thread.style.transition = snapping
        ? 'transform 480ms cubic-bezier(0.34, 1.55, 0.45, 1)'
        : 'none'
      thread.style.transform = pull
        ? `translate3d(0, ${(-pull * 0.28).toFixed(2)}px, 0)`
        : ''
    }

    const release = () => {
      if (releaseTimer != null) {
        window.clearTimeout(releaseTimer)
        releaseTimer = null
      }
      if (raw <= 0.5) {
        paint(0, false)
        compose.style.transition = ''
        thread.style.transition = ''
        springing = false
        return
      }
      springing = true
      paint(0, true)
      window.setTimeout(() => {
        compose.style.transition = ''
        thread.style.transition = ''
        springing = false
      }, 500)
    }

    const scheduleRelease = () => {
      if (touching) return
      if (releaseTimer != null) window.clearTimeout(releaseTimer)
      releaseTimer = window.setTimeout(release, 90)
    }

    const onWheel = (e: WheelEvent) => {
      if (springing) return
      if (e.deltaY <= 0) {
        if (raw <= 0) return
        e.preventDefault()
        paint(raw + e.deltaY * 0.65, false)
        if (raw <= 0.5) release()
        else scheduleRelease()
        return
      }
      if (!atBottom() && raw <= 0) return
      e.preventDefault()
      paint(raw + e.deltaY * 0.42, false)
      scheduleRelease()
    }

    const onTouchStart = (e: TouchEvent) => {
      touching = true
      lastTouchY = e.touches[0]?.clientY ?? 0
      if (releaseTimer != null) {
        window.clearTimeout(releaseTimer)
        releaseTimer = null
      }
      compose.style.transition = 'none'
      thread.style.transition = 'none'
    }

    const onTouchMove = (e: TouchEvent) => {
      if (springing) return
      const y = e.touches[0]?.clientY ?? lastTouchY
      const dy = lastTouchY - y // finger up → positive (scroll down)
      lastTouchY = y
      if (dy > 0 && (atBottom() || raw > 0)) {
        if (e.cancelable) e.preventDefault()
        paint(raw + dy * 0.85, false)
      } else if (dy < 0 && raw > 0) {
        if (e.cancelable) e.preventDefault()
        paint(raw + dy * 0.85, false)
      }
    }

    const onTouchEnd = () => {
      touching = false
      release()
    }

    thread.addEventListener('wheel', onWheel, { passive: false })
    thread.addEventListener('touchstart', onTouchStart, { passive: true })
    thread.addEventListener('touchmove', onTouchMove, { passive: false })
    thread.addEventListener('touchend', onTouchEnd)
    thread.addEventListener('touchcancel', onTouchEnd)

    return () => {
      if (releaseTimer != null) window.clearTimeout(releaseTimer)
      thread.removeEventListener('wheel', onWheel)
      thread.removeEventListener('touchstart', onTouchStart)
      thread.removeEventListener('touchmove', onTouchMove)
      thread.removeEventListener('touchend', onTouchEnd)
      thread.removeEventListener('touchcancel', onTouchEnd)
      compose.style.transform = ''
      compose.style.transition = ''
      compose.classList.remove('is-compressed')
      thread.style.transform = ''
      thread.style.transition = ''
    }
  }, [threadRef, composeRef])
}

export default function Conversation() {
  const [log, setLog] = useState<any[]>([])
  const [emotion, setEmotion] = useState('idle')
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [confirm, setConfirm] = useState<any>(null)
  const [hardState, setHardState] = useState('')
  const [commands, setCommands] = useState<SlashCmd[]>(() => mergeSkillCommands([]))
  const [slashIndex, setSlashIndex] = useState(0)
  const [slashOpen, setSlashOpen] = useState(true)
  const threadRef = useRef<HTMLElement>(null)
  const composeRef = useRef<HTMLElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useComposerRubberBand(threadRef, composeRef)

  async function refresh() {
    try {
      const [l, e, s] = await Promise.all([api.log(), api.emotion(), api.status()])
      setLog(l.log || [])
      setEmotion((e.emotion || 'idle').toLowerCase())
      setConfirm(s.confirm || null)
      setHardState(s.hard_task?.state || 'idle')
    } catch {
      /* hub down */
    }
  }

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 1200)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    api
      .skills()
      .then((d) => setCommands(mergeSkillCommands(d.skills || [])))
      .catch(() => setCommands(mergeSkillCommands([])))
  }, [])

  const slashDraft = useMemo(() => readSlashDraft(draft), [draft])
  const activeSlash = useMemo(
    () => (slashDraft?.hasSpace || (slashDraft && matchSlash(draft, commands)) ? matchSlash(draft, commands) : null),
    [slashDraft, draft, commands],
  )
  const slashSuggestions = useMemo(() => {
    if (!slashDraft || slashDraft.hasSpace) return []
    return filterSlashCommands(commands, slashDraft.token)
  }, [slashDraft, commands])
  const showSlashMenu = slashOpen && slashSuggestions.length > 0 && !!slashDraft && !slashDraft.hasSpace

  useEffect(() => {
    setSlashIndex(0)
    setSlashOpen(true)
  }, [slashDraft?.token, slashDraft?.hasSpace])

  // Scroll the thread pane only — never the page under the composer.
  useEffect(() => {
    const thread = threadRef.current
    if (!thread) return
    requestAnimationFrame(() => {
      thread.scrollTop = thread.scrollHeight
    })
  }, [log, sending])

  // Grow the composer with its content instead of scrolling a one-line box.
  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`
  }, [draft])

  function pickSlash(cmd: SlashCmd) {
    setDraft(`${cmd.slash} `)
    setSlashOpen(false)
    requestAnimationFrame(() => inputRef.current?.focus())
  }

  async function send() {
    const text = draft.trim()
    if (!text || sending) return
    setSending(true)
    setDraft('')
    setSlashOpen(false)
    try {
      await api.chat(text)
      await refresh()
    } finally {
      setSending(false)
    }
  }

  function onComposeKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (showSlashMenu) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSlashIndex((i) => (i + 1) % slashSuggestions.length)
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSlashIndex((i) => (i - 1 + slashSuggestions.length) % slashSuggestions.length)
        return
      }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) {
        const pick = slashSuggestions[slashIndex]
        if (pick) {
          e.preventDefault()
          pickSlash(pick)
          return
        }
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setSlashOpen(false)
        return
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  const working = hardState === 'running' || hardState === 'awaiting_confirm'

  return (
    <div className="convo">
      <header className="convo-hero">
        <div className="convo-brand">
          <h1>Rau</h1>
          <p className="convo-sub">
            <span className={`state-dot ${working ? 'working' : ''}`} />
            {working ? 'Still working on something — talk whenever.' : 'One continuous mind. Just talk.'}
          </p>
        </div>
        <div className="convo-eyes">
          <ClawdAvatar emotion={emotion} busy={sending} />
          <Link to="/face" className="convo-room-link">
            Open the room →
          </Link>
        </div>
      </header>

      {confirm && (
        <div className="convo-confirm">
          <div className="confirm-copy">
            <strong>Needs your yes</strong>
            <p>{confirm.summary}</p>
          </div>
          <div className="row">
            <button className="btn danger sm" onClick={() => api.confirm(false, confirm.id).then(refresh)}>
              Deny
            </button>
            <button className="btn primary sm" onClick={() => api.confirm(true, confirm.id).then(refresh)}>
              Allow
            </button>
          </div>
        </div>
      )}

      <section ref={threadRef} className="convo-thread">
        {log.length === 0 && <div className="convo-empty">Say something — voice or text.</div>}
        {log.map((m, i) => {
          const used =
            m.role === 'user' ? matchSlash(String(m.text || ''), commands) : null
          return (
            <article
              key={`${i}-${m.time}`}
              className={`convo-msg ${m.role}${used ? ' slash-msg' : ''}`}
            >
              <div className="meta">
                <span className="who">{m.role === 'user' ? 'You' : 'Rau'}</span>
                <span className="time">{m.time}</span>
              </div>
              {used ? (
                <>
                  <div className="slash-pill">
                    <span className="slash-pill-mark">/</span>
                    {used.cmd.name}
                  </div>
                  {used.arg ? (
                    <ChatMarkdown className="slash-arg" text={used.arg} />
                  ) : (
                    <p className="slash-empty">{used.cmd.description || 'Command'}</p>
                  )}
                </>
              ) : (
                <ChatMarkdown text={m.text || ''} />
              )}
            </article>
          )
        })}
        {sending && (
          <div className="convo-typing">
            <i />
            <i />
            <i />
          </div>
        )}
        <div ref={bottomRef} aria-hidden className="convo-thread-end" />
      </section>

      <footer ref={composeRef} className="convo-compose">
        <div className="compose-wrap">
          <SlashMenu
            open={showSlashMenu}
            commands={slashSuggestions}
            activeIndex={Math.min(slashIndex, Math.max(0, slashSuggestions.length - 1))}
            onHover={setSlashIndex}
            onPick={pickSlash}
          />
          {activeSlash && (
            <div className="compose-slash-chip" aria-live="polite">
              {activeSlash.cmd.slash}
              <span>
                {activeSlash.arg
                  ? activeSlash.arg.length > 42
                    ? `${activeSlash.arg.slice(0, 42)}…`
                    : activeSlash.arg
                  : activeSlash.cmd.description || 'ready'}
              </span>
            </div>
          )}
          <div className={`compose-box${slashDraft ? ' is-slash' : ''}`}>
            <textarea
              ref={inputRef}
              rows={1}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={onComposeKey}
              placeholder="Talk to Rau…  try /skills"
              autoFocus
            />
            <button
              className="send-btn"
              disabled={!draft.trim() || sending}
              onClick={send}
              aria-label="Send"
            >
              {sending ? (
                <i className="spinner" />
              ) : (
                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <path d="M3 10h13M11 5l5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              )}
            </button>
          </div>
        </div>
        <p className="compose-hint">
          {showSlashMenu
            ? '↑↓ to browse · Tab/Enter to pick · Esc to dismiss'
            : 'Enter sends · Shift+Enter for a new line · / for commands'}
        </p>
      </footer>
    </div>
  )
}
