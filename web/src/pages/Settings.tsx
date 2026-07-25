import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type AuthProvider, type Catalog } from '../api'
import './Settings.css'

/** Chat slots — the three that share a provider/model picker. */
type SlotKey = 'face' | 'subagent' | 'dream'
/** Every slot in models.json, including the ones with bespoke editors. */
type ConfigSlot = SlotKey | 'tts' | 'stt'
const SLOTS: SlotKey[] = ['face', 'subagent', 'dream']

type Check = { status: 'idle' | 'checking' | 'ok' | 'bad'; detail?: string }

export default function Settings() {
  const [models, setModels] = useState<any>(null)
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [auth, setAuth] = useState<AuthProvider[]>([])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [checks, setChecks] = useState<Record<string, Check>>({})
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const [dirty, setDirty] = useState(false)

  const [loadError, setLoadError] = useState('')

  async function reload() {
    setLoadError('')
    const [m, a, c] = await Promise.all([api.models(), api.auth(), api.catalog()])
    setModels(m)
    setAuth(a.providers || [])
    setCatalog(c)
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
      })
      setModels(saved)
      setDirty(false)
      flash('Models saved — hot-swapped for new requests.')
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

        {configured.has('elevenlabs') && (
          <div className="slot">
            <div className="slot-title">
              <h3>Voice</h3>
              <span className="slot-note">Which ElevenLabs voice speaks the face's replies.</span>
            </div>
            <div className="slot-fields">
              <div className="field">
                <label>Voice</label>
                <select
                  value={models.tts?.voice_id || ''}
                  onChange={(e) => {
                    setDirty(true)
                    setModels((p: any) => ({ ...p, tts: { ...p.tts, voice_id: e.target.value } }))
                  }}
                >
                  {catalog.voices.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label}
                      {v.note ? ` — ${v.note}` : ''}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>TTS model</label>
                <select
                  value={models.tts?.model || ''}
                  onChange={(e) => {
                    setDirty(true)
                    setModels((p: any) => ({ ...p, tts: { ...p.tts, model: e.target.value } }))
                  }}
                >
                  {catalog.tts_models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                      {m.note ? ` — ${m.note}` : ''}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </div>
        )}

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
                  Speech-to-text for voice mode.
                  {sttMeta?.partials
                    ? ' This backend streams a live transcript as you speak.'
                    : ' This backend transcribes once you stop speaking — no live transcript.'}
                </span>
              </div>

              {!sttUsable && (
                <div className="notice bad" style={{ marginBottom: '0.8rem' }}>
                  No key for {sttMeta?.label} — voice mode will fall back to local whisper until
                  you connect one.
                </div>
              )}

              <div className="slot-fields">
                <div className="field">
                  <label>Provider</label>
                  <select
                    value={stt.provider || 'local'}
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
                    onChange={(e) => updateSlot('stt', 'model', e.target.value)}
                  >
                    <option value="">choose…</option>
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
                <label>Language (blank = auto-detect)</label>
                <input
                  value={stt.language || ''}
                  placeholder="en"
                  onChange={(e) => updateSlot('stt', 'language', e.target.value)}
                />
              </div>
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
