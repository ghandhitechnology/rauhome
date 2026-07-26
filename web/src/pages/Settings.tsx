import { useEffect, useState } from 'react'
import { Link } from '../router'
import {
  api,
  type AuthProvider,
  type BrowseStatus,
  type Catalog,
  type ElevenVoice,
  type VoicePreset,
  type VoiceStatus,
} from '../api'
import '../components/AuthCard.css'
import './Settings.css'

/** Chat slots — the three that share a provider/model picker. */
type SlotKey = 'face' | 'subagent' | 'dream'
/** Every slot in models.json, including the ones with bespoke editors. */
type ConfigSlot = SlotKey | 'tts' | 'stt'
const SLOTS: SlotKey[] = ['face', 'subagent', 'dream']

type Check = { status: 'idle' | 'checking' | 'ok' | 'bad'; detail?: string }

export default function Settings() {
  const [models, setModels] = useState<any>(null)
  const [browseStatus, setBrowseStatus] = useState<BrowseStatus | null>(null)
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [auth, setAuth] = useState<AuthProvider[]>([])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [checks, setChecks] = useState<Record<string, Check>>({})
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const [dirty, setDirty] = useState(false)
  const [accountVoices, setAccountVoices] = useState<ElevenVoice[]>([])
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus | null>(null)
  const [voiceLoadError, setVoiceLoadError] = useState('')

  const [loadError, setLoadError] = useState('')

  async function reload() {
    setLoadError('')
    const [m, a, c, v, b] = await Promise.all([
      api.models(),
      api.auth(),
      api.catalog(),
      api.voiceStatus(),
      api.browseStatus().catch(() => null),
    ])
    setModels(m)
    setAuth(a.providers || [])
    setCatalog(c)
    setVoiceStatus(v)
    setBrowseStatus(b)
    if ((a.providers || []).some((p: AuthProvider) => p.id === 'elevenlabs' && p.configured)) {
      void loadAccountVoices()
    } else {
      setAccountVoices([])
    }
  }

  async function loadAccountVoices() {
    setVoiceLoadError('')
    try {
      const result = await api.elevenVoices()
      setAccountVoices(result.voices || [])
    } catch (e: any) {
      setVoiceLoadError(e?.message || String(e))
    }
  }

  useEffect(() => {
    reload().catch((e) => {
      const text = e.message || String(e)
      setMsg(text)
      setLoadError(text)
    })
  }, [])

  function flash(text: string) {
    setMsg(text)
    window.setTimeout(() => setMsg((cur) => (cur === text ? '' : cur)), 6000)
  }

  if (!models || !catalog) {
    return (
      <div className="settings grid-2">
        {loadError ? (
          <section className="panel">
            <h2 style={{ fontFamily: 'var(--font-display)', fontWeight: 400 }}>Settings failed to load</h2>
            <p className="muted">{loadError}</p>
            <p className="muted">
              Usually the hub is on an old process. Restart with{' '}
              <span className="mono">bash launch.sh --hub</span>, then retry.
            </p>
            <button className="btn primary" onClick={() => reload().catch((e) => setLoadError(e.message || String(e)))}>
              Retry
            </button>
          </section>
        ) : (
          [0, 1].map((i) => (
            <section key={i} className="panel">
              <div className="skeleton skeleton-line" style={{ width: '35%', height: '1.6rem' }} />
              <div className="skeleton" style={{ height: '12rem', marginTop: '1.2rem' }} />
            </section>
          ))
        )}
      </div>
    )
  }

  const configured = new Set(auth.filter((p) => p.configured).map((p) => p.id))
  const usable = Object.keys(catalog.providers).filter((p) => {
    const authId = catalog.provider_auth[p]
    return authId && configured.has(authId)
  })

  function updateSlot(slot: ConfigSlot, key: string, value: string | number) {
    setDirty(true)
    setModels((prev: any) => ({ ...prev, [slot]: { ...prev[slot], [key]: value } }))
  }

  function pickProvider(slot: SlotKey, provider: string) {
    const first = catalog?.providers?.[provider]?.models?.[0]?.id || ''
    setDirty(true)
    setModels((prev: any) => ({ ...prev, [slot]: { ...prev[slot], provider, model: first } }))
  }

  async function saveModels() {
    setBusy('models')
    try {
      const saved = await api.putModels({
        face: models.face,
        subagent: models.subagent,
        dream: models.dream,
        tts: models.tts,
        stt: models.stt,
        browse: models.browse,
      })
      setModels(saved)
      // Server clamps effort to the new provider/model capabilities.
      try {
        const ef = await api.effort()
        if (ef && typeof ef === 'object') {
          setModels((prev: any) => ({
            ...prev,
            face: { ...prev.face, effort: ef.face ?? prev.face?.effort },
            subagent: { ...prev.subagent, effort: ef.subagent ?? prev.subagent?.effort },
            dream: { ...prev.dream, effort: ef.dream ?? prev.dream?.effort },
          }))
        }
      } catch {
        /* effort refresh is best-effort */
      }
      setVoiceStatus(await api.voiceStatus())
      setDirty(false)
      flash('Voice and model settings saved — new voice sessions use them immediately.')
    } catch (e: any) {
      flash(e.message || String(e))
    } finally {
      setBusy('')
    }
  }

  async function checkAndSave(id: string) {
    const key = (drafts[id] || '').trim()
    if (!key) return
    setBusy(id)
    setChecks((c) => ({ ...c, [id]: { status: 'checking', detail: 'Calling the provider…' } }))
    try {
      const res = await api.verifyAuth(id, key)
      if (!res.ok) {
        setChecks((c) => ({ ...c, [id]: { status: 'bad', detail: res.detail || 'Key rejected.' } }))
        return
      }
      const saved = await api.setAuth(id, key)
      setAuth(saved.providers || [])
      setDrafts((d) => ({ ...d, [id]: '' }))
      setChecks((c) => ({ ...c, [id]: { status: 'ok', detail: res.detail || 'Connected.' } }))
      if (id === 'elevenlabs') void loadAccountVoices()
      if (id === 'elevenlabs' || id === 'deepgram' || id === 'codex') {
        api.voiceStatus().then(setVoiceStatus).catch(() => {})
        api.browseStatus().then(setBrowseStatus).catch(() => {})
      }
    } catch (e: any) {
      setChecks((c) => ({ ...c, [id]: { status: 'bad', detail: e?.message || String(e) } }))
    } finally {
      setBusy('')
    }
  }

  async function recheck(id: string) {
    setBusy(id)
    setChecks((c) => ({ ...c, [id]: { status: 'checking', detail: 'Re-checking saved key…' } }))
    try {
      const res = await api.verifyAuth(id)
      setChecks((c) => ({
        ...c,
        [id]: { status: res.ok ? 'ok' : 'bad', detail: res.detail || (res.ok ? 'Connected.' : 'Rejected.') },
      }))
    } catch (e: any) {
      setChecks((c) => ({ ...c, [id]: { status: 'bad', detail: e?.message || String(e) } }))
    } finally {
      setBusy('')
    }
  }

  async function clearKey(id: string) {
    setBusy(id)
    try {
      const res = await api.clearAuth(id)
      setAuth(res.providers || [])
      setChecks((c) => ({ ...c, [id]: { status: 'idle' } }))
      if (id === 'elevenlabs') setAccountVoices([])
      if (id === 'elevenlabs' || id === 'deepgram' || id === 'codex') {
        api.voiceStatus().then(setVoiceStatus).catch(() => {})
        api.browseStatus().then(setBrowseStatus).catch(() => {})
      }
      flash(`${id} disconnected.`)
    } catch (e: any) {
      flash(e.message || String(e))
    } finally {
      setBusy('')
    }
  }

  function openUrl(url?: string) {
    if (url) window.open(url, '_blank', 'noopener,noreferrer')
  }

  function choosePreset(preset: VoicePreset) {
    setDirty(true)
    setModels((prev: any) => ({
      ...prev,
      tts: {
        ...prev.tts,
        provider: 'elevenlabs',
        preset: preset.id,
        voice_id: preset.voice_id,
        effect: preset.effect,
        voice_settings: { ...preset.settings },
      },
    }))
  }

  function chooseAccountVoice(voiceId: string) {
    setDirty(true)
    setModels((prev: any) => ({
      ...prev,
      tts: {
        ...prev.tts,
        provider: 'elevenlabs',
        preset: 'custom',
        voice_id: voiceId,
        effect: 'none',
      },
    }))
  }

  async function previewVoice() {
    const tts = models.tts || {}
    if (!tts.voice_id) {
      flash('Choose a voice or enter a voice ID first.')
      return
    }
    setBusy('voice-preview')
    try {
      const blob = await api.previewVoice({
        voice_id: tts.voice_id,
        model: tts.model,
        effect: tts.effect || 'none',
        voice_settings: tts.voice_settings,
      })
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.addEventListener('ended', () => URL.revokeObjectURL(url), { once: true })
      audio.addEventListener('error', () => URL.revokeObjectURL(url), { once: true })
      await audio.play()
      flash('Playing the exact voice Rau will use.')
    } catch (e: any) {
      flash(e?.message || String(e))
    } finally {
      setBusy('')
    }
  }

  async function openComposio() {
    setBusy('composio-connect')
    try {
      const res = await api.composioConnect()
      if (res.needs_key) {
        flash(res.hint || 'Save a Composio API key first.')
        openUrl(res.open_url || res.app_url)
        return
      }
      openUrl(res.open_url || res.connect_url)
      flash('Opened Composio Connect — finish authorizing apps in the new tab.')
    } catch (e: any) {
      flash(e.message || String(e))
      openUrl('https://connect.composio.dev')
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="settings grid-2">
      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Models</h2>
            <p className="muted panel-sub">
              Face talks. Subagent does silent deep work. Dream rewrites the soul at night.
            </p>
          </div>
          {dirty && <span className="pill bad">unsaved</span>}
        </div>

        {usable.length === 0 && (
          <div className="notice bad" style={{ marginBottom: '1rem' }}>
            No provider keys yet — connect one on the right, or{' '}
            <Link to="/setup">run setup again</Link>.
          </div>
        )}

        {SLOTS.map((slot, i) => {
          const meta = catalog.slots.find((s) => s.id === slot)
          const cur = models[slot] || {}
          const list = catalog.providers[cur.provider]?.models || []
          const isCustom = !!cur.model && !list.some((m) => m.id === cur.model)
          return (
            <div key={slot} className="slot" style={{ '--i': i } as React.CSSProperties}>
              <div className="slot-title">
                <h3>{meta?.label || slot}</h3>
                <span className="slot-note">{meta?.blurb}</span>
              </div>

              <div className="slot-fields">
                <div className="field">
                  <label>Provider</label>
                  <select value={cur.provider || ''} onChange={(e) => pickProvider(slot, e.target.value)}>
                    <option value="">choose…</option>
                    {Object.keys(catalog.providers).map((p) => (
                      <option key={p} value={p}>
                        {catalog.providers[p].label}
                        {usable.includes(p) ? '' : ' (no key)'}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="field">
                  <label>Model</label>
                  <select
                    value={isCustom ? '__custom' : cur.model || ''}
                    onChange={(e) =>
                      updateSlot(slot, 'model', e.target.value === '__custom' ? '' : e.target.value)
                    }
                  >
                    <option value="">choose…</option>
                    {list.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}
                        {m.note ? ` — ${m.note}` : ''}
                      </option>
                    ))}
                    <option value="__custom">Custom model id…</option>
                  </select>
                </div>
              </div>

              {(isCustom || !cur.model) && (
                <div className="field">
                  <label>Custom model id</label>
                  <input
                    value={cur.model || ''}
                    placeholder="exact id as the provider spells it"
                    onChange={(e) => updateSlot(slot, 'model', e.target.value)}
                  />
                </div>
              )}

              <div className="slot-fields">
                <div className="field">
                  <label>Max tokens</label>
                  <input
                    type="number"
                    min={16}
                    value={cur.max_tokens ?? ''}
                    onChange={(e) => updateSlot(slot, 'max_tokens', Number(e.target.value))}
                  />
                </div>
                <div className="field">
                  <label>Temperature</label>
                  <input
                    type="number"
                    step="0.1"
                    min={0}
                    max={2}
                    value={cur.temperature ?? ''}
                    onChange={(e) => updateSlot(slot, 'temperature', Number(e.target.value))}
                  />
                </div>
              </div>
            </div>
          )
        })}

        <div className="slot voice-config">
          <div className="slot-title">
            <h3>Voice</h3>
            <span className="slot-note">
              Four ready-made personalities, or any ElevenLabs voice your key can access.
            </span>
          </div>

          {!configured.has('elevenlabs') && (
            <div className="notice bad voice-connect-note">
              ElevenLabs is not connected. Paste your own key in Connections to enable previews and
              spoken replies.
            </div>
          )}

          <div className="voice-preset-grid">
            {(catalog.voice_presets || []).map((preset) => (
              <button
                key={preset.id}
                type="button"
                className={`voice-preset ${models.tts?.preset === preset.id ? 'selected' : ''}`}
                onClick={() => choosePreset(preset)}
              >
                <strong>{preset.label}</strong>
                <span>{preset.note}</span>
                <em>{preset.voice_name}</em>
              </button>
            ))}
          </div>

          <div className="slot-fields voice-advanced">
            <div className="field">
              <label>Your ElevenLabs voices</label>
              <select
                value={
                  accountVoices.some((v) => v.id === models.tts?.voice_id)
                    ? models.tts.voice_id
                    : ''
                }
                disabled={!configured.has('elevenlabs') || !accountVoices.length}
                onChange={(e) => chooseAccountVoice(e.target.value)}
              >
                <option value="">
                  {configured.has('elevenlabs')
                    ? accountVoices.length
                      ? 'choose an account voice…'
                      : 'loading voices…'
                    : 'connect a key first'}
                </option>
                {accountVoices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                    {v.labels?.age ? ` · ${v.labels.age}` : ''}
                    {v.labels?.gender ? ` · ${v.labels.gender}` : ''}
                  </option>
                ))}
              </select>
              {voiceLoadError && <span className="field-hint bad">{voiceLoadError}</span>}
            </div>
            <div className="field">
              <label>Custom voice ID</label>
              <input
                value={models.tts?.voice_id || ''}
                placeholder="paste an ElevenLabs voice ID"
                spellCheck={false}
                onChange={(e) => chooseAccountVoice(e.target.value.trim())}
              />
            </div>
          </div>

          <div className="slot-fields">
            <div className="field">
              <label>TTS model</label>
              <select
                value={models.tts?.model || ''}
                onChange={(e) => updateSlot('tts', 'model', e.target.value)}
              >
                {catalog.tts_models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                    {m.note ? ` — ${m.note}` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>Voice effect</label>
              <select
                value={models.tts?.effect || 'none'}
                onChange={(e) => updateSlot('tts', 'effect', e.target.value)}
              >
                {(catalog.voice_effects || []).map((effect) => (
                  <option key={effect.id} value={effect.id}>
                    {effect.label} — {effect.note}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="row">
            <button
              className="btn sm"
              disabled={!configured.has('elevenlabs') || busy === 'voice-preview'}
              onClick={previewVoice}
            >
              {busy === 'voice-preview' && <i className="spinner" />}
              {busy === 'voice-preview' ? 'Generating…' : 'Preview voice'}
            </button>
            <button
              className="btn sm ghost"
              disabled={!configured.has('elevenlabs')}
              onClick={() => loadAccountVoices()}
            >
              Refresh account voices
            </button>
          </div>
        </div>

        {(() => {
          const stt = models.stt || {}
          const sttMeta = catalog.stt_providers?.[stt.provider] || null
          const sttModels = sttMeta?.models || []
          // A backend whose key is missing silently degrades to local whisper
          // at request time — say so here rather than letting it surprise them.
          const sttUsable =
            !sttMeta?.auth || configured.has(sttMeta.auth)
          return (
            <div className="slot">
              <div className="slot-title">
                <h3>Hearing</h3>
                <span className="slot-note">
                  Speech-to-text for voice mode.{' '}
                  {stt.provider === 'auto' && voiceStatus
                    ? `Currently resolves to ${voiceStatus.stt.label}.`
                    : ''}
                  {stt.provider !== 'auto' && sttMeta?.partials
                    ? ' This backend streams a live transcript as you speak.'
                    : stt.provider !== 'auto'
                      ? ' This backend transcribes once you stop speaking — no live transcript.'
                      : ''}
                </span>
              </div>

              {!sttUsable && (
                <div className="notice bad" style={{ marginBottom: '0.8rem' }}>
                  No key for {sttMeta?.label} — automatic fallback will use the best connected
                  backend.
                </div>
              )}

              <div className="slot-fields">
                <div className="field">
                  <label>Provider</label>
                  <select
                    value={stt.provider || 'auto'}
                    onChange={(e) => {
                      const p = e.target.value
                      const first = catalog.stt_providers?.[p]?.models?.[0]?.id || ''
                      setDirty(true)
                      setModels((prev: any) => ({
                        ...prev,
                        stt: { ...prev.stt, provider: p, model: first },
                      }))
                    }}
                  >
                    {Object.entries(catalog.stt_providers || {}).map(([id, meta]) => (
                      <option key={id} value={id}>
                        {meta.label}
                        {!meta.auth || configured.has(meta.auth) ? '' : ' (no key)'}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="field">
                  <label>Model</label>
                  <select
                    value={stt.model || ''}
                    disabled={stt.provider === 'auto'}
                    onChange={(e) => updateSlot('stt', 'model', e.target.value)}
                  >
                    <option value="">
                      {stt.provider === 'auto' ? 'chosen automatically' : 'choose…'}
                    </option>
                    {sttModels.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.label}
                        {m.note ? ` — ${m.note}` : ''}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="field" style={{ marginBottom: 0 }}>
                <label>Recognition language</label>
                <select
                  value={stt.language || ''}
                  onChange={(e) => updateSlot('stt', 'language', e.target.value)}
                >
                  <option value="">Provider default / detect when supported</option>
                  <option value="en">English</option>
                  <option value="ko">Korean</option>
                  <option value="ja">Japanese</option>
                  <option value="zh">Chinese</option>
                  <option value="es">Spanish</option>
                  <option value="multi">Multilingual / code-switching</option>
                </select>
                <span className="field-hint">
                  Deepgram Nova-3 supports Korean as <span className="mono">ko</span>; its multilingual
                  mode covers a smaller set of languages.
                </span>
              </div>
            </div>
          )
        })()}

        {(() => {
          const browse = models.browse || {}
          const chosen = browse.provider || 'auto'
          const browseMeta = catalog.browse_providers?.[chosen] || null
          // "Connected" here means the key exists; `auto` needs any one of them.
          const usable =
            chosen === 'auto'
              ? Object.entries(catalog.browse_providers || {}).some(
                  ([id, meta]) => id !== 'auto' && meta.auth && configured.has(meta.auth),
                )
              : !browseMeta?.auth || configured.has(browseMeta.auth)
          return (
            <div className="slot">
              <div className="slot-title">
                <h3>Reading the web</h3>
                <span className="slot-note">
                  How Rau opens a page when you ask him to look something up. He
                  walks over to the computer to do it.
                  {browseStatus?.ready && chosen === 'auto'
                    ? ` Currently resolves to ${browseStatus.provider}.`
                    : ''}
                </span>
              </div>

              {!usable && (
                <div className="notice bad" style={{ marginBottom: '0.8rem' }}>
                  {chosen === 'auto'
                    ? 'No Firecrawl or Browserbase key yet — connect one on the right and he can read the web.'
                    : `No key for ${browseMeta?.label} — connect one on the right, or pick the other backend.`}
                </div>
              )}

              <div className="slot-fields">
                <div className="field">
                  <label>Backend</label>
                  <select
                    value={chosen}
                    onChange={(e) => {
                      setDirty(true)
                      setModels((prev: any) => ({
                        ...prev,
                        browse: { ...prev.browse, provider: e.target.value },
                      }))
                    }}
                  >
                    {Object.entries(catalog.browse_providers || {}).map(([id, meta]) => (
                      <option key={id} value={id}>
                        {meta.label}
                        {id !== 'auto' && meta.auth && !configured.has(meta.auth)
                          ? ' (no key)'
                          : ''}
                      </option>
                    ))}
                  </select>
                  <span className="field-hint">{browseMeta?.blurb}</span>
                </div>
              </div>

              {browseMeta && !browseMeta.can_search && (
                <span className="field-hint">
                  This backend opens a url you give it but cannot search the web.
                  Firecrawl can do both.
                </span>
              )}
            </div>
          )
        })()}

        <div className="row end sticky-save">
          <button className="btn primary" disabled={busy === 'models'} onClick={saveModels}>
            {busy === 'models' && <i className="spinner" />}
            {busy === 'models' ? 'Saving…' : 'Save models'}
          </button>
        </div>
      </section>

      <section className="panel">
        <div className="panel-head">
          <div>
            <h2>Connections</h2>
            <p className="muted panel-sub">
              Keys are checked live, then written to <span className="mono">.env</span> on this
              machine only.
            </p>
          </div>
        </div>

        <div className="auth-list">
          {auth.map((p, i) => {
            const c = checks[p.id] || { status: 'idle' as const }
            return (
              <article
                id={`connection-${p.id}`}
                key={p.id}
                className={`auth-card ${p.configured ? 'ok' : ''} ${c.status === 'bad' ? 'bad' : ''}`}
                style={{ '--i': i } as React.CSSProperties}
              >
                <div className="auth-head static">
                  <span className="auth-title">
                    <span className="auth-name">{p.label}</span>
                    <span className="auth-help">{p.help}</span>
                  </span>
                  <span className={`pill ${p.configured ? 'on' : 'off'}`}>
                    <i className="pill-dot" />
                    {p.configured ? p.masked || 'connected' : 'not connected'}
                  </span>
                </div>

                <div className="auth-body-inner">
                  <div className="field">
                    <label>{p.env}</label>
                    <input
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      placeholder={p.configured ? '•••• paste a new key to replace' : 'paste API key'}
                      value={drafts[p.id] || ''}
                      onChange={(e) => setDrafts((d) => ({ ...d, [p.id]: e.target.value }))}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') checkAndSave(p.id)
                      }}
                    />
                  </div>

                  {c.status !== 'idle' && (
                    <p className={`verify-line ${c.status}`}>
                      {c.status === 'checking' && <i className="spinner" />}
                      {c.status === 'ok' && <i className="tick" />}
                      {c.status === 'bad' && <i className="cross" />}
                      {c.detail}
                    </p>
                  )}

                  <div className="row">
                    <button
                      className="btn primary sm"
                      disabled={busy === p.id || !(drafts[p.id] || '').trim()}
                      onClick={() => checkAndSave(p.id)}
                    >
                      {busy === p.id && <i className="spinner" />}
                      {busy === p.id ? 'Checking…' : p.configured ? 'Replace key' : 'Check & save'}
                    </button>
                    {p.configured && (
                      <button className="btn sm" disabled={busy === p.id} onClick={() => recheck(p.id)}>
                        Re-check
                      </button>
                    )}
                    <button className="btn sm ghost" onClick={() => openUrl(p.docs_url)}>
                      Get key ↗
                    </button>
                    {p.id === 'composio' && (
                      <button
                        className="btn sm"
                        disabled={busy === 'composio-connect'}
                        onClick={openComposio}
                      >
                        {busy === 'composio-connect' ? 'Opening…' : 'App connect'}
                      </button>
                    )}
                    {p.id === 'kimi_code' && p.connect_url && (
                      <button className="btn sm ghost" onClick={() => openUrl(p.connect_url)}>
                        Kimi Code ↗
                      </button>
                    )}
                    {p.configured && (
                      <button
                        className="btn sm danger"
                        disabled={busy === p.id}
                        onClick={() => clearKey(p.id)}
                      >
                        Disconnect
                      </button>
                    )}
                  </div>
                </div>
              </article>
            )
          })}
        </div>

        <h3 className="section-title">Maintenance</h3>
        <div className="row">
          <button
            className="btn"
            disabled={busy === 'dream'}
            onClick={() => {
              setBusy('dream')
              api
                .dream()
                .then(() => flash('Dream pass complete — soul.md may have changed.'))
                .catch((e) => flash(e.message || String(e)))
                .finally(() => setBusy(''))
            }}
          >
            {busy === 'dream' && <i className="spinner" />}
            {busy === 'dream' ? 'Dreaming…' : 'Run dream now'}
          </button>
          <Link to="/setup" className="btn">
            Re-run setup
          </Link>
        </div>

        {msg && <p className="msg-line">{msg}</p>}
      </section>
    </div>
  )
}
