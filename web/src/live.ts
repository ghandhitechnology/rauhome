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
type WorkingHandler = (working: boolean) => void

/** Reconnect backoff: 0.5s, 1s, 2s, 4s, then every 8s. */
const RECONNECT_BASE_MS = 500
const RECONNECT_MAX_MS = 8000

const handlers = new Set<EventHandler>()
const statusHandlers = new Set<StatusHandler>()
const workingHandlers = new Set<WorkingHandler>()

let socket: WebSocket | null = null
let retries = 0
let retryTimer: ReturnType<typeof setTimeout> | null = null
let connected = false
let activityTimer: ReturnType<typeof setTimeout> | null = null
/** Nested desk-work depth so overlapping tools keep him at the computer. */
let deskWorkDepth = 0
let working = false

function setDeskWork(delta: number) {
  deskWorkDepth = Math.max(0, deskWorkDepth + delta)
  const next = deskWorkDepth > 0
  if (next === working) return
  working = next
  for (const fn of [...workingHandlers]) {
    try {
      fn(working)
    } catch {
      /* one bad subscriber must not stall the rest */
    }
  }
}

function resetDeskWork() {
  deskWorkDepth = 0
  if (!working) return
  working = false
  for (const fn of [...workingHandlers]) {
    try {
      fn(false)
    } catch {
      /* as above */
    }
  }
}

function deskSustain(event: LiveEvent, fallbackMotion: 'search' | 'type') {
  const watchdog = typeof event.watchdog_ms === 'number' ? event.watchdog_ms : 90_000
  const motion =
    event.motion === 'search' || event.motion === 'type' || event.motion === 'read'
      ? (event.motion as 'search' | 'type' | 'read')
      : fallbackMotion
  setDeskWork(1)
  bodyController.sustain(
    {
      anchor: 'now',
      station: 'desk',
      motion,
      gaze: 'screen',
      hold_ms: 1000,
      hurry: true,
    },
    watchdog,
  )
}

function deskRelease() {
  setDeskWork(-1)
  if (deskWorkDepth === 0) bodyController.endSustain()
}

function markActive(durationMs = 2500) {
  if (typeof document === 'undefined') return
  document.documentElement.dataset.rauActive = 'true'
  if (activityTimer) clearTimeout(activityTimer)
  activityTimer = setTimeout(() => {
    delete document.documentElement.dataset.rauActive
    activityTimer = null
  }, durationMs)
}

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
  if (
    event.kind.startsWith('chat_') ||
    event.kind.startsWith('job_') ||
    event.kind.startsWith('hard_task') ||
    event.kind.startsWith('computer_')
  ) {
    markActive()
  }
  if (event.kind === 'resource_profile' && event.profile && typeof event.profile === 'object') {
    const name = String((event.profile as Record<string, unknown>).name || 'balanced')
    document.documentElement.dataset.resourceProfile = name
  }
  const turnId = typeof event.turn_id === 'string' ? event.turn_id : ''
  switch (event.kind) {
    case 'chat_started':
      resetDeskWork()
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
      resetDeskWork()
      if (event.interrupted) bodyController.cancel(turnId, 'interrupted')
      else bodyController.endTurn(turnId, typeof event.text === 'string' ? event.text : undefined)
      break
    case 'chat_error':
      resetDeskWork()
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
    case 'browse_started':
      // Research: dash to the desk and search for as long as the fetch takes.
      deskSustain(event, 'search')
      break
    case 'tool_started':
      // Generic face tools (shell, files, memory, hard task, …).
      deskSustain(event, 'type')
      break
    case 'browse_finished':
    case 'tool_finished':
      deskRelease()
      break
    case 'panel_shown':
      panelStore.add({
        panel_id: String(event.panel_id ?? ''),
        title: String(event.title ?? 'Untitled'),
        kind: String(event.panel_kind ?? 'report'),
        created: Number(event.created ?? Date.now() / 1000),
        revision: Number(event.revision ?? 1),
      })
      break
    case 'panel_updated':
      panelStore.update({
        panel_id: String(event.panel_id ?? ''),
        title: String(event.title ?? 'Untitled'),
        kind: String(event.panel_kind ?? 'report'),
        revision: Number(event.revision ?? 1),
      })
      break
    case 'panel_closed':
      panelStore.remove(String(event.panel_id ?? ''))
      break
    case 'panel_presented':
      // Recorded, not opened — only the room acts on it. See panels.ts.
      panelStore.present(String(event.panel_id ?? ''))
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
  /** True while a face tool or browse is holding him at the computer. */
  isWorking(): boolean {
    return working
  },
  /** Listen to every hub event. Returns an unsubscribe. */
  subscribe(fn: EventHandler): () => void {
    handlers.add(fn)
    connect()
    return () => {
      handlers.delete(fn)
    }
  },
  /** Desk-work flag for the thinking bubble vs computer pose. */
  subscribeWorking(fn: WorkingHandler): () => void {
    workingHandlers.add(fn)
    fn(working)
    connect()
    return () => {
      workingHandlers.delete(fn)
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
