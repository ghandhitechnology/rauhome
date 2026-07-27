import { useCallback, useEffect, useRef, useState } from 'react'

import { bodyController } from '../clawd/body'
import { spokenSentence, spokenSoFar, type AlignedSentence } from './alignment'
import { classifyEndpoint, ENDPOINT_SCALE } from './endpoint'
import { FRAME_MS, MicCapture } from './capture'
import { TtsPlayback } from './playback'
import { Vad } from './vad'

export type VoicePhase = 'idle' | 'listening' | 'thinking' | 'speaking'

export type VoiceSession = {
  phase: VoicePhase
  connected: boolean
  /** Interim transcript; only backends that stream partials fill this. */
  partial: string
  /** The last settled transcript of what the user said. */
  finalText: string
  /** Latest sentence queued for TTS (synth-time; may lead the ear). */
  lastSay: string
  /** Cumulative text actually heard so far this reply. */
  spokenText: string
  /** Sentence currently reaching the speaker. */
  spokenSentence: string
  micLevel: number
  outLevel: number
  error: string
  /** How the previous reply ended — notably whether it was cut off. */
  lastTurn: VoiceTurnEnd | null
  /** Tools invoked this session, newest last, capped to a recent window. */
  tools: VoiceToolCall[]
  /** STT backend the session resolved to, which may differ from the config. */
  backend: string
  sendText: (text: string) => void
  /** Shut Rau up / abandon the utterance in progress. */
  stop: () => void
}

/**
 * Mic frames kept before speech is confirmed. The VAD needs 120ms to be sure
 * and up to 260ms to justify an interrupt; replaying this ring means the STT
 * backend still hears the word from its first consonant.
 */
const PREROLL_FRAMES = 16

/** Levels arrive ~70 times a second. Rendering that often is pointless. */
const LEVEL_INTERVAL_MS = 60
const LEVEL_EPSILON = 0.004

/** Long enough for a permission prompt, short enough to not feel hung. */
const AUDIO_START_TIMEOUT_MS = 12000

/** Reconnect backoff: 0.5s, 1s, 2s, 4s, then every 8s. */
const RECONNECT_BASE_MS = 500
const RECONNECT_MAX_MS = 8000

type ServerMessage = {
  t: string
  phase?: VoicePhase
  text?: string
  detail?: string
  /** say_end: whether the user cut this reply off, and what they heard. */
  interrupted?: boolean
  heard?: string
  /** say: the reply could not be synthesised, so it is text-only. */
  silent?: boolean
  /** tool: a face tool fired mid-turn — how background jobs surface. */
  name?: string
  args?: Record<string, unknown>
  ok?: boolean
  /** hello: which STT backend the session actually resolved to. */
  stt?: string
  model?: string
  /** say_align / say / say_end: which reply this frame belongs to. */
  turn_id?: string
  /** say_align: where this sentence starts in the reply's audio timeline. */
  offset_ms?: number
  duration_ms?: number
  /** say_align: when each character of `text` starts, within the sentence. */
  char_ms?: number[]
}

/** A tool the model invoked during the current session. */
export type VoiceToolCall = { name: string; args: Record<string, unknown>; ok: boolean }

/** How the last reply ended. `heard` is populated only when interrupted. */
export type VoiceTurnEnd = { interrupted: boolean; heard: string; at: number }

export const useVoiceSession = ({
  enabled,
  listen = true,
}: {
  enabled: boolean
  /** When false, keep the voice socket and TTS but do not open the mic. */
  listen?: boolean
}): VoiceSession => {
  const [phase, setPhase] = useState<VoicePhase>('idle')
  const [connected, setConnected] = useState(false)
  const [partial, setPartial] = useState('')
  const [finalText, setFinalText] = useState('')
  const [lastSay, setLastSay] = useState('')
  const [spokenText, setSpokenText] = useState('')
  const [spokenSentenceState, setSpokenSentenceState] = useState('')
  const [error, setError] = useState('')
  const [levels, setLevels] = useState({ mic: 0, out: 0 })
  const [lastTurn, setLastTurn] = useState<VoiceTurnEnd | null>(null)
  const [tools, setTools] = useState<VoiceToolCall[]>([])
  const [backend, setBackend] = useState('')

  const wsRef = useRef<WebSocket | null>(null)
  const playbackRef = useRef<TtsPlayback | null>(null)
  const vadRef = useRef<Vad | null>(null)
  const phaseRef = useRef<VoicePhase>('idle')
  const streamingRef = useRef(false)
  const bargingRef = useRef(false)
  const mutedRef = useRef(false)
  const micRef = useRef(0)
  const outRef = useRef(0)

  const applyPhase = useCallback((next: VoicePhase) => {
    phaseRef.current = next
    setPhase(next)
  }, [])

  useEffect(() => {
    if (!enabled) return

    const vad = new Vad()
    const capture = new MicCapture()
    const playback = new TtsPlayback()
    vadRef.current = vad
    playbackRef.current = playback

    const held: ArrayBuffer[] = []
    let ws: WebSocket | null = null
    let disposed = false
    let retries = 0
    let retryTimer: number | null = null

    const send = (payload: Record<string, unknown>) => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload))
    }

    const drain = () => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return
      for (const frame of held) ws.send(frame)
      held.length = 0
    }

    const bargeIn = async () => {
      // Locally first, always: waiting for the server to acknowledge before
      // going quiet is the difference between interrupting someone and
      // talking over them.
      mutedRef.current = true
      const socket = ws
      const playedMs = await playback.flush()
      // The session can be torn down mid-flush, and the refs below outlive it:
      // a stale `streaming` would make the next session send mic frames the
      // server drops for want of a speech_start. The same is true of a socket
      // that died mid-flush: onclose has already reset this state, and
      // reviving it here would silently lose the next utterance.
      if (disposed || ws !== socket || !socket || socket.readyState !== WebSocket.OPEN) return
      send({ t: 'barge', playedMs })
      // Only now: the server drops a barge once speech_start has moved the
      // session out of the speaking phase.
      send({ t: 'speech_start' })
      streamingRef.current = true
      bargingRef.current = false
      drain()
    }

    capture.onFrame((pcm, level) => {
      micRef.current = level
      if (!ws || ws.readyState !== WebSocket.OPEN) return

      const event = vad.push(level, FRAME_MS)
      held.push(pcm)
      if (!bargingRef.current) {
        while (held.length > PREROLL_FRAMES) held.shift()
      }

      // While Rau talks, the utterance is held back rather than streamed: a
      // cough must not open an STT stream, and a real interruption has to be
      // announced before its audio.
      if (phaseRef.current === 'speaking' && !streamingRef.current) {
        if (!bargingRef.current && vad.shouldBarge()) {
          bargingRef.current = true
          void bargeIn()
        }
        return
      }

      if (!streamingRef.current && vad.speaking) {
        send({ t: 'speech_start' })
        streamingRef.current = true
      }
      if (streamingRef.current) drain()
      if (event === 'end') {
        send({ t: 'speech_end' })
        streamingRef.current = false
        held.length = 0
      }
    })

    /** Sentences of the reply currently being spoken, in timeline order. */
    let aligned: AlignedSentence[] = []
    let reported = ''
    let reportedSentence = ''

    const clearHeard = () => {
      aligned = []
      reported = ''
      reportedSentence = ''
      setSpokenText('')
      setSpokenSentenceState('')
    }

    playback.onLevel((level, playedMs, idle) => {
      outRef.current = idle ? 0 : level
      if (!aligned.length) return
      const spoken = spokenSoFar(aligned, playedMs)
      const sentence = spokenSentence(aligned, playedMs)
      if (sentence !== reportedSentence) {
        reportedSentence = sentence
        setSpokenSentenceState(sentence)
      }
      if (spoken === reported) return
      reported = spoken
      setSpokenText(spoken)
      // 'audio' takes the turn away from the text stream for good: the two
      // describe the same reply, but only one of them is in step with the ear.
      bodyController.advance(aligned[0].turnId, spoken, 'audio')
    })

    // Audio hardware can fail asynchronously — a device the OS hands over but
    // never starts leaves `start()` pending rather than rejecting. Without a
    // deadline the UI sits on "connecting…" forever with nothing to act on.
    const watchdog = window.setTimeout(() => {
      if (!disposed && !wsRef.current) {
        setError(
          listen
            ? 'could not start audio — check microphone access and output device'
            : 'could not start audio — check the output device',
        )
      }
    }, AUDIO_START_TIMEOUT_MS)

    const open = async () => {
      try {
        await playback.start()
        // Talk mode (listen=false) only needs speakers — skip the mic so we
        // never ask for permission or stream silence into STT.
        if (listen) await capture.start()
      } catch (e) {
        if (!disposed) setError(e instanceof Error ? e.message : String(e))
        return
      }
      if (disposed) return
      window.clearTimeout(watchdog)
      connect()
    }

    const connect = () => {
      if (disposed) return
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const socket = new WebSocket(`${proto}://${window.location.host}/ws/voice`)
      socket.binaryType = 'arraybuffer'
      ws = socket
      wsRef.current = socket

      socket.onopen = () => {
        retries = 0
        setConnected(true)
        setError('')
      }
      socket.onerror = () => {
        if (!disposed) setError('voice connection failed')
      }
      socket.onclose = () => {
        if (ws !== socket) return
        ws = null
        wsRef.current = null
        setConnected(false)
        // Everything below describes the connection that just died; carrying
        // it into the next one would mute its audio or drop its first words.
        streamingRef.current = false
        bargingRef.current = false
        mutedRef.current = false
        held.length = 0
        vad.reset()
        playback.reset()
        // A reconnect starts a new timeline; a plan for the dead one is over.
        clearHeard()
        bodyController.cancel(undefined, 'disconnected')
        setPartial('')
        setLastSay('')
        applyPhase('idle')
        if (disposed) return
        // The hub restarting is routine; the session should outlive it.
        const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** retries)
        retries += 1
        retryTimer = window.setTimeout(connect, delay)
      }
      socket.onmessage = (ev: MessageEvent) => {
        if (typeof ev.data !== 'string') {
          // Audio from a turn we already interrupted is still in flight for a
          // few milliseconds after the barge; playing it would undo the cut.
          if (!mutedRef.current) playback.push(ev.data as ArrayBuffer)
          return
        }
        let msg: ServerMessage
        try {
          msg = JSON.parse(ev.data) as ServerMessage
        } catch {
          return // one malformed frame must not take the handler down
        }
        switch (msg.t) {
          case 'phase': {
            const next = msg.phase ?? 'idle'
            // The server measures barge offsets from the start of each reply,
            // so the played-time counter restarts with the turn.
            if (next === 'thinking') {
              playback.reset()
              // Timings describe one reply's audio timeline; carrying them
              // into the next one would place every phrase in the wrong place.
              clearHeard()
              setLastSay('')
            }
            if (next === 'thinking' || next === 'idle') mutedRef.current = false
            applyPhase(next)
            break
          }
          case 'say_align': {
            const turnId = msg.turn_id ?? ''
            const text = msg.text ?? ''
            if (!turnId || !text) break
            if (aligned.length && aligned[0].turnId !== turnId) {
              clearHeard()
            }
            const charMs = Array.isArray(msg.char_ms) ? msg.char_ms : []
            aligned.push({
              turnId,
              text,
              offsetMs: typeof msg.offset_ms === 'number' ? msg.offset_ms : 0,
              durationMs: typeof msg.duration_ms === 'number' ? msg.duration_ms : 0,
              charMs,
            })
            aligned.sort((a, b) => a.offsetMs - b.offsetMs)
            break
          }
          case 'partial': {
            const text = msg.text ?? ''
            setPartial(text)
            // The partial lands a beat before the silence runs out, which is
            // the only window in which the endpointer can still act on it.
            vad.setHangoverScale(ENDPOINT_SCALE[classifyEndpoint(text)])
            break
          }
          case 'final':
            setPartial('')
            setFinalText(msg.text ?? '')
            // The next utterance is a different sentence with different
            // timing; carrying this one's patience into it would either cut
            // it off early or leave a long silence after a plain question.
            vad.setHangoverScale(1)
            break
          case 'say':
            setLastSay(msg.text ?? '')
            break
          case 'say_end':
            // A cut-off reply reports only what actually reached the speaker,
            // which is also all the model is allowed to remember saying.
            setLastTurn({
              interrupted: !!msg.interrupted,
              heard: msg.heard ?? '',
              at: Date.now(),
            })
            break
          case 'tool':
            setTools((prev) => [
              ...prev.slice(-7),
              { name: msg.name ?? '', args: msg.args ?? {}, ok: msg.ok !== false },
            ])
            break
          case 'cancelled':
            // The server confirms the barge; audio was already flushed locally.
            setLastSay('')
            clearHeard()
            break
          case 'hello':
            setBackend(msg.stt ?? '')
            break
          case 'error':
            setError(msg.detail ?? 'voice error')
            break
        }
      }
    }
    void open()

    return () => {
      disposed = true
      window.clearTimeout(watchdog)
      if (retryTimer != null) window.clearTimeout(retryTimer)
      capture.onFrame(null)
      playback.onLevel(null)

      const socket = ws
      ws = null
      wsRef.current = null
      if (socket) {
        socket.onmessage = null
        socket.onclose = null
        socket.onerror = null
        socket.close()
      }

      void capture.stop()
      void playback.close()
      playbackRef.current = null
      vadRef.current = null
      streamingRef.current = false
      bargingRef.current = false
      mutedRef.current = false
      micRef.current = 0
      outRef.current = 0
      setConnected(false)
      setPartial('')
      setLastSay('')
      setSpokenText('')
      setSpokenSentenceState('')
      // Both describe the connection that just went away, not the next one.
      setTools([])
      setBackend('')
      applyPhase('idle')
    }
  }, [enabled, listen, applyPhase])

  useEffect(() => {
    if (!enabled) return
    const id = window.setInterval(() => {
      setLevels((prev) =>
        Math.abs(prev.mic - micRef.current) < LEVEL_EPSILON &&
        Math.abs(prev.out - outRef.current) < LEVEL_EPSILON
          ? prev
          : { mic: micRef.current, out: outRef.current },
      )
    }, LEVEL_INTERVAL_MS)
    return () => {
      window.clearInterval(id)
      setLevels({ mic: 0, out: 0 })
    }
  }, [enabled])

  const sendText = useCallback((text: string) => {
    const value = text.trim()
    const socket = wsRef.current
    if (!value || !socket || socket.readyState !== WebSocket.OPEN) return
    socket.send(JSON.stringify({ t: 'text', text: value }))
    // Typed input is never transcribed, so nothing else will report it.
    setPartial('')
    setFinalText(value)
  }, [])

  const stop = useCallback(() => {
    const socket = wsRef.current
    const playback = playbackRef.current
    // Silence him locally regardless of the socket — audio already queued in
    // the worklet keeps playing even while the connection is down.
    if (phaseRef.current === 'speaking' && playback) {
      mutedRef.current = true
      void playback.flush().then((playedMs) => {
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ t: 'barge', playedMs }))
        }
      })
      return
    }
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ t: 'stop' }))
    }
    streamingRef.current = false
    vadRef.current?.reset()
    applyPhase('idle')
  }, [applyPhase])

  return {
    phase,
    connected,
    partial,
    finalText,
    lastSay,
    spokenText,
    spokenSentence: spokenSentenceState,
    micLevel: levels.mic,
    outLevel: levels.out,
    error,
    lastTurn,
    tools,
    backend,
    sendText,
    stop,
  }
}
