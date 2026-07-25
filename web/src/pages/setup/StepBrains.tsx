import { useState } from 'react'
import { api } from '../../api'
import { CHAT_AUTH_IDS, type StepProps } from './types'

const RECOMMENDED = 'openrouter'

export default function StepBrains({ state, catalog, reload, verify, setVerify }: StepProps) {
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState('')
  const [open, setOpen] = useState<string | null>(null)

  const providers = (state?.providers || []).filter((p) => CHAT_AUTH_IDS.includes(p.id))
  const connected = providers.filter((p) => p.configured).length

  /** Prove the key works before writing it to .env — a bad key never gets saved. */
  async function checkAndSave(id: string) {
    const key = (drafts[id] || '').trim()
    if (!key) return
    setBusy(id)
    setVerify(id, { status: 'checking', detail: 'Calling the provider…' })
    try {
      const res = await api.verifyAuth(id, key)
      if (!res.ok) {
        setVerify(id, { status: 'bad', detail: res.detail || 'Key rejected.' })
        return
      }
      await api.setAuth(id, key)
      setVerify(id, { status: 'ok', detail: res.detail || 'Connected.' })
      setDrafts((d) => ({ ...d, [id]: '' }))
      setOpen(null)
      await reload()
    } catch (e: any) {
      setVerify(id, { status: 'bad', detail: e?.message || String(e) })
    } finally {
      setBusy('')
    }
  }

  async function recheck(id: string) {
    setBusy(id)
    setVerify(id, { status: 'checking', detail: 'Re-checking saved key…' })
    try {
      const res = await api.verifyAuth(id)
      setVerify(id, {
        status: res.ok ? 'ok' : 'bad',
        detail: res.detail || (res.ok ? 'Connected.' : 'Key rejected.'),
      })
    } catch (e: any) {
      setVerify(id, { status: 'bad', detail: e?.message || String(e) })
    } finally {
      setBusy('')
    }
  }

  async function disconnect(id: string) {
    setBusy(id)
    try {
      await api.clearAuth(id)
      setVerify(id, { status: 'idle' })
      await reload()
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="step">
      <header className="step-head">
        <p className="eyebrow">Step three</p>
        <h2>Give Rau something to think with</h2>
        <p className="step-lede">
          Keys are checked against the live provider before anything is written, then stored in{' '}
          <span className="mono">.env</span> on this machine only. One provider is enough to finish.
        </p>
      </header>

      <div className={`tally ${connected ? 'ok' : ''}`}>
        <span className="tally-count">{connected}</span>
        <span>
          {connected === 0
            ? 'no providers connected yet — connect at least one'
            : `provider${connected > 1 ? 's' : ''} connected`}
        </span>
      </div>

      <div className="auth-list">
        {providers.map((p, i) => {
          const v = verify[p.id] || { status: 'idle' as const }
          const isOpen = open === p.id || (!p.configured && open === null && i === 0)
          const meta = catalog?.providers?.[p.id]
          return (
            <article
              key={p.id}
              className={`auth-card ${p.configured ? 'ok' : ''} ${v.status === 'bad' ? 'bad' : ''}`}
              style={{ '--i': i } as React.CSSProperties}
            >
              <button className="auth-head" onClick={() => setOpen(isOpen ? '' : p.id)}>
                <span className="auth-title">
                  <span className="auth-name">
                    {p.label}
                    {p.id === RECOMMENDED && <em className="tag">easiest start</em>}
                  </span>
                  <span className="auth-help">{meta?.blurb || p.help}</span>
                </span>
                <span className={`pill ${p.configured ? 'on' : 'off'}`}>
                  <i className="pill-dot" />
                  {p.configured ? p.masked || 'connected' : 'not connected'}
                </span>
              </button>

              <div className={`auth-body ${isOpen ? 'open' : ''}`}>
                <div className="auth-body-inner">
                  <div className="field">
                    <label>{p.env}</label>
                    <input
                      type="password"
                      autoComplete="off"
                      spellCheck={false}
                      placeholder={p.configured ? 'paste a new key to replace' : 'paste API key'}
                      value={drafts[p.id] || ''}
                      onChange={(e) => setDrafts((d) => ({ ...d, [p.id]: e.target.value }))}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault()
                          checkAndSave(p.id)
                        }
                      }}
                    />
                  </div>

                  {v.status !== 'idle' && (
                    <p className={`verify-line ${v.status}`}>
                      {v.status === 'checking' && <i className="spinner" />}
                      {v.status === 'ok' && <i className="tick" />}
                      {v.status === 'bad' && <i className="cross" />}
                      {v.detail}
                    </p>
                  )}

                  <div className="row">
                    <button
                      className="btn primary sm"
                      disabled={busy === p.id || !(drafts[p.id] || '').trim()}
                      onClick={() => checkAndSave(p.id)}
                    >
                      {busy === p.id && <i className="spinner" />}
                      {busy === p.id ? 'Checking…' : 'Check & save'}
                    </button>
                    {p.configured && (
                      <button className="btn sm" disabled={busy === p.id} onClick={() => recheck(p.id)}>
                        Re-check
                      </button>
                    )}
                    <button
                      className="btn sm ghost"
                      onClick={() => window.open(p.docs_url, '_blank', 'noopener,noreferrer')}
                    >
                      Get a key ↗
                    </button>
                    {p.configured && (
                      <button
                        className="btn sm danger"
                        disabled={busy === p.id}
                        onClick={() => disconnect(p.id)}
                      >
                        Disconnect
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </article>
          )
        })}
      </div>
    </div>
  )
}
