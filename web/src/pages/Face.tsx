import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react'
import { Link } from '../router'
import ClawdRoom, { type ClawdRoomApi } from '../components/ClawdRoom'
import ActivityInspector, {
  ActivityChip,
} from '../components/ActivityInspector'
import PermissionMenu from '../components/PermissionMenu'
import { EMPTY_SIGNALS, type Signals } from '../clawd/director'
import type { MotionName } from '../clawd/motions'
import {
  loadRoomVisual,
  saveRoomVisual,
  type RoomVisual,
} from '../clawd/roomVisual'
import {
  adoptStoredTier,
  clearTier,
  currentTier,
  setTier,
  tierIsAutomatic,
  type QualityTier,
} from '../clawd/quality'
import { useMode } from '../mode'
import { useVoiceSession } from '../voice'
import { api } from '../api'
import { live } from '../live'
import PanelViewer from '../components/PanelViewer'
import { panelStore, type PanelSummary } from '../panels'

import { gameStore, useGame } from '../games/kittens/useGame'

const GameTable = lazy(() => import('../games/kittens/GameTable'))
import {
  IDLE_FACE_STREAM,
  bubbleSpeechFromStream,
  reduceFaceStream,
  streamCaughtUp,
  type FaceStream,
} from '../faceStream'
import './Face.css'

const MOTION_BUTTONS: { id: MotionName; label: string }[] = [
  { id: 'wave', label: 'Wave' },
  { id: 'bounce', label: 'Bounce' },
  { id: 'celebrate', label: 'Celebrate' },
  { id: 'type', label: 'Type' },
  { id: 'think', label: 'Think' },
  { id: 'gaze', label: 'Gaze' },
  { id: 'sleep', label: 'Sleep' },
  { id: 'walk', label: 'Walk in place' },
]

const STATION_BUTTONS = ['window', 'plant', 'rug', 'centre', 'desk', 'shelf'] as const

/**
 * Coarse tag for the sentence Rau is about to say, so his body reacts to what
 * he means rather than on a timer. The model already emits `[HAPPY]`-style
 * markers that the hub strips before speaking; failing that, punctuation and a
 * few openers carry most of the signal.
 */
function tagOf(sentence: string): string | null {
  const marked = sentence.match(/\[(\w+)\]/)
  if (marked) return marked[1].toLowerCase()

  const s = sentence.trim().toLowerCase()
  if (!s) return null
  if (/^(hi|hey|hello|morning|welcome)\b/.test(s)) return 'greeting'
  if (/\b(sorry|afraid|unfortunately)\b/.test(s)) return 'uncertain'
  if (/\b(not sure|no idea|maybe|might be|possibly|i think)\b/.test(s)) return 'unsure'
  if (/\b(done|finished|got it|nailed it|works)\b/.test(s)) return 'celebrate'
  if (s.endsWith('?')) return 'question'
  if (s.endsWith('!')) return 'excited'
  return null
}

export default function Face() {
  const [signals, setSignals] = useState<Signals>(EMPTY_SIGNALS)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [panel, setPanel] = useState(false)
  const [activityOpen, setActivityOpen] = useState(false)
  const [wall, setWall] = useState<PanelSummary[]>(() => panelStore.list())
  const [hour, setHour] = useState<number | null>(null)
  const [lamp, setLamp] = useState<boolean | undefined>(undefined)
  const [roomVisual, setRoomVisual] = useState<RoomVisual>(() => loadRoomVisual())
  const [tier, setTierState] = useState<QualityTier>(() => currentTier())
  const [tierAuto, setTierAuto] = useState(() => tierIsAutomatic())
  // Whether there is a game on the table. Held here rather than inside the
  // table itself, because the room needs to know before deciding to mount it.
  const { table: game } = useGame()

  // A game survives a reload, and it survives you walking off to another route
  // and coming back. Asking once on arrival is what makes that true.
  useEffect(() => {
    void gameStore.refresh()
  }, [])

  // The tier is resolved once and held in the module, so a second tab changing
  // it would otherwise leave this one showing a choice it is no longer making.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== null && event.key !== 'rau.quality') return
      setTierState(adoptStoredTier())
      setTierAuto(tierIsAutomatic())
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [])
  const apiRef = useRef<ClawdRoomApi | null>(null)
  const lastReply = useRef({ at: 0, text: '', sig: '' })
  const sendingRef = useRef(false)
  /** Last sentence seen, so a repeated level tick is not read as a new line. */
  const spokenRef = useRef('')
  // The log already holds old replies on mount. Without this, the first poll
  // reads the newest one as if it just arrived and Clawd announces a stale
  // message every time the page loads.
  const seeded = useRef(false)
  /** Stamp `lastReplyAt` once per streamed turn so celebrate does not retrigger. */
  const streamStampRef = useRef('')

  const { mode } = useMode()
  const voice = useVoiceSession({ enabled: mode === 'voice' })
  const [stream, setStream] = useState<FaceStream>(IDLE_FACE_STREAM)
  const streamRef = useRef(stream)
  streamRef.current = stream

  const onReady = useCallback((a: ClawdRoomApi) => {
    apiRef.current = a
  }, [])

  // Face bypasses the app shell — still need the shared `/ws` channel.
  useEffect(() => {
    live.start()
  }, [])

  // Desktop pet mutex: Face open hides the pet; leaving Face restores it.
  useEffect(() => {
    void api.setPetVisibility({ face_open: true }).catch(() => undefined)
    return () => {
      void api.setPetVisibility({ face_open: false }).catch(() => undefined)
    }
  }, [])

  // Chat mode: `/ws` tokens paint the character bubble only (no composer panel).
  useEffect(() => {
    if (mode === 'voice') return
    if (stream.phase === 'off') {
      setSignals((s) => (s.streaming ? { ...s, streaming: false } : s))
      return
    }
    if (stream.phase === 'wait') {
      setSignals((s) => ({
        ...s,
        thinking: true,
        streaming: true,
        speech: null,
      }))
      return
    }
    const speech = bubbleSpeechFromStream(stream)
    if (!speech) {
      // First word still forming — keep thinking dots, not a character trickle.
      setSignals((s) => ({
        ...s,
        thinking: stream.phase === 'live',
        streaming: true,
        speech: null,
      }))
      return
    }
    const stampKey = stream.turnId || 'pending'
    const first = streamStampRef.current !== stampKey
    if (first) streamStampRef.current = stampKey
    setSignals((s) => ({
      ...s,
      thinking: false,
      // Stay "streaming" through done so desk-work cannot wipe the final line
      // before the log hand-off clears the buffer.
      streaming: true,
      speech,
      lastReplyAt: first ? Date.now() : s.lastReplyAt || Date.now(),
      sentenceTag: first ? tagOf(speech) : s.sentenceTag,
    }))
  }, [mode, stream])

  // Voice: ear-aligned captions only — never paint model-speed chat_delta.
  useEffect(() => {
    if (mode !== 'voice') return
    // `lastReplyAt` is an event stamp, not a heartbeat. Levels tick ~15x a
    // second, so re-stamping it on every tick would read to the director as a
    // stream of brand-new replies: the bubble would never expire and a
    // celebrate would retrigger forever.
    // Captions follow playback (spokenSentence), not synth-time lastSay —
    // otherwise the bubble jumps ahead of the ear while PCM queues.
    // Only caption while audio is actually playing — after the turn ends,
    // drop the bubble so the cumulative spokenText does not linger as a
    // full-reply dump.
    const speaking = voice.phase === 'speaking'
    const heard = speaking ? voice.spokenSentence || voice.spokenText : ''
    const fresh = !!heard && heard !== spokenRef.current
    if (fresh) spokenRef.current = heard
    if (!speaking && voice.phase !== 'thinking') spokenRef.current = ''
    setSignals((s) => ({
      ...s,
      userSpeaking: voice.phase === 'listening',
      rauSpeaking: speaking,
      userLevel: voice.micLevel,
      rauLevel: voice.outLevel,
      thinking: voice.phase === 'thinking',
      // Keep captions visible if a tool fires while audio is still playing.
      streaming: speaking,
      speech: heard || null,
      lastReplyAt: fresh ? Date.now() : s.lastReplyAt,
      sentenceTag: fresh ? tagOf(heard) : s.sentenceTag,
      jobs: voice.tools.filter((t) => t.name === 'start_hard_task').map((t) => String(t.args.goal ?? '')),
    }))
  }, [
    mode,
    voice.phase,
    voice.micLevel,
    voice.outLevel,
    voice.spokenSentence,
    voice.spokenText,
    voice.tools,
  ])

  // A cut-off reply is its own beat: he flinches, then picks up from what the
  // user actually heard.
  useEffect(() => {
    if (voice.lastTurn?.interrupted) {
      setSignals((s) => ({ ...s, interruptedAt: voice.lastTurn?.at ?? Date.now() }))
    }
  }, [voice.lastTurn])

  const refresh = useCallback(async () => {
    try {
      const [log, emo, status] = await Promise.all([api.log(), api.emotion(), api.status()])
      const entries: any[] = log.log || []
      // Newest assistant line drives the speech bubble in chat mode only.
      // Voice mode already captions from playback; dumping the full log line
      // here re-opens the bubble with the whole reply after he finishes.
      const idx = entries.map((m) => m.role !== 'user').lastIndexOf(true)
      const reply = idx >= 0 ? entries[idx] : null
      if (reply?.text) {
        // Do NOT include entries.length — a new user turn grows the log and
        // would re-fire the previous Rau line as if it were fresh.
        const sig = `${idx}|${reply.time}|${reply.text}`
        if (sig !== lastReply.current.sig) {
          // On the first poll the log already holds old replies; record them
          // but leave `at` at 0 so Clawd does not announce stale messages
          // every time the page loads.
          lastReply.current = {
            at: seeded.current ? Date.now() : 0,
            text: reply.text,
            sig,
          }
        }
      }
      seeded.current = true
      // User line is newest → still waiting on Rau (text or voice).
      const awaiting = entries.length > 0 && entries[entries.length - 1]?.role === 'user'
      const thinking = sendingRef.current || awaiting
      const active = streamRef.current
      if (streamCaughtUp(active, reply?.text)) {
        streamStampRef.current = ''
        setStream(IDLE_FACE_STREAM)
      }
      setSignals((prev) => {
        const next = {
          ...prev,
          emotion: (emo.emotion || 'idle').toLowerCase(),
          listening: !!status.listening,
          hardState: status.hard_task?.state || 'idle',
          awaitingConfirm: !!status.confirm,
        }
        // Mid-stream: ambient hub fields only — the stream effect owns speech.
        if (streamRef.current.phase !== 'off') {
          return next
        }
        if (mode === 'voice') {
          // Ambient hub state only — speech bubble stays with the voice effect.
          return {
            ...next,
            // Keep the "..." while the user turn is outstanding.
            thinking: thinking || prev.thinking,
          }
        }
        return {
          ...next,
          thinking,
          streaming: false,
          // Hold the previous line out of the bubble while waiting; director
          // shows a moving "..." from the thinking flag instead.
          lastReplyAt: thinking ? prev.lastReplyAt : lastReply.current.at,
          speech: thinking ? null : lastReply.current.text || null,
        }
      })
    } catch {
      /* hub down — Clawd keeps pottering about regardless */
    }
  }, [mode])

  useEffect(() => {
    refresh()
    const id = setInterval(() => {
      if (!live.isConnected()) void refresh()
    }, 15_000)
    const off = live.subscribe((event) => {
      if (
        event.kind === 'chat_started' ||
        event.kind === 'chat_delta' ||
        event.kind === 'chat_done' ||
        event.kind === 'chat_error'
      ) {
        setStream((prev) => reduceFaceStream(prev, event))
        if (event.kind === 'chat_done' || event.kind === 'chat_error') {
          const text = typeof event.text === 'string' ? event.text : ''
          const turnId = typeof event.turn_id === 'string' ? event.turn_id : ''
          if (event.kind === 'chat_done' && text.trim()) {
            lastReply.current = {
              at: Date.now(),
              text,
              sig: `stream|${turnId}|${text}`,
            }
          }
          void refresh()
        }
        return
      }
      if (
        event.kind === 'hard_task' ||
        event.kind === 'confirm_request' ||
        event.kind === 'confirm_result'
      ) {
        void refresh()
      }
    })
    const offWork = live.subscribeWorking((working) => {
      setSignals((s) => (s.working === working ? s : { ...s, working }))
    })
    return () => {
      clearInterval(id)
      off()
      offWork()
    }
  }, [refresh])

  async function send() {
    const text = draft.trim()
    if (!text || sending) return

    // In voice mode the turn belongs to the socket, so typing goes down the
    // same path and comes back as speech.
    if (mode === 'voice' && voice.connected) {
      setDraft('')
      setStream(IDLE_FACE_STREAM)
      streamStampRef.current = ''
      voice.sendText(text)
      return
    }

    setSending(true)
    sendingRef.current = true
    setDraft('')
    streamStampRef.current = ''
    setStream({ turnId: '', text: '', phase: 'wait' })
    setSignals((s) => ({
      ...s,
      thinking: true,
      streaming: true,
      speech: null,
    }))
    try {
      await api.chat(text)
      await refresh()
    } catch {
      // Hub unreachable — hand the message back rather than dropping it.
      setStream(IDLE_FACE_STREAM)
      setDraft((d) => d || text)
    } finally {
      sendingRef.current = false
      setSending(false)
      await refresh()
    }
  }

  // Escape closes the director panel; Enter focuses the input.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setPanel(false)
        setActivityOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Panels Rau has put on the wall; the documents themselves are only ever
  // mounted inside PanelViewer's sandboxed frame.
  //
  // The room is also the only place a `present_panel` request is honoured: the
  // store just records it, and this claims it. That means Rau can say "look at
  // this" while you are somewhere else and it will be open and waiting the
  // moment you walk in, instead of a modal appearing over your conversation.
  useEffect(
    () =>
      panelStore.subscribe(() => {
        setWall(panelStore.list())
        const presented = panelStore.takePending()
        if (presented) panelStore.show(presented)
      }),
    [],
  )

  useEffect(() => {
    api
      .panels()
      .then((d) => panelStore.replaceAll(d.panels || []))
      .catch(() => {})
    // A present that arrived while the user was on another route is claimed
    // here, on arrival.
    const waiting = panelStore.takePending()
    if (waiting) panelStore.show(waiting)
  }, [])

  const isVoice = mode === 'voice'

  return (
    <div className={`face ${isVoice ? 'voice-mode' : ''}`}>
      <ClawdRoom
        signals={signals}
        cinematic
        hourOverride={hour}
        lampOn={lamp}
        conversing={isVoice}
        roomVisual={roomVisual}
        onReady={onReady}
      />

      {wall.length > 0 && (
        <div className="face-wall" role="group" aria-label="Panels on the wall">
          {wall.map((p) => (
            // A row rather than one button: the close control cannot be nested
            // inside the open control, and the whole chip should still open.
            <div key={p.panel_id} className={`face-wall-row kind-${p.kind}`}>
              <button
                className="face-wall-chip"
                onClick={() => panelStore.show(p.panel_id)}
                title={
                  p.headings?.length
                    ? `Open “${p.title}” — ${p.headings.join(' · ')}`
                    : `Open “${p.title}”`
                }
              >
                <span className="face-wall-kind">{p.kind}</span>
                <span className="face-wall-title">{p.title}</span>
              </button>
              <button
                className="face-wall-close"
                // Optimistic: the hub broadcasts panel_closed, but waiting for
                // the round trip makes the click feel unacknowledged.
                onClick={() => {
                  panelStore.remove(p.panel_id)
                  api.closePanel(p.panel_id).catch(() => {})
                }}
                title={`Take “${p.title}” down`}
                aria-label={`Take ${p.title} down`}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      <PanelViewer />

      {/*
        The table, only when there is one. Mounted on the state rather than
        unconditionally: the thirteen inline-SVG card faces are their own chunk,
        and rendering an empty table would fetch all of it on every visit to the
        room for someone who never plays.
      */}
      {game && (
        <Suspense fallback={null}>
          <GameTable />
        </Suspense>
      )}

      <header className="face-top">
        <div className="face-top-left">
          <Link to="/" className="face-back" aria-label="Back to talk">
            ← Rau
          </Link>
          <div
            className="room-style-seg"
            role="radiogroup"
            aria-label="Room style"
          >
            <button
              type="button"
              role="radio"
              aria-checked={roomVisual === 'classic'}
              className={roomVisual === 'classic' ? 'is-active' : ''}
              onClick={() => {
                setRoomVisual('classic')
                saveRoomVisual('classic')
              }}
            >
              Classic
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={roomVisual === 'enhanced'}
              className={roomVisual === 'enhanced' ? 'is-active' : ''}
              onClick={() => {
                setRoomVisual('enhanced')
                saveRoomVisual('enhanced')
              }}
            >
              Enhanced
            </button>
          </div>
        </div>
        <div className="face-top-right">
          <ActivityChip
            open={activityOpen}
            onToggle={() => {
              setPanel(false)
              setActivityOpen((value) => !value)
            }}
            className="face-activity-chip"
          />
          <span className={`mode-pill ${isVoice ? 'on' : ''}`} title="Shift+Space to switch">
            <i className="mode-dot" />
            {isVoice ? 'voice' : 'chat'}
            <em>⇧␣</em>
          </span>
          {/*
            Dealing without asking him. He can still start a game himself with
            `start_kittens` — this is the shortcut for when you already know you
            want one and would rather not type a sentence about it.

            Hidden while a game is up: the table covers the room and carries its
            own Leave, so a second control here would only be a way to lose a
            game you were in the middle of.
          */}
          {!game && (
            <button
              className="face-toggle face-play"
              onClick={() => {
                setActivityOpen(false)
                setPanel(false)
                void gameStore.deal().catch(() => {})
              }}
              title="Deal a hand of Exploding Kittens"
            >
              Play
            </button>
          )}
          <button
            className={`face-toggle ${panel ? 'on' : ''}`}
            onClick={() => {
              setActivityOpen(false)
              setPanel((p) => !p)
            }}
            aria-expanded={panel}
          >
            Direct
          </button>
        </div>
      </header>

      {activityOpen && (
        <aside className="face-activity-drawer" aria-label="Rau agent activity">
          <ActivityInspector
            global
            defaultOpen
            onClose={() => setActivityOpen(false)}
          />
        </aside>
      )}

      {isVoice && (
        <div className="voice-hud">
          <div className={`voice-orb ${voice.phase}`}>
            <i
              className="voice-orb-fill"
              style={{
                transform: `scale(${1 + (voice.phase === 'speaking' ? voice.outLevel : voice.micLevel) * 1.8})`,
              }}
            />
          </div>
          <div className="voice-read" role="status" aria-live="polite">
            <span className={`voice-phase ${signals.working ? 'working' : voice.phase}`}>
              {!voice.connected
                ? 'connecting…'
                : signals.working
                  ? 'at the computer'
                  : voice.phase === 'listening'
                    ? 'listening'
                    : voice.phase === 'thinking'
                      ? 'thinking'
                      : voice.phase === 'speaking'
                        ? 'speaking — talk to cut in'
                        : 'ready'}
            </span>
            {/* Only Deepgram streams partials; the rest stay blank until final. */}
            {(voice.partial || voice.finalText) && (
              <p className={`voice-transcript ${voice.partial ? 'live' : ''}`}>
                {voice.partial || voice.finalText}
              </p>
            )}
            {voice.lastTurn?.interrupted && (
              <p className="voice-note">cut off — he only remembers what you heard</p>
            )}
            {voice.error && <p className="voice-note bad">{voice.error}</p>}
          </div>
          {signals.jobs.length > 0 && (
            <div className="voice-jobs">
              {signals.jobs.map((g, i) => (
                <span key={`${g}-${i}`} className="voice-job">
                  <i className="spinner" />
                  {g.slice(0, 40)}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      <div
        className={`face-panel ${panel ? 'open' : ''}`}
        aria-hidden={!panel}
        inert={!panel}
        hidden={!panel}
      >
        <div className="face-panel-inner">
          <h3>Motions</h3>
          <div className="chip-row">
            {MOTION_BUTTONS.map((m) => (
              <button key={m.id} className="chip" onClick={() => apiRef.current?.play(m.id)}>
                {m.label}
              </button>
            ))}
          </div>

          <h3>Send him to</h3>
          <div className="chip-row">
            {STATION_BUTTONS.map((s) => (
              <button key={s} className="chip" onClick={() => apiRef.current?.goTo(s)}>
                {s}
              </button>
            ))}
          </div>

          <h3>Detail</h3>
          <p className="face-hint">
            {tierAuto
              ? 'Chosen for this machine. Drop it if the room ever feels heavy.'
              : 'Set by you. Automatic judges the machine instead.'}
          </p>
          <div className="chip-row">
            {(['low', 'balanced', 'high'] as const).map((level) => (
              <button
                key={level}
                className={`chip ${!tierAuto && tier === level ? 'is-active' : ''}`}
                aria-pressed={!tierAuto && tier === level}
                onClick={() => {
                  setTier(level)
                  setTierState(level)
                  setTierAuto(false)
                }}
              >
                {level}
              </button>
            ))}
            <button
              className={`chip ${tierAuto ? 'is-active' : ''}`}
              aria-pressed={tierAuto}
              onClick={() => {
                clearTier()
                setTierState(currentTier())
                setTierAuto(true)
              }}
            >
              auto
            </button>
          </div>

          <h3>Room</h3>
          <label className="face-field">
            <span>Hour {hour === null ? '(live)' : hour.toFixed(1)}</span>
            <input
              type="range"
              min={0}
              max={24}
              step={0.5}
              value={hour ?? new Date().getHours()}
              onChange={(e) => setHour(Number(e.target.value))}
            />
          </label>
          <div className="chip-row">
            <button className="chip" onClick={() => setHour(null)}>
              Live time
            </button>
            <button className="chip" onClick={() => setLamp((l) => (l === true ? false : true))}>
              Lamp {lamp === undefined ? 'auto' : lamp ? 'on' : 'off'}
            </button>
            <button className="chip" onClick={() => setLamp(undefined)}>
              Auto lamp
            </button>
          </div>
        </div>
      </div>

      <footer className="face-compose">
        <div className="face-box">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') send()
            }}
            placeholder="Say something to Rau…"
            aria-label="Message Rau"
          />
          <PermissionMenu />
          <button
            className="face-send"
            disabled={!draft.trim() || sending}
            onClick={send}
            aria-label="Send"
          >
            {sending ? <i className="spinner" /> : '→'}
          </button>
        </div>
      </footer>
    </div>
  )
}
