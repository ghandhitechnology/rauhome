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

import { bodyController, type BodyCue, type BodyPlan } from './clawd/body'
import { PROP_SPOTS, propStore, type PropId, type SpotId } from './clawd/props'
import { panelStore } from './panels'

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

/**
 * Expand one `prop_move` into the performance of moving something.
 *
 * Walk to it, take its weight, carry it across, set it down. The object's
 * visual state follows these steps rather than jumping to the answer, which is
 * the whole difference between a room he lives in and a database of positions.
 */
function errandPlan(errandId: string, from: SpotId, to: SpotId): BodyCue[] {
  const origin = PROP_SPOTS[from]
  const target = PROP_SPOTS[to]
  const step = (cue: Omit<BodyCue, 'anchor'>): BodyCue => ({ anchor: 'now', ...cue })
  return [
    step({ station: origin.station, gaze: 'floor', hold_ms: 400, errand: { id: errandId, phase: 'travel' } }),
    step({ motion: 'lift', hold_ms: 1100, errand: { id: errandId, phase: 'lift' } }),
    step({
      motion: 'carry',
      station: target.station,
      hold_ms: 500,
      errand: { id: errandId, phase: 'carry' },
    }),
    step({ motion: 'place', gaze: 'floor', hold_ms: 1150, errand: { id: errandId, phase: 'place' } }),
  ]
}

// One sequencer owns the object's state: every mounted avatar performs the
// same cue, but the errand advances once.
bodyController.onCueChange((cue) => {
  const errand = cue?.errand
  if (errand) propStore.advance(errand.id, errand.phase)
  else if (propStore.activeErrand?.phase === 'place') {
    propStore.advance(propStore.activeErrand.id, 'done')
  }
})

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
    case 'prop_layout':
      propStore.setLayout((event.layout ?? {}) as Partial<Record<PropId, SpotId>>)
      break
    case 'prop_move': {
      const prop = String(event.object ?? '') as PropId
      const from = String(event.from ?? '') as SpotId
      const to = String(event.to ?? '') as SpotId
      const errandId = String(event.errand_id ?? '')
      if (!errandId || !(from in PROP_SPOTS) || !(to in PROP_SPOTS)) break
      propStore.begin({ id: errandId, prop, from, to })
      bodyController.applyPlan({
        turn_id: turnId || errandId,
        plan_id: errandId,
        cues: errandPlan(errandId, from, to),
      })
      break
    }
    case 'browse_started': {
      // Send him to the computer for as long as the fetch actually takes.
      const watchdog = typeof event.watchdog_ms === 'number' ? event.watchdog_ms : 90_000
      bodyController.sustain(
        {
          anchor: 'now',
          station: 'desk',
          motion: 'search',
          gaze: 'screen',
          hold_ms: 1000,
        },
        watchdog,
      )
      break
    }
    case 'browse_finished':
      bodyController.endSustain()
      break
    case 'panel_shown':
      panelStore.add({
        panel_id: String(event.panel_id ?? ''),
        title: String(event.title ?? 'Untitled'),
        kind: String(event.panel_kind ?? 'report'),
        created: Number(event.created ?? Date.now() / 1000),
      })
      break
    case 'panel_cleared':
      panelStore.clear()
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
