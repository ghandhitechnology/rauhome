import type { PanelSummary } from './panels'

const BASE = ''

export type AuthProvider = {
  id: string
  label: string
  env: string
  docs_url?: string
  connect_url?: string
  help?: string
  configured: boolean
  masked?: string
}

export type VerifyResult = {
  ok: boolean
  provider?: string
  detail?: string
  models?: string[]
  soft?: boolean
}

export type CatalogModel = { id: string; label: string; note?: string }

export type VoiceSettings = {
  stability: number
  similarity_boost: number
  style: number
  speed: number
  use_speaker_boost: boolean
}

export type VoicePreset = {
  id: string
  label: string
  note: string
  voice_id: string
  voice_name: string
  effect: 'none' | 'robot' | 'childlike'
  settings: VoiceSettings
}

export type ElevenVoice = {
  id: string
  label: string
  category: string
  description: string
  labels: Record<string, string>
  preview_url?: string
}

/** One background job. `hard_task` in /api/status is a view of the newest. */
export type Job = {
  id: string
  goal: string
  state: 'queued' | 'planning' | 'running' | 'verifying' | 'awaiting_confirm' | 'done' | 'completed' | 'failed' | 'cancelled' | 'interrupted'
  progress: string
  result: string
  created: number
  updated: number
  executor?: 'python' | 'pi'
  plan?: { steps?: AgentStep[] }
  budget?: Record<string, number>
  parent_id?: string | null
  lifecycle_state?: string
  origin_turn_id?: string | null
  plan_revision?: number
}

export type AgentStep = {
  id: string
  ordinal: number
  title: string
  goal?: string
  state: string
  executor: string
  effect_class?: string
  capabilities?: string[]
  dependencies: string[]
  expected_output?: Record<string, unknown>
  expected_evidence?: string[]
  evidence: Array<Record<string, unknown>>
  attempt: number
  retry_budget?: number
  strategy: string
  result: Record<string, unknown>
  terminal_reason?: string
  plan_revision?: number
}

export type ActivitySpan = {
  id: string
  seq: number
  revision: number
  kind: 'reasoning' | 'planning' | 'tool' | 'approval' | 'execution' | 'verification' | 'retry' | 'completion'
  source: string
  status: string
  label: string
  summary: string
  details: Record<string, unknown>
  turn_id?: string | null
  job_id?: string | null
  step_id?: string | null
  parent_span_id?: string | null
  started: number
  updated: number
  ended?: number | null
}

export type Schedule = {
  id: string
  name: string
  enabled: boolean | number
  goal: string
  trigger_kind: 'once' | 'interval' | 'cron'
  trigger: Record<string, unknown>
  timezone: string
  resource_profile: 'eco' | 'balanced' | 'performance'
  permission_policy: 'readonly' | 'approval'
  next_run_at?: number | null
  revision: number
}

export type ScheduleRun = {
  id: string
  schedule_id: string
  state: string
  nominal_at: number
  enqueued_at: number
  coalesced_count: number
  attempt: number
  job_id?: string | null
  outcome: Record<string, unknown>
}

export type BrowseProviderMeta = {
  label: string
  blurb: string
  auth: string
  /** False for backends that can open a url but not search the web. */
  can_search: boolean
}

export type BrowseStatus = {
  provider: string
  configured: string
  reason: string
  can_search: boolean
  available: Record<string, boolean>
  ready: boolean
}

export type SttProviderMeta = {
  label: string
  blurb: string
  auth: string
  /** True only for backends that stream interim results worth showing live. */
  partials: boolean
  models: CatalogModel[]
}

export type Catalog = {
  providers: Record<string, { label: string; blurb: string; models: CatalogModel[] }>
  provider_auth: Record<string, string>
  slots: { id: string; label: string; blurb: string; prefers: string }[]
  voices: { id: string; label: string; note?: string }[]
  voice_presets: VoicePreset[]
  voice_effects: CatalogModel[]
  tts_models: { id: string; label: string; note?: string }[]
  stt_providers: Record<string, SttProviderMeta>
  browse_providers: Record<string, BrowseProviderMeta>
}

export type VoiceStatus = {
  stt: {
    provider: string
    configured_provider: string
    model: string
    language: string
    /** The configured backend was unusable and we degraded to local whisper. */
    fallback: boolean
    partials: boolean
    label: string
    reason: string
  }
  available: Record<string, boolean>
  tts_ready: boolean
  tts: { voice_id: string; preset: string; effect: string }
}

export type SetupState = {
  identity_ready: boolean
  brains_ready: boolean
  models_ready: boolean
  voice_ready: boolean
  apps_ready: boolean
  complete: boolean
  configured: string[]
  providers: AuthProvider[]
  models: Record<string, any>
  identity: {
    has_identity: boolean
    has_backstory: boolean
    has_soul: boolean
    identity_text: string
    backstory_text: string
  }
  examples: { identity?: string; backstory?: string }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || res.statusText)
  }
  return res.json()
}

async function blobReq(path: string, init?: RequestInit): Promise<Blob> {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    let detail = await res.text()
    try {
      const parsed = JSON.parse(detail)
      detail = parsed.error || parsed.detail || detail
    } catch {
      // Plain-text provider errors are already useful.
    }
    throw new Error(detail || res.statusText)
  }
  return res.blob()
}

export type PermissionMode = 'auto' | 'bypass' | 'readonly'

export type Permissions = {
  subagents: PermissionMode
  room: PermissionMode
  heartbeats: PermissionMode
}

export const api = {
  status: () => req<any>('/api/status'),
  getPet: () =>
    req<{ visible: boolean; face_open: boolean; user_hidden: boolean }>('/api/pet'),
  setPetVisibility: (body: {
    face_open?: boolean
    user_hidden?: boolean
    visible?: boolean
  }) =>
    req<{ ok: boolean; visible: boolean; face_open: boolean; user_hidden: boolean }>(
      '/api/pet/visibility',
      { method: 'POST', body: JSON.stringify(body) },
    ),
  getPermissions: () =>
    req<{ permissions: Permissions; mode: PermissionMode }>('/api/permissions'),
  setPermissions: (body: Partial<Permissions> & { mode?: PermissionMode }) =>
    req<{ ok: boolean; permissions: Permissions; mode: PermissionMode }>(
      '/api/permissions',
      {
        method: 'PUT',
        body: JSON.stringify(body),
      },
    ),
  identity: () => req<any>('/api/identity'),
  fresh: () => req<any>('/api/identity/fresh', { method: 'POST', body: '{}' }),
  hard: (identity: string, backstory: string) =>
    req<any>('/api/identity/hard', {
      method: 'POST',
      body: JSON.stringify({ identity, backstory }),
    }),
  steer: (identity: string, backstory: string) =>
    req<any>('/api/identity/steer', {
      method: 'POST',
      body: JSON.stringify({ identity, backstory }),
    }),
  setupState: () => req<SetupState>('/api/setup/state'),
  catalog: () => req<Catalog>('/api/models/catalog'),
  voiceStatus: () => req<VoiceStatus>('/api/voice/status'),
  browseStatus: () => req<BrowseStatus>('/api/browse/status'),
  elevenVoices: () => req<{ ok: boolean; voices: ElevenVoice[] }>('/api/voice/voices'),
  previewVoice: (body: {
    text?: string
    voice_id: string
    model: string
    effect: string
    voice_settings: VoiceSettings
  }) =>
    blobReq('/api/voice/preview', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  verifyAuth: (providerId: string, key?: string) =>
    req<VerifyResult>(`/api/auth/${providerId}/verify`, {
      method: 'POST',
      body: JSON.stringify({ key: key || null }),
    }),
  models: () => req<any>('/api/models'),
  putModels: (body: any) =>
    req<any>('/api/models', { method: 'PUT', body: JSON.stringify(body) }),
  effort: () => req<any>('/api/effort'),
  putEffort: (body: { face?: string; subagent?: string; dream?: string; all?: string }) =>
    req<any>('/api/effort', { method: 'PUT', body: JSON.stringify(body) }),
  skills: () => req<{ skills: any[] }>('/api/skills'),
  goal: () => req<{ goal: any }>('/api/goal'),
  setGoal: (text: string) =>
    req<any>('/api/goal', { method: 'PUT', body: JSON.stringify({ text }) }),
  clearGoal: () => req<any>('/api/goal', { method: 'DELETE' }),
  providers: () => req<any>('/api/providers/status'),
  auth: () => req<{ providers: any[] }>('/api/auth'),
  setAuth: (providerId: string, key: string) =>
    req<any>(`/api/auth/${providerId}`, {
      method: 'PUT',
      body: JSON.stringify({ key }),
    }),
  clearAuth: (providerId: string) =>
    req<any>(`/api/auth/${providerId}`, { method: 'DELETE' }),
  composioConnect: () =>
    req<any>('/api/auth/composio/connect', { method: 'POST', body: '{}' }),
  log: () => req<{ log: any[] }>('/api/log'),
  emotion: () => req<any>('/api/emotion'),
  control: (action: string, extra: Record<string, unknown> = {}) =>
    req<any>('/api/control', {
      method: 'POST',
      body: JSON.stringify({ action, ...extra }),
    }),
  confirm: (approved: boolean, id?: string) =>
    req<any>('/api/confirm', {
      method: 'POST',
      body: JSON.stringify({ approved, id }),
    }),
  hardTask: () => req<any>('/api/hard-task'),
  startHardTask: (goal: string) =>
    req<any>('/api/hard-task', { method: 'POST', body: JSON.stringify({ goal }) }),
  cancelHardTask: () => req<any>('/api/hard-task/cancel', { method: 'POST', body: '{}' }),
  jobs: () => req<{ jobs: Job[]; max_parallel: number }>('/api/jobs'),
  job: (id: string) => req<{ job: Job; steps: AgentStep[] }>(`/api/jobs/${id}`),
  startJob: (goal: string) =>
    req<any>('/api/jobs', { method: 'POST', body: JSON.stringify({ goal }) }),
  cancelJob: (id: string) =>
    req<any>(`/api/jobs/${id}/cancel`, { method: 'POST', body: '{}' }),
  pauseJob: (id: string) =>
    req<any>(`/api/jobs/${id}/pause`, { method: 'POST', body: '{}' }),
  resumeJob: (id: string) =>
    req<any>(`/api/jobs/${id}/resume`, { method: 'POST', body: '{}' }),
  steerJob: (id: string, instruction: string) =>
    req<any>(`/api/jobs/${id}/steer`, {
      method: 'POST',
      body: JSON.stringify({ instruction }),
    }),
  activity: (filters: {
    turnId?: string
    jobId?: string
    afterSeq?: number
    limit?: number
  } = {}) => {
    const query = new URLSearchParams()
    if (filters.turnId) query.set('turn_id', filters.turnId)
    if (filters.jobId) query.set('job_id', filters.jobId)
    if (filters.afterSeq) query.set('after_seq', String(filters.afterSeq))
    if (filters.limit) query.set('limit', String(filters.limit))
    return req<{ activity: ActivitySpan[] }>(`/api/activity?${query.toString()}`)
  },
  activeActivity: () => req<{ activity: ActivitySpan[] }>('/api/activity/active'),
  confirmations: () => req<{ confirmations: any[] }>('/api/confirmations?state_filter=pending'),
  schedules: () => req<{ schedules: Schedule[] }>('/api/schedules'),
  scheduleRuns: (id: string) =>
    req<{ runs: ScheduleRun[] }>(`/api/schedules/${id}/runs`),
  createSchedule: (body: Record<string, unknown>) =>
    req<any>('/api/schedules', { method: 'POST', body: JSON.stringify(body) }),
  updateSchedule: (id: string, body: Record<string, unknown>) =>
    req<any>(`/api/schedules/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteSchedule: (id: string) =>
    req<any>(`/api/schedules/${id}`, { method: 'DELETE' }),
  runSchedule: (id: string) =>
    req<any>(`/api/schedules/${id}/run`, { method: 'POST', body: '{}' }),
  pauseSchedule: (id: string) =>
    req<any>(`/api/schedules/${id}/pause`, { method: 'POST', body: '{}' }),
  resumeSchedule: (id: string) =>
    req<any>(`/api/schedules/${id}/resume`, { method: 'POST', body: '{}' }),
  computerSessions: () => req<any>('/api/computer/sessions'),
  resourceProfile: () => req<any>('/api/resource-profile'),
  putResourceProfile: (profile: 'eco' | 'balanced' | 'performance') =>
    req<any>('/api/resource-profile', {
      method: 'PUT',
      body: JSON.stringify({ profile }),
    }),
  mcp: () => req<any>('/api/mcp/status'),
  memory: () => req<any>('/api/memory'),
  dream: () => req<any>('/api/dream/run', { method: 'POST', body: '{}' }),
  panels: () => req<{ panels: PanelSummary[] }>('/api/panels'),
  clearPanels: () => req<{ ok: boolean }>('/api/panels', { method: 'DELETE' }),
  closePanel: (panelId: string) =>
    req<{ ok: boolean }>(`/api/panels/${encodeURIComponent(panelId)}`, {
      method: 'DELETE',
    }),
  // Exploding Kittens. The state that comes back is already redacted to this
  // seat by rau/games/kittens/view.py — there is no unredacted form to ask for.
  kittens: () => req<{ ok: boolean; state: unknown; record: unknown }>('/api/game/kittens'),
  dealKittens: () =>
    req<{ ok: boolean; state: unknown }>('/api/game/kittens', { method: 'POST', body: '{}' }),
  endKittens: () => req<{ ok: boolean }>('/api/game/kittens', { method: 'DELETE' }),
  kittensMove: (move: unknown) =>
    req<{ ok: boolean; state: unknown }>('/api/game/kittens/move', {
      method: 'POST',
      body: JSON.stringify(move),
    }),
  // Chess. Nothing is redacted here — both players are looking at the same
  // board — but the client is still only ever told, never asked: it sends a
  // move and finds out whether it was one.
  chess: () => req<{ ok: boolean; state: unknown; record: unknown }>('/api/game/chess'),
  // An unfinished game on disk is resumed in preference to a new one, so
  // `resumed` says which of the two just happened. Omitting the colour is the
  // normal case, and it means the sides alternate from the last finished game.
  startChess: (rauColor?: 'white' | 'black') =>
    req<{ ok: boolean; state: unknown; resumed?: boolean }>('/api/game/chess', {
      method: 'POST',
      body: JSON.stringify(rauColor ? { rau_color: rauColor } : {}),
    }),
  endChess: () => req<{ ok: boolean }>('/api/game/chess', { method: 'DELETE' }),
  chessMove: (move: unknown) =>
    req<{ ok: boolean; state: unknown }>('/api/game/chess/move', {
      method: 'POST',
      body: JSON.stringify(move),
    }),
  roomProps: () => req<{ layout: Record<string, string> }>('/api/room/props'),
  resetRoomProps: () =>
    req<{ ok: boolean; layout: Record<string, string> }>('/api/room/props/reset', {
      method: 'POST',
      body: '{}',
    }),
  chat: (text: string) =>
    req<{ ok: boolean; reply: string; turn_id: string }>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
}
