/**
 * The hub's live event channel, shared by the whole page.
 *
 * `/ws` carries everything that is not audio: presence pings, job state, and
 * the turn-scoped reply stream (`chat_started` / `chat_delta` / `chat_done` /
 * `chat_error`) plus the body plans anchored to it. One socket serves every
 * subscriber — a second one would give two avatars two different views of the
 * same turn.
 *
 * Nothing here is replayed. A plan is only meaningful while the reply it
 * belongs to is still arriving, so a page that reconnects picks up from the
 * next turn rather than acting out an expired one.
 */

import { bodyController, type BodyPlan } from './clawd/body'

export type LiveEvent = { kind: string; [key: string]: unknown }

type EventHandler = (event: LiveEvent) => void
type StatusHandler = (connected: boolean) => void

/** Reconnect backoff: 0.5s, 1s, 2s, 4s, then every 8s. */
const RECONNECT_BASE_MS = 500
const RECONNECT_MAX_MS = 8000

const handlers = new Set<EventHandler>()
const statusHandlers = new Set<StatusHandler>()

let socket: WebSocket | null = null
let retries = 0
let retryTimer: ReturnType<typeof setTimeout> | null = null
let connected = false

function setConnected(next: boolean) {
  if (connected === next) return
  connected = next
  for (const fn of [...statusHandlers]) {
    try {
      fn(next)
    } catch {
      /* one bad subscriber must not take the socket down */
    }
  }
}

/** Route a hub event into the body controller. */
function driveBody(event: LiveEvent) {
  const turnId = typeof event.turn_id === 'string' ? event.turn_id : ''
  switch (event.kind) {
    case 'chat_started':
      bodyController.startTurn(turnId)
      break
    case 'body_plan':
      bodyController.applyPlan({
        turn_id: turnId,
        plan_id: typeof event.plan_id === 'string' ? event.plan_id : '',
        cues: Array.isArray(event.cues) ? (event.cues as BodyPlan['cues']) : [],
        expires_ms: typeof event.expires_ms === 'number' ? event.expires_ms : undefined,
      })
      break
    case 'body_cancel':
      bodyController.cancel(turnId, String(event.reason ?? 'cancelled'))
      break
    case 'chat_delta':
      bodyController.advance(turnId, typeof event.text === 'string' ? event.text : '', 'text')
      break
    case 'chat_done':
      // An interrupted reply has no end to gesture at — the words after the
      // cut were never heard, so neither should the cues anchored to them be.
      if (event.interrupted) bodyController.cancel(turnId, 'interrupted')
      else bodyController.endTurn(turnId, typeof event.text === 'string' ? event.text : undefined)
      break
    case 'chat_error':
      bodyController.cancel(turnId, 'error')
      break
  }
}

function connect() {
  if (socket || typeof window === 'undefined' || typeof WebSocket === 'undefined') return
  let ws: WebSocket
  try {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    ws = new WebSocket(`${proto}://${window.location.host}/ws`)
  } catch {
    schedule()
    return
  }
  socket = ws

  ws.onopen = () => {
    retries = 0
    setConnected(true)
  }
  ws.onclose = () => {
    if (socket !== ws) return
    socket = null
    setConnected(false)
    schedule()
  }
  ws.onerror = () => {
    /* onclose does the recovery; this only silences the unhandled error */
  }
  ws.onmessage = (message: MessageEvent) => {
    if (typeof message.data !== 'string') return
    let event: LiveEvent
    try {
      event = JSON.parse(message.data) as LiveEvent
    } catch {
      return // one malformed frame must not take the handler down
    }
    if (!event || typeof event.kind !== 'string') return
    driveBody(event)
    for (const fn of [...handlers]) {
      try {
        fn(event)
      } catch {
        /* as above */
      }
    }
  }
}

function schedule() {
  if (retryTimer !== null) return
  // The hub restarting is routine; the page should outlive it.
  const delay = Math.min(RECONNECT_MAX_MS, RECONNECT_BASE_MS * 2 ** retries)
  retries += 1
  retryTimer = setTimeout(() => {
    retryTimer = null
    connect()
  }, delay)
}

export const live = {
  /** Open the channel. Idempotent; safe to call from every mount. */
  start(): void {
    connect()
  },
  isConnected(): boolean {
    return connected
  },
  /** Listen to every hub event. Returns an unsubscribe. */
  subscribe(fn: EventHandler): () => void {
    handlers.add(fn)
    connect()
    return () => {
      handlers.delete(fn)
    }
  },
  /** Listen to connection state, called immediately with the current one. */
  onStatus(fn: StatusHandler): () => void {
    statusHandlers.add(fn)
    fn(connected)
    connect()
    return () => {
      statusHandlers.delete(fn)
    }
  },
}
