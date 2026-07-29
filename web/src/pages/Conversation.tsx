/* oxlint-disable react/only-export-components -- the echo hand-off is exported for its regression tests */
import {
  memo,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type RefObject,
} from 'react'
import { Link } from '../router'
import ChatMarkdown from '../components/ChatMarkdown'
import ActivityInspector, {
  ActivityChip,
} from '../components/ActivityInspector'
import ClawdAvatar from '../components/ClawdAvatar'
import PermissionMenu from '../components/PermissionMenu'
import SlashMenu from '../components/SlashMenu'
import { HyperToggle } from '../components/HyperMode'
import { ThreadSkeleton } from '../components/PageSkeleton'
import { api } from '../api'
import { live } from '../live'
import {
  useMode,
  modeListens,
  modeSupportsHyper,
  modeUsesVoice,
  type Mode,
  type VoiceLatencyProfile,
} from '../mode'
import { useVoiceSession, type VoicePhase } from '../voice'
import { useLocale } from '../i18n'
import {
  filterSlashCommands,
  matchSlash,
  mergeSkillCommands,
  readSlashDraft,
  type SlashCmd,
} from '../slash'
import './Conversation.css'

/**
 * Rubber-band overscroll: past the bottom, compress/repulse the composer.
 *
 * Takes the composer element, not a ref to it. The composer is unmounted on the
 * `space-talk` leg of the mode cycle and remounts as a NEW node, which a ref
 * would silently keep out of date — the effect would go on writing to a
 * detached footer, and `offsetHeight` does not flush layout on a detached node,
 * so the spring would lose its start value again. Passing the node through
 * state re-runs this when it changes, and covers mounting straight into
 * space-talk, where the composer does not exist yet — which used to leave the
 * band dead for the whole session, since the mode is persisted.
 *
 * Re-running is not quite sufficient on its own: cleanup here is passive, so a
 * timer armed before the unmount can still fire after it. `release` checks the
 * node is connected for that reason.
 */
function useComposerRubberBand(
  threadRef: RefObject<HTMLElement | null>,
  compose: HTMLElement | null,
) {
  useEffect(() => {
    const thread = threadRef.current
    if (!thread || !compose) return

    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduce) return

    const MAX = 72
    let raw = 0
    let touching = false
    let lastTouchY = 0
    let releaseTimer: number | null = null
    let settleTimer: number | null = null
    let springing = false
    let frame = 0
    let queued: { pull: number; snapping: boolean } | null = null

    const atBottom = () =>
      thread.scrollTop + thread.clientHeight >= thread.scrollHeight - 2

    const apply = () => {
      frame = 0
      const job = queued
      queued = null
      if (!job) return
      const { pull, snapping } = job
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

    /*
      The travel is queued, not written. A wheel or touchmove handler reads the
      thread's scroll geometry to decide whether it owns the gesture, and a
      trackpad delivers several of those per frame — writing the transforms
      inline would make every read after the first one force a fresh layout of
      the whole thread. Deferring the writes to the frame keeps reads and
      writes in separate phases, and collapses N events into one write.
    */
    const paint = (nextRaw: number, snapping: boolean) => {
      raw = snapping ? 0 : Math.max(0, nextRaw)
      // Soft resistance — more drag → less travel.
      queued = { pull: MAX * (1 - Math.exp(-raw / MAX)), snapping }
      if (!frame) frame = requestAnimationFrame(apply)
    }

    /** Land a queued paint now — the caller is about to write past it. */
    const flush = () => {
      if (!frame) return
      cancelAnimationFrame(frame)
      apply()
    }

    /*
      Land the pull, force it to be computed, and only then queue the snap.

      Two things have to be true for the spring to be visible. The pull the
      gesture ended on must reach the DOM — `paint` replaces `queued` wholesale,
      so snapping first simply discards it, and when touchmove and touchend fall
      in one frame (routine at a 120Hz touch rate) nothing had been committed at
      all and the band sprang 0 → 0.

      Landing it is not enough on its own, though: rAF callbacks run before the
      style step of the same frame, so a flushed write followed by a queued snap
      both resolve against one recalculation and the browser never computes the
      pulled value to transition away from. Reading `offsetHeight` between them
      forces that recalculation. It is a synchronous layout, which is exactly
      what the queue exists to avoid — but once per release, not once per
      touchmove, and it is the only way the transition has a start value.
    */
    const release = () => {
      if (releaseTimer != null) {
        window.clearTimeout(releaseTimer)
        releaseTimer = null
      }
      /*
        This effect is passive, so its cleanup runs a task after the commit that
        removed the composer. A wheel gesture's 90ms timer can land inside that
        gap — shift+space toggles the mode, so the unmount is not tied to a
        click on the composer itself. On a detached node `offsetHeight` forces
        no layout and the spring would silently lose its start value again.
      */
      if (!compose.isConnected) return
      if (raw <= 0.5) {
        // Nothing to spring from here — the band never really moved, and this
        // commit carries no transition, so landing 0 directly is correct.
        paint(0, false)
        flush()
        compose.style.transition = ''
        thread.style.transition = ''
        springing = false
        return
      }
      springing = true
      flush()
      void compose.offsetHeight
      paint(0, true)
      flush()
      // Tracked, because a stale one firing mid-flight would clear `transition`
      // on both elements and cancel the spring that is currently running — the
      // composer would pop to its end position instead of settling.
      if (settleTimer != null) window.clearTimeout(settleTimer)
      settleTimer = window.setTimeout(() => {
        settleTimer = null
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
      if (settleTimer != null) window.clearTimeout(settleTimer)
      if (frame) cancelAnimationFrame(frame)
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
  }, [threadRef, compose])
}

/** A locally-echoed send waiting for the hub's log to catch up with it. */
export type PendingEcho = {
  role: 'user'
  text: string
  time: string
  /**
   * The log's last entry at send time. Positions are no anchor: the hub
   * trims the log at its cap, so the slot a message held at send time slides
   * left as new lines push old ones out. The echo is anchored to this entry.
   */
  anchor: { role: string; text: string; time: string } | null
}

/**
 * Whether the hub's log now holds a locally-echoed send.
 *
 * Only a match *after* the anchor's current position counts: an older
 * identical line (a second "yes") is a different message and must not
 * swallow this echo. If the anchor itself has been trimmed out of the log,
 * every line left arrived after the send, so any match is the echo.
 */
export function pendingEchoed(log: any[], pending: PendingEcho): boolean {
  let from = 0
  const anchor = pending.anchor
  if (anchor) {
    let at = -1
    for (let i = log.length - 1; i >= 0; i--) {
      const m = log[i]
      if (
        m?.role === anchor.role &&
        String(m?.text || '') === anchor.text &&
        String(m?.time || '') === anchor.time
      ) {
        at = i
        break
      }
    }
    if (at >= 0) from = at + 1
  }
  return log.some(
    (m, i) => i >= from && m?.role === 'user' && String(m.text || '') === pending.text,
  )
}

/** The echo to show until the hub logs the send, anchored to the log's tail. */
function pendingEchoFor(log: any[], text: string): PendingEcho {
  const last = log[log.length - 1]
  return {
    role: 'user',
    text,
    time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    anchor: last
      ? {
          role: String(last.role || ''),
          text: String(last.text || ''),
          time: String(last.time || ''),
        }
      : null,
  }
}

/**
 * The logged part of the thread.
 *
 * Split off and memoised because the page re-renders on every streamed token
 * and (before the composer moved out) on every keystroke, while the backlog
 * itself only changes when the hub's log does — and re-rendering it means
 * re-parsing every bubble's markdown and re-matching every slash command.
 */
const ThreadMessages = memo(function ThreadMessages({
  log,
  commands,
}: {
  log: any[]
  commands: SlashCmd[]
}) {
  const { t } = useLocale()
  /*
    Position is no key. The hub trims the log at its cap, so once it is full
    every entry slides left as a new one arrives, and an index-based key would
    hand each row its neighbour's identity — React would tear down and rebuild
    the whole thread, re-firing every msg-in animation and every inspector's
    activity fetch. Key on what the entry *is* instead, disambiguating repeats
    ("yes" twice in one minute) by how many like it came before.
  */
  const seen = new Map<string, number>()
  return (
    <>
      {log.map((m) => {
        const text = String(m.text || '')
        const sig = `${m.role}|${m.time}|${text.length}|${text.slice(0, 32)}`
        const nth = (seen.get(sig) || 0) + 1
        seen.set(sig, nth)
        const used = m.role === 'user' ? matchSlash(text, commands) : null
        return (
          <article
            key={`${sig}#${nth}`}
            className={`convo-msg ${m.role}${used ? ' slash-msg' : ''}`}
          >
            <div className="meta">
              <span className="who">{m.role === 'user' ? t('talk.you') : t('talk.rau')}</span>
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
                  <p className="slash-empty">{used.cmd.description || t('talk.command')}</p>
                )}
              </>
            ) : (
              <ChatMarkdown text={text} />
            )}
            {m.role !== 'user' && m.turn_id && (
              <ActivityInspector turnId={String(m.turn_id)} />
            )}
          </article>
        )
      })}
    </>
  )
})

/**
 * The composer.
 *
 * Split out so a keystroke re-renders one box instead of the whole thread —
 * the same split Face already makes for the room. What it does NOT own is the
 * draft: this box unmounts on the `space-talk` leg of the mode cycle, and text
 * the reader has typed must outlive that. So the draft is the page's, and only
 * the composer's own transient UI state (slash menu) lives here.
 */
function ConversationComposer({
  boxRef,
  commands,
  mode,
  voiceLatency,
  setVoiceLatency,
  voicePhase,
  voiceError,
  onSend,
  draft,
  setDraft,
  sendError,
  setSendError,
}: {
  boxRef: (el: HTMLElement | null) => void
  commands: SlashCmd[]
  mode: Mode
  voiceLatency: VoiceLatencyProfile
  setVoiceLatency: (profile: VoiceLatencyProfile) => void
  voicePhase: VoicePhase
  /** Empty unless the mode uses voice; the page decides that. */
  voiceError: string
  /** Deliver the trimmed message. Reject to hand the draft back. */
  onSend: (text: string) => Promise<void>
  draft: string
  setDraft: (text: string) => void
  sendError: string
  setSendError: (message: string) => void
}) {
  const { t } = useLocale()
  const [slashIndex, setSlashIndex] = useState(0)
  const [slashOpen, setSlashOpen] = useState(true)
  const inputRef = useRef<HTMLTextAreaElement>(null)

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
  const clampedSlashIndex = Math.min(slashIndex, Math.max(0, slashSuggestions.length - 1))

  useEffect(() => {
    setSlashIndex(0)
    setSlashOpen(true)
  }, [slashDraft?.token, slashDraft?.hasSpace])

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
    if (!text) return
    setSlashOpen(false)
    setSendError('')
    setDraft('')
    try {
      await onSend(text)
    } catch {
      // Give the newest message back instead of losing it. The page rejects
      // only for the turn that is still the newest one.
      setDraft(text)
      setSendError(t('talk.sendFailed'))
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
      void send()
    }
  }

  return (
    <footer ref={boxRef} className="convo-compose" data-tour="talk-composer">
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
        {voiceError && (
          <p className="compose-error" role="alert">
            {voiceError}
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
                : activeSlash.cmd.description || t('talk.ready')}
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
            placeholder={t('talk.placeholder')}
            aria-label={t('talk.messageLabel')}
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={showSlashMenu}
            aria-controls="slash-menu-list"
            aria-activedescendant={showSlashMenu ? `slash-opt-${clampedSlashIndex}` : undefined}
            autoFocus
          />
          <div className="compose-actions">
            {modeSupportsHyper(mode) && (
              <HyperToggle
                profile={voiceLatency}
                setProfile={setVoiceLatency}
                disabled={voicePhase !== 'idle'}
              />
            )}
            <PermissionMenu />
            <button
              className="send-btn"
              disabled={!draft.trim()}
              onClick={() => void send()}
              aria-label={t('talk.send')}
            >
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M3 10h13M11 5l5 5-5 5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </div>
      </div>
      <p className="compose-hint">
        {showSlashMenu
          ? t('talk.hintSlash')
          : mode === 'talk'
            ? t('talk.hintTalk')
            : mode === 'voice'
              ? t('talk.hintVoice')
              : t('talk.hintDefault')}
      </p>
    </footer>
  )
}

export default function Conversation() {
  const { t } = useLocale()
  const { mode, voiceLatency, setVoiceLatency } = useMode()
  const voiceOn = modeUsesVoice(mode)
  const voice = useVoiceSession({
    enabled: voiceOn,
    listen: modeListens(mode),
    pushToTalk: mode === 'space-talk',
    profile: modeSupportsHyper(mode) ? voiceLatency : 'normal',
  })
  const [log, setLog] = useState<any[]>([])
  /** Until the first fetch settles, an empty `log` means "unknown", not "none". */
  const [logLoaded, setLogLoaded] = useState(false)
  const [emotion, setEmotion] = useState('idle')
  const [sending, setSending] = useState(false)
  const [confirm, setConfirm] = useState<any>(null)
  const [hardState, setHardState] = useState('')
  const [commands, setCommands] = useState<SlashCmd[]>(() => mergeSkillCommands([]))
  /** The message just sent, echoed locally until the hub's log includes it. */
  const [pending, setPending] = useState<PendingEcho | null>(null)
  /**
   * The reply arriving right now, streamed over `/ws`.
   *
   * The HTTP response still carries the finished text, so this is not what
   * makes the answer appear — it is what makes it appear *progressively*, and
   * what gives a phrase-anchored body cue a moment at which its phrase became
   * visible to fire on.
   */
  const [streaming, setStreaming] = useState<{ turnId: string; text: string } | null>(null)
  const [offline, setOffline] = useState(false)
  const [deskWorking, setDeskWorking] = useState(() => live.isWorking())
  const [activityOpen, setActivityOpen] = useState(false)
  /*
    The draft is the page's, not the composer's: cycling the mode through
    `space-talk` unmounts the composer, and unsent text has to survive that.
    Keeping it here costs nothing — `ThreadMessages` is memoised on `log` and
    `commands`, so a keystroke still re-renders only the box.
  */
  const [draft, setDraft] = useState('')
  const [sendError, setSendError] = useState('')
  const threadRef = useRef<HTMLElement>(null)
  // State, not a ref: the composer unmounts on `space-talk` and comes back as a
  // different node, and the rubber band has to follow it. See the hook.
  const [composeEl, setComposeEl] = useState<HTMLElement | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const refreshingRef = useRef(false)
  const failsRef = useRef(0)
  /** Only the newest HTTP turn may settle composer state. Older requests are
   * allowed to drain so an in-flight side-effecting tool can finish safely. */
  const sendSeqRef = useRef(0)
  /** Whether the user is reading at the bottom — only then do we auto-scroll. */
  const stickRef = useRef(true)
  /** Ignore model-speed chat_delta while a voice turn is speaking. */
  const voiceActiveRef = useRef(false)

  useComposerRubberBand(threadRef, composeEl)

  const voiceTurnActive =
    voiceOn &&
    (voice.phase === 'speaking' || voice.phase === 'thinking' || !!voice.spokenText)
  voiceActiveRef.current = voiceTurnActive
  async function refresh() {
    // Polls that outlive their interval slot must not stack up or land
    // out of order and flash an older log over a newer one.
    if (refreshingRef.current) return
    refreshingRef.current = true
    try {
      const [l, e, s] = await Promise.all([api.log(), api.emotion(), api.health()])
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
      // Settled either way: a failed load still has to release the thread, or
      // the offline notice would sit above a permanent shimmer.
      setLogLoaded(true)
    }
  }

  useEffect(() => {
    refresh()
    const id = setInterval(() => {
      if (!live.isConnected()) void refresh()
    }, 15_000)
    const offWork = live.subscribeWorking(setDeskWorking)
    const offStatus = live.onStatus((connectedNow) => {
      if (connectedNow) {
        // The poll stands down while the socket is up, so a hub restart is
        // only ever noticed here: pull the log, drop the offline banner.
        void refresh()
      } else {
        // A reply streaming over the dead socket gets no chat_done.
        setStreaming(null)
      }
    })
    return () => {
      clearInterval(id)
      offWork()
      offStatus()
    }
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
          // Voice/talk turns paint from playback; keep the text stream for chat.
          if (voiceActiveRef.current || voiceOn) {
            setStreaming(null)
            break
          }
          setStreaming({ turnId, text: '' })
          break
        case 'chat_delta':
          if (voiceActiveRef.current || voiceOn) break
          setStreaming((prev) =>
            prev && prev.turnId !== turnId ? prev : { turnId, text },
          )
          break
        case 'chat_done':
          if (voiceActiveRef.current || voiceOn) {
            setStreaming(null)
            // The voice branch used to trust say_end to fold the turn in, but
            // non-voice producers (game table talk, …) have no say_end — pull
            // the log now or those lines never appear.
            void refresh()
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
  [voiceOn])

  // A voice turn settles with say_end, which the hub sends only after both
  // sides of the exchange are in its log — chat_done arrives while TTS is
  // still playing, before the reply is logged. Fold the turn into the thread
  // then; nothing else refreshes while the live socket is up.
  useEffect(() => {
    if (voiceOn && voice.lastTurn) void refresh()
  }, [voiceOn, voice.lastTurn])

  // The pending echo is a stand-in until the hub's log includes the message.
  // Keeping it past that point re-appends it as a ghost copy the moment the
  // log moves on to Rau's reply. Only a match after the anchor counts: an
  // older identical line is a different message, and must not swallow this
  // one's echo.
  useEffect(() => {
    if (!pending) return
    if (pendingEchoed(log, pending)) setPending(null)
  }, [log, pending])

  // The pending echo disappears once the hub's log has caught up with it.
  const displayLog = useMemo(() => {
    if (!pending) return log
    const last = log[log.length - 1]
    if (last?.role === 'user' && String(last.text || '') === pending.text) return log
    return [...log, pending]
  }, [log, pending])

  // Same idea for the streamed reply: it hands over to the polled log the
  // moment that log contains it, so the message never appears twice.
  // In voice/talk mode the bubble tracks the ear (spokenText), not chat_delta.
  const liveReply = useMemo(() => {
    if (voiceOn) {
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
  }, [voiceOn, voice.spokenText, voice.phase, streaming, log])

  // Your own line as the mic hears it, before the hub logs it — the same
  // transcript the room's voice HUD shows. Only while the turn it belongs to
  // is in play: finalText outlives its turn, and an old transcript is not a
  // new message. Once the log holds the line it renders itself.
  const voiceLine = useMemo(() => {
    if (!voiceOn || voice.phase === 'idle') return ''
    const heard = (voice.partial || voice.finalText).trim()
    if (!heard) return ''
    const lastUser = log.map((m) => m?.role).lastIndexOf('user')
    if (lastUser >= 0 && String(log[lastUser]?.text || '').trim() === heard) return ''
    if (pending?.text.trim() === heard) return ''
    return heard
  }, [voiceOn, voice.phase, voice.partial, voice.finalText, log, pending])

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
  // Tokens arriving faster than the display rate each re-run this; without the
  // cancel they would stack several measure-and-scroll pairs into one frame.
  useEffect(() => {
    const thread = threadRef.current
    if (!thread || !stickRef.current) return
    const frame = requestAnimationFrame(() => {
      thread.scrollTop = thread.scrollHeight
    })
    return () => cancelAnimationFrame(frame)
  }, [displayLog, sending, liveReply, voiceLine])

  async function send(text: string) {
    const sendSeq = ++sendSeqRef.current
    // Sending your own message always belongs at the bottom.
    stickRef.current = true

    // Voice/talk: same socket as speech so the reply streams as audio and the
    // live bubble tracks playback, not chat_delta.
    if (voiceOn && voice.connected) {
      // A voice turn supersedes any older HTTP turn too.
      setSending(false)
      setPending(pendingEchoFor(log, text))
      voice.sendText(text)
      return
    }

    setSending(true)
    setPending(pendingEchoFor(log, text))
    try {
      await api.chat(text)
      if (sendSeq !== sendSeqRef.current) return
      failsRef.current = 0
      setOffline(false)
      await refresh()
    } catch {
      // Only the newest turn's failure goes back to the composer: a superseded
      // request must never overwrite what the user is typing now.
      if (sendSeq === sendSeqRef.current) throw new Error('send failed')
    } finally {
      if (sendSeq === sendSeqRef.current) {
        setPending(null)
        setSending(false)
      }
    }
  }

  const working = hardState === 'running' || hardState === 'awaiting_confirm'

  return (
    <div className={`convo${activityOpen ? ' has-activity' : ''}`}>
      <div className="convo-main">
      <header className="convo-hero">
        <div className="convo-brand">
          <h1>Rau</h1>
          <p className="convo-sub" role="status">
            <span className={`state-dot ${offline ? 'offline' : working ? 'working' : ''}`} />
            {offline ? t('talk.offline') : working ? t('talk.working') : t('talk.idle')}
          </p>
        </div>
        <div className="convo-eyes">
          <ClawdAvatar emotion={emotion} busy={sending} />
          <Link to="/face" className="convo-room-link">
            {t('talk.openRoom')}
          </Link>
          <ActivityChip
            open={activityOpen}
            onToggle={() => setActivityOpen((value) => !value)}
            className="convo-activity-chip"
          />
          {mode === 'space-talk' && (
            <div className="space-talk-controls" role="status">
              <span>
                {!voice.connected
                  ? t('talk.spaceConnecting')
                  : voice.phase === 'thinking'
                    ? t('talk.spaceThinking')
                    : voice.phase === 'speaking'
                      ? t('talk.spaceSpeaking')
                      : voice.phase === 'listening'
                        ? t('talk.spaceListening')
                        : t('talk.spaceHold')}
              </span>
              <HyperToggle
                profile={voiceLatency}
                setProfile={setVoiceLatency}
                disabled={voice.phase !== 'idle'}
              />
              {voice.error && <em>{voice.error}</em>}
            </div>
          )}
        </div>
      </header>

      {confirm && (
        <div className="convo-confirm">
          <div className="confirm-copy">
            <strong>{t('talk.confirmTitle')}</strong>
            <p>{confirm.summary}</p>
          </div>
          <div className="row">
            <button className="btn danger sm" onClick={() => api.confirm(false, confirm.id).then(refresh).catch(() => {})}>
              {t('talk.deny')}
            </button>
            <button className="btn primary sm" onClick={() => api.confirm(true, confirm.id).then(refresh).catch(() => {})}>
              {t('talk.allow')}
            </button>
          </div>
        </div>
      )}

      <section
        ref={threadRef}
        className="convo-thread"
        role="log"
        aria-live="polite"
        aria-label={t('talk.threadLabel')}
      >
        {displayLog.length === 0 &&
          (logLoaded ? (
            <div className="convo-empty">{t('talk.empty')}</div>
          ) : (
            <ThreadSkeleton />
          ))}
        <ThreadMessages log={displayLog} commands={commands} />
        {voiceLine && (
          <article className="convo-msg user is-streaming">
            <div className="meta">
              <span className="who">{t('talk.you')}</span>
              <span className="time">{t('talk.now')}</span>
            </div>
            <ChatMarkdown text={voiceLine} />
          </article>
        )}
        {liveReply && (
          <article className="convo-msg rau is-streaming">
            <div className="meta">
              <span className="who">{t('talk.rau')}</span>
              <span className="time">{t('talk.now')}</span>
            </div>
            <ChatMarkdown text={liveReply} />
            {streaming?.turnId && (
              <ActivityInspector turnId={streaming.turnId} />
            )}
          </article>
        )}
        {(sending ||
          deskWorking ||
          (voiceOn && voice.phase === 'thinking')) &&
          !liveReply && (
          <div
            className={`convo-typing${deskWorking ? ' working' : ''}`}
            role="status"
            aria-label={deskWorking ? t('talk.atComputerLabel') : t('talk.thinkingLabel')}
          >
            <i />
            <i />
            <i />
          </div>
        )}
        <div ref={bottomRef} aria-hidden className="convo-thread-end" />
      </section>

      {mode !== 'space-talk' && (
        <ConversationComposer
          boxRef={setComposeEl}
          commands={commands}
          mode={mode}
          voiceLatency={voiceLatency}
          setVoiceLatency={setVoiceLatency}
          voicePhase={voice.phase}
          voiceError={voiceOn ? voice.error : ''}
          onSend={send}
          draft={draft}
          setDraft={setDraft}
          sendError={sendError}
          setSendError={setSendError}
        />
      )}
      </div>

      {activityOpen && (
        <aside className="convo-activity-sidebar" aria-label={t('talk.sidebarLabel')}>
          <ActivityInspector
            global
            variant="sidebar"
            onClose={() => setActivityOpen(false)}
          />
        </aside>
      )}
    </div>
  )
}
