import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type RefObject,
} from 'react'
import { Link } from '../router'
import ChatMarkdown from '../components/ChatMarkdown'
import ClawdAvatar from '../components/ClawdAvatar'
import PermissionMenu from '../components/PermissionMenu'
import SlashMenu from '../components/SlashMenu'
import { api } from '../api'
import { live } from '../live'
import { useMode } from '../mode'
import { useVoiceSession } from '../voice'
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
  const { mode } = useMode()
  const voice = useVoiceSession({ enabled: mode === 'voice' })
  const [log, setLog] = useState<any[]>([])
  const [emotion, setEmotion] = useState('idle')
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [confirm, setConfirm] = useState<any>(null)
  const [hardState, setHardState] = useState('')
  const [commands, setCommands] = useState<SlashCmd[]>(() => mergeSkillCommands([]))
  const [slashIndex, setSlashIndex] = useState(0)
  const [slashOpen, setSlashOpen] = useState(true)
  /** The message just sent, echoed locally until the hub's log includes it. */
  const [pending, setPending] = useState<{ role: 'user'; text: string; time: string } | null>(null)
  /**
   * The reply arriving right now, streamed over `/ws`.
   *
   * The HTTP response still carries the finished text, so this is not what
   * makes the answer appear — it is what makes it appear *progressively*, and
   * what gives a phrase-anchored body cue a moment at which its phrase became
   * visible to fire on.
   */
  const [streaming, setStreaming] = useState<{ turnId: string; text: string } | null>(null)
  const [sendError, setSendError] = useState('')
  const [offline, setOffline] = useState(false)
  const threadRef = useRef<HTMLElement>(null)
  const composeRef = useRef<HTMLElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const refreshingRef = useRef(false)
  const failsRef = useRef(0)
  /** Whether the user is reading at the bottom — only then do we auto-scroll. */
  const stickRef = useRef(true)
  /** Ignore model-speed chat_delta while a voice turn is speaking. */
  const voiceActiveRef = useRef(false)

  useComposerRubberBand(threadRef, composeRef)

  const voiceTurnActive =
    mode === 'voice' &&
    (voice.phase === 'speaking' || voice.phase === 'thinking' || !!voice.spokenText)
  voiceActiveRef.current = voiceTurnActive

  async function refresh() {
    // Polls that outlive their interval slot must not stack up or land
    // out of order and flash an older log over a newer one.
    if (refreshingRef.current) return
    refreshingRef.current = true
    try {
      const [l, e, s] = await Promise.all([api.log(), api.emotion(), api.status()])
      setLog(l.log || [])
      setEmotion((e.emotion || 'idle').toLowerCase())
      setConfirm(s.confirm || null)
      setHardState(s.hard_task?.state || 'idle')
      failsRef.current = 0
      setOffline(false)
    } catch {
      // One miss is a blip; two in a row is worth telling the user about.
      failsRef.current += 1
      if (failsRef.current >= 2) setOffline(true)
    } finally {
      refreshingRef.current = false
    }
  }

  useEffect(() => {
    refresh()
    const id = setInterval(() => {
      if (!live.isConnected()) void refresh()
    }, 15_000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    api
      .skills()
      .then((d) => setCommands(mergeSkillCommands(d.skills || [])))
      .catch(() => setCommands(mergeSkillCommands([])))
  }, [])

  useEffect(() =>
    live.subscribe((event) => {
      const turnId = typeof event.turn_id === 'string' ? event.turn_id : ''
      const text = typeof event.text === 'string' ? event.text : ''
      switch (event.kind) {
        case 'chat_started':
          // Voice turns paint from playback; keep the text stream for chat mode.
          if (voiceActiveRef.current || mode === 'voice') {
            setStreaming(null)
            break
          }
          setStreaming({ turnId, text: '' })
          break
        case 'chat_delta':
          if (voiceActiveRef.current || mode === 'voice') break
          setStreaming((prev) =>
            prev && prev.turnId !== turnId ? prev : { turnId, text },
          )
          break
        case 'chat_done':
          if (voiceActiveRef.current || mode === 'voice') {
            setStreaming(null)
            break
          }
          // Hold the finished text until the polled log catches up with it,
          // otherwise the reply blinks out and back in again.
          setStreaming((prev) => (prev && prev.turnId !== turnId ? prev : { turnId, text }))
          void refresh()
          break
        case 'chat_error':
          setStreaming((prev) => (prev && prev.turnId !== turnId ? prev : null))
          void refresh()
          break
        case 'hard_task':
        case 'confirm_request':
        case 'confirm_result':
          void refresh()
          break
      }
    }),
  [mode])

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

  // The pending echo disappears once the hub's log has caught up with it.
  const displayLog = useMemo(() => {
    if (!pending) return log
    const last = log[log.length - 1]
    if (last?.role === 'user' && String(last.text || '') === pending.text) return log
    return [...log, pending]
  }, [log, pending])

  // Same idea for the streamed reply: it hands over to the polled log the
  // moment that log contains it, so the message never appears twice.
  // In voice mode the bubble tracks the ear (spokenText), not chat_delta.
  const liveReply = useMemo(() => {
    if (mode === 'voice') {
      const heard = voice.spokenText.trim()
      if (!heard) return ''
      const last = log[log.length - 1]
      if (last && last.role !== 'user' && String(last.text || '').trim() === heard) return ''
      // While still speaking, show heard progress even if the log already has
      // the full reply — avoid duplicating once idle and log matches.
      if (voice.phase !== 'speaking' && voice.phase !== 'thinking') {
        if (last && last.role !== 'user' && String(last.text || '').startsWith(heard)) {
          return ''
        }
      }
      return heard
    }
    const text = streaming?.text?.trim()
    if (!text) return ''
    const last = log[log.length - 1]
    if (last && last.role !== 'user' && String(last.text || '').trim() === text) return ''
    return text
  }, [mode, voice.spokenText, voice.phase, streaming, log])

  // Track whether the reader is at the bottom; scrolling up to reread must
  // not be yanked back down by the next poll.
  useEffect(() => {
    const thread = threadRef.current
    if (!thread) return
    const onScroll = () => {
      stickRef.current =
        thread.scrollTop + thread.clientHeight >= thread.scrollHeight - 80
    }
    thread.addEventListener('scroll', onScroll, { passive: true })
    return () => thread.removeEventListener('scroll', onScroll)
  }, [])

  // Scroll the thread pane only — never the page under the composer.
  useEffect(() => {
    const thread = threadRef.current
    if (!thread || !stickRef.current) return
    requestAnimationFrame(() => {
      thread.scrollTop = thread.scrollHeight
    })
  }, [displayLog, sending, liveReply])

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
    setSlashOpen(false)
    setSendError('')
    // Sending your own message always belongs at the bottom.
    stickRef.current = true

    // Voice mode: same socket as speech so the reply streams as audio and the
    // live bubble tracks playback, not chat_delta.
    if (mode === 'voice' && voice.connected) {
      setDraft('')
      setPending({
        role: 'user',
        text,
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      })
      voice.sendText(text)
      return
    }

    setSending(true)
    setDraft('')
    setPending({
      role: 'user',
      text,
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    })
    try {
      await api.chat(text)
      failsRef.current = 0
      setOffline(false)
      await refresh()
    } catch {
      // Give the message back instead of losing it.
      setDraft(text)
      setSendError('Could not reach Rau — that message was not sent.')
    } finally {
      setPending(null)
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
        const pick = slashSuggestions[clampedSlashIndex]
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
  const clampedSlashIndex = Math.min(slashIndex, Math.max(0, slashSuggestions.length - 1))

  return (
    <div className="convo">
      <header className="convo-hero">
        <div className="convo-brand">
          <h1>Rau</h1>
          <p className="convo-sub" role="status">
            <span className={`state-dot ${offline ? 'offline' : working ? 'working' : ''}`} />
            {offline
              ? 'Can’t reach Rau right now — retrying…'
              : working
                ? 'Still working on something — talk whenever.'
                : 'One continuous mind. Just talk.'}
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
            <button className="btn danger sm" onClick={() => api.confirm(false, confirm.id).then(refresh).catch(() => {})}>
              Deny
            </button>
            <button className="btn primary sm" onClick={() => api.confirm(true, confirm.id).then(refresh).catch(() => {})}>
              Allow
            </button>
          </div>
        </div>
      )}

      <section
        ref={threadRef}
        className="convo-thread"
        role="log"
        aria-live="polite"
        aria-label="Conversation with Rau"
      >
        {displayLog.length === 0 && <div className="convo-empty">Say something — voice or text.</div>}
        {displayLog.map((m, i) => {
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
        {liveReply && (
          <article className="convo-msg rau is-streaming">
            <div className="meta">
              <span className="who">Rau</span>
              <span className="time">now</span>
            </div>
            <ChatMarkdown text={liveReply} />
          </article>
        )}
        {(sending || (mode === 'voice' && voice.phase === 'thinking')) && !liveReply && (
          <div className="convo-typing" role="status" aria-label="Rau is replying">
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
            activeIndex={clampedSlashIndex}
            onHover={setSlashIndex}
            onPick={pickSlash}
          />
          {sendError && (
            <p className="compose-error" role="alert">
              {sendError}
            </p>
          )}
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
              aria-label="Message Rau"
              role="combobox"
              aria-autocomplete="list"
              aria-expanded={showSlashMenu}
              aria-controls="slash-menu-list"
              aria-activedescendant={showSlashMenu ? `slash-opt-${clampedSlashIndex}` : undefined}
              autoFocus
            />
            <div className="compose-actions">
              <PermissionMenu />
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
