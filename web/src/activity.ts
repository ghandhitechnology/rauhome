import { useSyncExternalStore } from 'react'
import { api, type ActivitySpan } from './api'
import { live, type LiveEvent } from './live'

const VISIBILITY_KEY = 'rau.activity.visible'
const spans = new Map<string, ActivitySpan>()
const listeners = new Set<() => void>()
let snapshot: ActivitySpan[] = []
let visible = true
let initialized = false

function publish() {
  snapshot = [...spans.values()].sort((a, b) => a.seq - b.seq)
  for (const listener of [...listeners]) listener()
}

/**
 * Spans accumulate for the life of the page, and this page lives for days.
 * Turn and job inspectors re-fetch their own spans on demand, so the oldest
 * can fall off the back without losing anything but memory.
 */
const MAX_KEPT_SPANS = 2000

/** Drop the oldest spans by seq until at most `max` remain. */
export function trimActivitySpans(
  store: Map<string, ActivitySpan>,
  max = MAX_KEPT_SPANS,
): boolean {
  if (store.size <= max) return false
  const excess = store.size - max
  const oldest = [...store.values()].sort((a, b) => a.seq - b.seq)
  for (const span of oldest.slice(0, excess)) store.delete(span.id)
  return true
}

function merge(items: ActivitySpan[]) {
  let changed = false
  for (const item of items) {
    const prior = spans.get(item.id)
    if (!prior || item.revision >= prior.revision) {
      spans.set(item.id, item)
      changed = true
    }
  }
  if (trimActivitySpans(spans)) changed = true
  if (changed) publish()
}

export function activityFromEvent(event: LiveEvent): ActivitySpan | null {
  if (
    event.kind !== 'activity_started' &&
    event.kind !== 'activity_delta' &&
    event.kind !== 'activity_finished'
  ) {
    return null
  }
  if (typeof event.id !== 'string' || typeof event.seq !== 'number') return null
  return {
    id: event.id,
    seq: event.seq,
    revision: Number(event.revision || 1),
    kind: String(event.activity_kind || 'execution') as ActivitySpan['kind'],
    source: String(event.source || 'rau'),
    status: String(event.status || 'running'),
    label: String(event.label || 'Working'),
    summary: String(event.summary || ''),
    details:
      event.details && typeof event.details === 'object'
        ? (event.details as Record<string, unknown>)
        : {},
    turn_id: typeof event.turn_id === 'string' ? event.turn_id : null,
    job_id: typeof event.job_id === 'string' ? event.job_id : null,
    step_id: typeof event.step_id === 'string' ? event.step_id : null,
    parent_span_id:
      typeof event.parent_span_id === 'string' ? event.parent_span_id : null,
    started: Number(event.started || event.ts || Date.now() / 1000),
    updated: Number(event.updated || event.ts || Date.now() / 1000),
    ended: typeof event.ended === 'number' ? event.ended : null,
  }
}

async function hydrate() {
  try {
    const [recent, active] = await Promise.all([
      api.activity({ limit: 500 }),
      api.activeActivity(),
    ])
    merge([...(recent.activity || []), ...(active.activity || [])])
  } catch {
    // The WebSocket can still populate live activity while the hub recovers.
  }
}

function init() {
  if (initialized || typeof window === 'undefined') return
  initialized = true
  visible = window.localStorage.getItem(VISIBILITY_KEY) !== 'false'
  live.subscribe((event) => {
    const item = activityFromEvent(event)
    if (item) merge([item])
  })
  live.onStatus((connected) => {
    if (connected) void hydrate()
  })
  window.addEventListener('storage', (event) => {
    if (event.key !== VISIBILITY_KEY) return
    visible = event.newValue !== 'false'
    publish()
  })
}

export function activityFor(
  items: ActivitySpan[],
  filter: {
    turnId?: string
    jobId?: string
    global?: boolean
    agent?: ActivityAgent
  },
) {
  return items.filter((span) => {
    const correlated = filter.turnId
      ? span.turn_id === filter.turnId
      : filter.jobId
        ? span.job_id === filter.jobId
        : !!filter.global
    if (!correlated) return false
    if (filter.agent === 'main') return !span.job_id
    if (filter.agent === 'deep-work') return !!span.job_id
    return true
  })
}

export type ActivityAgent = 'main' | 'deep-work'

export const activityStore = {
  subscribe(listener: () => void) {
    init()
    listeners.add(listener)
    return () => listeners.delete(listener)
  },
  snapshot() {
    init()
    return snapshot
  },
  visible() {
    init()
    return visible
  },
  setVisible(next: boolean) {
    visible = next
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(VISIBILITY_KEY, String(next))
    }
    publish()
  },
  async ensureTurn(turnId: string) {
    if (!turnId) return
    try {
      const result = await api.activity({ turnId, limit: 500 })
      merge(result.activity || [])
    } catch {
      // Live delivery may still have the same spans.
    }
  },
  async ensureJob(jobId: string) {
    if (!jobId) return
    try {
      const result = await api.activity({ jobId, limit: 500 })
      merge(result.activity || [])
    } catch {
      // As above.
    }
  },
}

export function useActivity() {
  const all = useSyncExternalStore(
    activityStore.subscribe,
    activityStore.snapshot,
    activityStore.snapshot,
  )
  return { all, visible: activityStore.visible() }
}
