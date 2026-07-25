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

/** One background job. `hard_task` in /api/status is a view of the newest. */
export type Job = {
  id: string
  goal: string
  state: 'running' | 'awaiting_confirm' | 'done' | 'failed' | 'cancelled'
  progress: string
  result: string
  created: number
  updated: number
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
  tts_models: { id: string; label: string; note?: string }[]
  stt_providers: Record<string, SttProviderMeta>
}

export type VoiceStatus = {
  stt: {
    provider: string
    model: string
    language: string
    /** The configured backend was unusable and we degraded to local whisper. */
    fallback: boolean
    partials: boolean
    label: string
  }
  available: Record<string, boolean>
  tts_ready: boolean
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

export const api = {
  status: () => req<any>('/api/status'),
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
  startJob: (goal: string) =>
    req<any>('/api/jobs', { method: 'POST', body: JSON.stringify({ goal }) }),
  cancelJob: (id: string) =>
    req<any>(`/api/jobs/${id}/cancel`, { method: 'POST', body: '{}' }),
  mcp: () => req<any>('/api/mcp/status'),
  memory: () => req<any>('/api/memory'),
  dream: () => req<any>('/api/dream/run', { method: 'POST', body: '{}' }),
  chat: (text: string) =>
    req<{ ok: boolean; reply: string }>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ text }),
    }),
}
