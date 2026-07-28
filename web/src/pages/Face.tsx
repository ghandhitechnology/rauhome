/* oxlint-disable react/only-export-components -- the re-seat path is exported for its regression tests */
import { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react'
import { Link } from '../router'
import ClawdRoom, { type ClawdRoomApi } from '../components/ClawdRoom'
import ActivityInspector, {
  ActivityChip,
} from '../components/ActivityInspector'
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
import { useMode, modeLabel, modeListens, modeUsesVoice } from '../mode'
import { useVoiceSession } from '../voice'
import { api } from '../api'
import { live } from '../live'
import PanelViewer from '../components/PanelViewer'
import { panelStore, type PanelSummary } from '../panels'

import { gameStore, useGame } from '../games/kittens/useGame'
import { phaseStore, usePhase } from '../games/kittens/phase'
import {
  gameStore as chessStore,
  phaseStore as chessPhaseStore,
  useGame as useChess,
  usePhase as useChessPhase,
} from '../games/chess/useGame'
import { gameBridge } from '../clawd/gameBridge'
import FaceComposer from './FaceComposer'

const GameTable = lazy(() => import('../games/kittens/GameTable'))
const ChessTable = lazy(() => import('../games/chess/GameTable'))
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

/**
 * The table verbs, kept apart because they only read right seated.
 *
 * Play `sit` first, or `sitTable`, and then any of these — fired from a
 * standing pose they all look like he is falling out of a chair he was not
 * in, which is exactly the failure they are authored to avoid.
 */
const TABLE_BUTTONS: { id: MotionName; label: string }[] = [
  { id: 'sitTable', label: 'Sit at table' },
  { id: 'dealFlick', label: 'Deal' },
  { id: 'reachDraw', label: 'Draw' },
  { id: 'flickPlay', label: 'Play a card' },
  { id: 'slamNope', label: 'Nope' },
  { id: 'kittenRecoil', label: 'Kitten!' },
  { id: 'defuseRelief', label: 'Defused' },
  { id: 'smugLean', label: 'Smug' },
  { id: 'sitCheer', label: 'Win' },
  { id: 'slumpLoss', label: 'Lose' },
  { id: 'standUp', label: 'Stand up' },
]

const STATION_BUTTONS = ['window', 'plant', 'rug', 'table', 'centre', 'desk', 'shelf'] as const

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

/**
 * Seat him over a game that outlived the room.
 *
 * A game survives a reload, and it survives you walking off to another route
 * and coming back — but the choreographer does not, and the phase store
 * remembers a table state that a brand-new choreographer knows nothing
 * about.
 */
export async function reseatIntoGame(): Promise<void> {
  const phase = phaseStore.get()
  if (phase === 'idle') {
    phaseStore.adopt()
    return
  }
  if (phase === 'summoning') {
    // A 'summoning' at this point belongs to a begin()/arrive() from the
    // room that was navigated away from: its summon() is only ever resolved
    // by that choreographer's frame loop, which no longer exists. Seated
    // below without unwinding it first, the phase would never advance past
    // 'summoning' — him at an empty table, the cards never appearing.
    await phaseStore.end({ fast: true })
    phaseStore.adopt()
    return
  }
  // Came back to a game left running: adopt() stands down on a phase it did
  // not start, and nobody seats him — cards floating over a wandering crab.
  // seatInstantly() no-ops unless the choreographer is idle.
  gameBridge.choreography?.seatInstantly()
}

export default function Face() {
  const [signals, setSignals] = useState<Signals>(EMPTY_SIGNALS)
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
  const tablePhase = usePhase()
  // The other table. Only one of the two is ever out — the server puts the
  // cards away when the pieces come out — but the room has to know about both
  // to decide which one to mount and whether it is free to offer either.
  const { table: chess } = useChess()
  const chessPhase = useChessPhase()
  const [composerOpen, setComposerOpen] = useState(false)
  /** Whether the first look at the server has come back yet. */
  const gameSeeded = useRef(false)
  const chessSeeded = useRef(false)

  /*
    A game survives a reload, and it survives you walking off to another route
    and coming back. Asking once on arrival is what makes that true — and a
    game found on this first look has been going on the whole time you were
    away, so he is simply already sitting there rather than walking over.

    Deciding that here, inside the same continuation that sets the flag,
    rather than in an effect watching the table: the state lands before React
    re-renders, so an effect would always see the flag already set and give a
    reloaded game the full walk-on.
  */
  useEffect(() => {
    void gameStore.refresh().then(async () => {
      if (gameStore.get()) await reseatIntoGame()
      gameSeeded.current = true
    })
  }, [])

  /*
    A table that appears later did not come from this page. He dealt himself
    in — `start_kittens`, on his own turn — and that deserves the walk over
    and the camera push, the same as pressing Play.
  */
  useEffect(() => {
    if (!game || tablePhase !== 'idle' || !gameSeeded.current) return
    void phaseStore.arrive()
  }, [game, tablePhase])

  /* The same two questions again, for the board. Kept as their own pair rather
     than folded into the ones above: the two games have separate stores, and a
     single effect asking about both would have to decide what it meant for one
     to answer before the other. */
  useEffect(() => {
    void chessStore.refresh().then(() => {
      if (chessStore.get() && chessPhaseStore.get() === 'idle') chessPhaseStore.adopt()
      chessSeeded.current = true
    })
  }, [])

  useEffect(() => {
    if (!chess || chessPhase !== 'idle' || !chessSeeded.current) return
    void chessPhaseStore.arrive()
  }, [chess, chessPhase])

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
  const voiceOn = modeUsesVoice(mode)
  const voice = useVoiceSession({ enabled: voiceOn, listen: modeListens(mode) })
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
    if (voiceOn) {
      // The ear owns the bubble now; drop any buffered text stream so it
      // cannot resurface as a stale reply the moment chat mode returns.
      setStream((prev) => (prev.phase === 'off' ? prev : IDLE_FACE_STREAM))
      return
    }
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
  }, [voiceOn, stream])

  // Voice / talk: ear-aligned captions only — never paint model-speed chat_delta.
  useEffect(() => {
    if (!voiceOn) return
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
      // Talk mode has no mic — never claim the user is speaking.
      userSpeaking: modeListens(mode) && voice.phase === 'listening',
      rauSpeaking: speaking,
      userLevel: modeListens(mode) ? voice.micLevel : 0,
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
    voiceOn,
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
        if (voiceOn) {
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
  }, [mode, voiceOn])

  // A voice turn settles with say_end, which the hub sends only after both
  // sides of the exchange are in its log — chat_done arrives while TTS is
  // still playing, too early to see them. Same fold-in as Conversation.
  useEffect(() => {
    if (voiceOn && voice.lastTurn) void refresh()
  }, [voiceOn, voice.lastTurn, refresh])

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
        // Voice captions follow the ear; a text stream buffered now would
        // paint a stale reply the moment chat mode returns.
        if (!voiceOn) setStream((prev) => reduceFaceStream(prev, event))
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
    const offStatus = live.onStatus((connectedNow) => {
      // A reply streaming over the dead socket gets no chat_done.
      if (!connectedNow) setStream(IDLE_FACE_STREAM)
    })
    return () => {
      clearInterval(id)
      off()
      offWork()
      offStatus()
    }
    // voiceOn is read by the handler; refresh already tracks it, but list it
    // so the dependency array says what the closure uses.
  }, [refresh, voiceOn])

  const send = useCallback(
    async (text: string) => {
      // At the table this is what makes him glance up from his cards. Stamped
      // whichever way the message goes out, because being spoken to is being
      // spoken to.
      gameBridge.userChattedAt = Date.now()

      // In voice/talk mode the turn belongs to the socket, so typing goes down
      // the same path and comes back as speech.
      if (voiceOn && voice.connected) {
        setStream(IDLE_FACE_STREAM)
        streamStampRef.current = ''
        voice.sendText(text)
        return
      }

      sendingRef.current = true
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
        throw new Error('chat failed')
      } finally {
        sendingRef.current = false
        await refresh()
      }
    },
    [mode, voiceOn, voice, refresh],
  )

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

  const isVoice = voiceOn
  /** The mic is open. Talk mode uses the voice socket but never listens. */
  const listening = modeListens(mode)
  /** A hand is actually on — the exit ritual gives the composer back early. */
  const inGame =
    tablePhase === 'dealing' || tablePhase === 'playing' || chessPhase === 'playing'
  /** Neither table is out, so either one can be offered. There is only one. */
  const roomFree = tablePhase === 'idle' && !game && chessPhase === 'idle' && !chess

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

        The phase is checked as well as the game, so the deck is already in
        place for the deal and stays put through the exit — a table that
        vanished the instant the server forgot about it would cut the last
        second of him standing back up.
      */}
      {(game || tablePhase !== 'idle') && (
        <Suspense fallback={null}>
          <GameTable />
        </Suspense>
      )}

      {/* The board, on the same terms and for the same reasons. */}
      {(chess || chessPhase !== 'idle') && (
        <Suspense fallback={null}>
          <ChessTable />
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
          <span
            className={`mode-pill ${isVoice ? 'on' : ''}`}
            title="Shift+Space to switch — chat, voice, or talk (type in, speak out)"
          >
            <i className="mode-dot" />
            {modeLabel(mode)}
            <em>⇧␣</em>
          </span>
          {/*
            Starting a game without asking him. He can still deal or set up the
            board himself — `start_kittens`, `start_chess` — and these are the
            shortcuts for when you already know which one you want and would
            rather not type a sentence about it.

            Both disappear from the moment either is pressed until the room is
            his again: there is one table, each game carries its own Leave, and
            a second control up here would only be a way to lose a game you
            were in the middle of.
          */}
          {roomFree && (
            <>
              <button
                className="face-toggle face-play"
                onClick={() => {
                  setActivityOpen(false)
                  setPanel(false)
                  setComposerOpen(false)
                  void chessPhaseStore.begin()
                }}
                title="Set the chess board up"
              >
                Chess
              </button>
              <button
                className="face-toggle face-play"
                onClick={() => {
                  setActivityOpen(false)
                  setPanel(false)
                  setComposerOpen(false)
                  void phaseStore.begin()
                }}
                title="Deal a hand of Exploding Kittens"
              >
                Play
              </button>
            </>
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

      {/*
        The HUD is for the mode where you cannot see what the machine is
        doing: the mic is open, and the only way to know whether it heard you
        is to be told. In talk mode you typed the message yourself and his
        reply comes out of his mouth over his own head — a tile restating
        "type below" is a caption on something already in front of you, so it
        is not drawn at all. The one thing talk mode still needs the HUD for
        is a voice that has broken: a reply that never arrives out loud is
        indistinguishable from silence, so an error brings the tile back on
        its own.
      */}
      {(listening || (voiceOn && !!voice.error)) && (
        <div className={`voice-hud ${listening ? '' : 'is-quiet'}`}>
          {listening && (
            <div className={`voice-orb ${voice.phase}`}>
              <i
                className="voice-orb-fill"
                style={{
                  transform: `scale(${1 + (voice.phase === 'speaking' ? voice.outLevel : voice.micLevel) * 1.8})`,
                }}
              />
            </div>
          )}
          <div className="voice-read" role="status" aria-live="polite">
            {listening && (
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
            )}
            {/* Only Deepgram streams partials; the rest stay blank until final. */}
            {listening && (voice.partial || voice.finalText) && (
              <p className={`voice-transcript ${voice.partial ? 'live' : ''}`}>
                {voice.partial || voice.finalText}
              </p>
            )}
            {listening && voice.lastTurn?.interrupted && (
              <p className="voice-note">cut off — he only remembers what you heard</p>
            )}
            {voice.error && <p className="voice-note bad">{voice.error}</p>}
          </div>
          {listening && signals.jobs.length > 0 && (
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

          <h3>At the table</h3>
          <p className="face-hint">
            The ritual runs with or without a game, so the walk, the sit and
            the camera can be watched on their own. The verbs below it only
            read right seated — start with “Sit at table”.
          </p>
          <div className="chip-row">
            <button className="chip" onClick={() => void apiRef.current?.game.begin()}>
              Enter the table
            </button>
            <button className="chip" onClick={() => void apiRef.current?.game.end()}>
              Leave the table
            </button>
          </div>
          <div className="chip-row">
            {TABLE_BUTTONS.map((m) => (
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

      {/*
        The composer, collapsed to a corner while a hand is on.

        Collapsed, not disabled. His moves come back through the same face
        turn as everything else — he narrates them in his own voice and the
        bubble is drawn over his head — so talking to him mid-game is the best
        part of playing him, and shutting the input off during his turn would
        be shutting off the thing worth having. A message sent while he is
        thinking about a move simply waits behind it, which is also what
        happens at a real table. Draft state lives in FaceComposer so typing
        does not re-render the room or the card table.
      */}
      <FaceComposer
        inGame={inGame}
        open={composerOpen}
        onOpenChange={setComposerOpen}
        onSend={send}
      />
    </div>
  )
}
